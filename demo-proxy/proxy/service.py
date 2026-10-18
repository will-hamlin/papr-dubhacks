"""Order pipeline: authenticate -> authorize -> propose spec -> policy check -> search payload -> engine.
Purchase hook: the engine reports a completed purchase for an accepted order -> spend counters move.

POST /orders takes two shapes:
- signed auth: {auth, request_text}; the user, limits and caps come from data/*.json.
- the employee dashboard's envelope (generic-enterprise/DASHBOARD.md): {request, userConfig, companyConfig}
  with a bearer token; the user's limit comes from the dashboard profiles, retries dedupe on request.id.

The proxy never holds payment credentials and never lets request text change limits or policy.
Every call to handle_order or handle_purchase writes exactly one audit entry.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from .audit import AuditLog
from .engine import Engine, EngineError, HttpEngine, StubEngine
from .gates import authorize, build_search, check_policy
from .models import DashboardOrder, OrderBody, User
from .signing import AuthError, canonical_json, check_auth, sign_payload, verify_payload
from .spec import DEFAULT_WEIGHTS, FallbackSpecParser, ParseError, make_parser
from .store import PolicyStore, load_users

ROOT = Path(__file__).resolve().parent.parent
PURCHASE_FIELDS = {"order_id", "total_cents", "proxy_sig"}
# Outcomes a retry may change (auth fixed, engine/parser back up) are not replayed.
NOT_REPLAYED = {400, 401, 409, 502, 503}


@dataclass
class Settings:
    shared_secret: str = ""
    api_token: str = ""
    engine_url: str | None = None
    engine_path: str = "/search"
    data_dir: Path = ROOT / "data"
    var_dir: Path = ROOT / "var"

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls(shared_secret=os.environ.get("PROXY_SHARED_SECRET", ""),
                api_token=os.environ.get("PROXY_API_TOKEN", ""),
                engine_url=os.environ.get("ENGINE_URL") or None,
                engine_path=os.environ.get("ENGINE_PATH", "/search"))
        if os.environ.get("PROXY_VAR_DIR"):
            s.var_dir = Path(os.environ["PROXY_VAR_DIR"])
        return s


@dataclass
class Outcome:
    status: int
    body: dict


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _errors(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())


class Proxy:
    def __init__(self, settings: Settings, parser=None, engine: Engine | None = None,
                 clock: Callable[[], datetime] | None = None):
        if not settings.shared_secret:
            raise RuntimeError("PROXY_SHARED_SECRET is not set; refusing to start")
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        settings.var_dir.mkdir(parents=True, exist_ok=True)
        self.users = load_users(settings.data_dir)
        self.policy = PolicyStore(settings.data_dir, settings.var_dir, self.clock)
        self.audit = AuditLog(settings.var_dir / "audit.jsonl")
        self.parser = parser or make_parser()
        if engine is not None:
            self.engine = engine
        elif settings.engine_url:
            self.engine = HttpEngine(settings.engine_url, settings.engine_path)
        else:
            self.engine = StubEngine()
        # Rebuilt from the audit log so a restart remembers accepted orders, recorded purchases and
        # dashboard request ids.
        self.accepted: dict[str, dict] = {}   # order_id -> {max_total_cents, job_number, company_caps}
        self.purchased: dict[str, int] = {}   # order_id -> total_cents
        self.requests: dict[str, dict] = {}   # dashboard request.id -> {fingerprint, status, body}
        self.in_flight: set[str] = set()
        for e in self.audit.entries():
            if e.get("kind") == "order" and e.get("decision") == "accepted":
                self._remember_order(e["order_id"], e)
            elif e.get("kind") == "purchase":
                self.purchased[e["order_id"]] = e["total_cents"]
            if e.get("response") and e.get("request_id"):
                self.requests[e["request_id"]] = {"fingerprint": e["request_fingerprint"], **e["response"]}

    def _remember_order(self, order_id: str, record: dict) -> None:
        self.accepted[order_id] = {"max_total_cents": record["max_total_cents"],
                                   "job_number": record.get("job_number"),
                                   "company_caps": record.get("source") != "dashboard"}

    def _done(self, order_id: str, status: int, decision: str, reason: str | None, record: dict,
              extra: dict | None = None) -> Outcome:
        ok = decision == "accepted"
        if ok:
            self._remember_order(order_id, record)
        body = {"ok": ok, "order_id": order_id, "decision": decision}
        if record.get("request_id"):
            body["request_id"] = record["request_id"]
        if reason:
            body["reason"] = reason
        body = {**body, **(extra or {})}
        entry = {"at": _iso(self.clock()), "order_id": order_id,
                 "kind": "order" if ok else "attempt", "decision": decision, "reason": reason, **record}
        if record.get("request_fingerprint") and status not in NOT_REPLAYED:
            self.requests[record["request_id"]] = {"fingerprint": record["request_fingerprint"],
                                                   "status": status, "body": body}
            entry["response"] = {"status": status, "body": body}
        self.audit.append(entry)
        return Outcome(status, body)

    async def handle_order(self, raw: Any, authorization: str | None = None) -> Outcome:
        order_id = "o_" + secrets.token_hex(6)
        if isinstance(raw, dict) and "request" in raw:
            return await self._dashboard_order(order_id, raw, authorization)
        text = raw.get("request_text") if isinstance(raw, dict) else None
        record: dict = {"user_id": None, "request_text": text if isinstance(text, str) else None}

        try:
            body = OrderBody.model_validate(raw)
        except ValidationError as e:
            return self._done(order_id, 400, "bad_request", _errors(e), record)

        # 1. Authenticate the caller's signed auth object.
        try:
            user_id = check_auth(body.auth, self.settings.shared_secret, now=self.clock())
        except AuthError as e:
            return self._done(order_id, 401, "not_authorized", f"invalid auth: {e}", record)
        user = self.users.get(user_id)
        record["user_id"] = user_id
        if user is None:
            return self._done(order_id, 401, "not_authorized", "unknown user", record)
        record.update(user_name=user.name, job_number=user.job_number, cost_code=user.cost_code)

        company = {"id": self.policy.policy.id, "name": self.policy.policy.name}
        return await self._run_order(order_id, user, body.request_text, record, company, company_caps=True)

    async def _dashboard_order(self, order_id: str, raw: dict, authorization: str | None) -> Outcome:
        req = raw.get("request")
        text = req.get("text") if isinstance(req, dict) else None
        rid = req.get("id") if isinstance(req, dict) else None
        record: dict = {"source": "dashboard", "user_id": None,
                        "request_id": rid[:200] if isinstance(rid, str) else None,
                        "request_text": text if isinstance(text, str) else None}

        try:
            body = DashboardOrder.model_validate(raw)
        except ValidationError as e:
            return self._done(order_id, 400, "bad_request", _errors(e), record)

        # 1. Authenticate: the dashboard relay sends "Authorization: Bearer <PROXY_API_TOKEN>".
        token = self.settings.api_token
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not token:
            return self._done(order_id, 401, "not_authorized", "PROXY_API_TOKEN is not set on the proxy", record)
        if not hmac.compare_digest(given.encode(), token.encode()):
            return self._done(order_id, 401, "not_authorized", "missing or wrong bearer token", record)

        u, c = body.userConfig, body.companyConfig
        record.update(user_id=u.employeeId, user_name=u.name, company_id=c.companyId, cost_code=u.costCenter)
        if u.companyId != c.companyId:
            return self._done(order_id, 400, "bad_request",
                              f"userConfig.companyId {u.companyId} does not match companyConfig.companyId", record)
        if u.currency != "USD" or c.currency != "USD":
            return self._done(order_id, 400, "bad_request", "only USD is supported", record)

        # 2. Retries: the dashboard keeps request.id on a retry. Same request -> the first answer again.
        fingerprint = hashlib.sha256(canonical_json(
            {"employeeId": u.employeeId, "companyId": c.companyId, "text": body.request.text})).hexdigest()
        prior = self.requests.get(body.request.id)
        if prior is not None:
            if prior["fingerprint"] != fingerprint:
                return self._done(order_id, 409, "conflict",
                                  "request.id was already used for a different employee, company or text", record)
            self.audit.append({"at": _iso(self.clock()), "order_id": prior["body"]["order_id"],
                               "kind": "attempt", "decision": "duplicate_request", "reason": None, **record})
            return Outcome(prior["status"], {**prior["body"], "duplicate": True})
        if body.request.id in self.in_flight:
            return self._done(order_id, 409, "conflict", "this request.id is still being processed", record)
        record["request_fingerprint"] = fingerprint

        # The dashboard profile sets the limit: approvalLimit, lowered to approvalRequiredAbove when set
        # (the proxy has no approval step). The company's daily/job caps in data/ don't apply.
        limit = u.approvalLimit
        if c.purchasePolicy.approvalRequiredAbove is not None:
            limit = min(limit, c.purchasePolicy.approvalRequiredAbove)
        user = User(id=u.employeeId, name=u.name, email=u.email, role=u.role, cost_code=u.costCenter,
                    spend_limit_cents=limit, purchasing_enabled=True, ship_to=c.billingAddress)
        extra_limits = {"preferred_vendors": c.purchasePolicy.preferredVendors[:20]}
        self.in_flight.add(body.request.id)
        try:
            return await self._run_order(order_id, user, body.request.text, record,
                                         {"id": c.companyId, "name": c.name}, company_caps=False,
                                         extra_limits=extra_limits)
        finally:
            self.in_flight.discard(body.request.id)

    async def _run_order(self, order_id: str, user: User, request_text: str, record: dict, company: dict,
                         company_caps: bool, extra_limits: dict | None = None) -> Outcome:
        # 2. Authorize: user-level checks.
        spent_today, spent_on_job = self.policy.spend(user.job_number) if company_caps else (0, 0)
        reasons = authorize(user, self.policy.policy, spent_today, spent_on_job, company_caps)
        if reasons:
            return self._done(order_id, 403, "not_authorized", "; ".join(reasons), record)

        # 3. Propose a spec (Claude, or rules). Probabilistic: checked below.
        note = None
        try:
            if isinstance(self.parser, FallbackSpecParser):
                proposal, source, note = await self.parser.parse_with_source(request_text)
            else:
                proposal, source = await self.parser.parse(request_text), self.parser.name
        except ParseError as e:
            return self._done(order_id, 503, "parser_error", str(e), record)
        record["parser"] = source
        record["proposal"] = proposal.model_dump()

        # 4. Company policy, checked deterministically on the proposal AND the raw text.
        violations = check_policy(proposal, request_text, self.policy.policy)
        if violations:
            return self._done(order_id, 403, "violates_company_policy", "; ".join(violations), record)
        if not proposal.understood or not proposal.item.strip():
            return self._done(order_id, 422, "unclear_request",
                              proposal.unclear_reason or "could not tell what to buy", record)

        # 5. Specs + weights + spending limits for the engine, signed so it can't be altered in transit.
        search = build_search(proposal, user, self.policy.policy, spent_today, spent_on_job, DEFAULT_WEIGHTS,
                              company_caps)
        if search.errors:
            return self._done(order_id, 422, "unclear_request", "; ".join(search.errors), record)
        search.limits.update(extra_limits or {})
        notes = search.notes + ([note] if note else [])
        payload = sign_payload({
            "order_id": order_id,
            "issued_at": _iso(self.clock()),
            "company": company,
            "requester": {"user_id": user.id, "name": user.name, "job_number": user.job_number,
                          "cost_code": user.cost_code, "ship_to": user.ship_to},
            "request_text": request_text,
            "specs": search.specs,
            "weights": search.weights,
            "priority": search.priority,
            "limits": search.limits,
        }, self.settings.shared_secret)
        record.update(specs=search.specs, weights=search.weights,
                      max_total_cents=search.limits["max_total_cents"], notes=notes)

        # 6. Forward to the engine and return its answer.
        try:
            result = await self.engine.search(payload)
        except EngineError as e:
            return self._done(order_id, 502, "engine_error", str(e), record,
                              {"specs": search.specs, "weights": search.weights})
        return self._done(order_id, 200, "accepted", None, record, {
            "parser": source, "notes": notes, "specs": search.specs, "weights": search.weights,
            "priority": search.priority, "limits": search.limits, "engine": result})

    def _purchase_done(self, order_id: str | None, status: int, decision: str, reason: str | None,
                       record: dict) -> Outcome:
        ok = decision in ("recorded", "duplicate")
        self.audit.append({"at": _iso(self.clock()), "order_id": order_id,
                           "kind": "purchase" if decision == "recorded" else "purchase_attempt",
                           "decision": decision, "reason": reason, **record})
        body = {"ok": ok, "order_id": order_id, "decision": decision}
        if reason:
            body["reason"] = reason
        return Outcome(status, body)

    def handle_purchase(self, raw: Any) -> Outcome:
        """The engine / payment gate reports a completed purchase. Synchronous on purpose: no await between
        the checks and the counter update, so two reports for one order can't interleave."""
        claimed = raw.get("order_id") if isinstance(raw, dict) else None
        order_id = claimed[:64] if isinstance(claimed, str) else None
        record: dict = {"total_cents": raw.get("total_cents") if isinstance(raw, dict) else None}

        if not isinstance(raw, dict) or set(raw) != PURCHASE_FIELDS:
            return self._purchase_done(order_id, 400, "bad_request",
                                       "body must contain exactly order_id, total_cents, proxy_sig", record)
        if not verify_payload(raw, self.settings.shared_secret):
            return self._purchase_done(order_id, 401, "not_authorized", "bad signature", record)

        order = self.accepted.get(claimed) if isinstance(claimed, str) else None
        if order is None:
            return self._purchase_done(order_id, 404, "unknown_order", "no accepted order with this order_id", record)
        record.update(job_number=order["job_number"], max_total_cents=order["max_total_cents"])

        total = raw["total_cents"]
        if order_id in self.purchased:
            if total == self.purchased[order_id] and type(total) is int:
                return self._purchase_done(order_id, 200, "duplicate", None, record)
            return self._purchase_done(order_id, 409, "conflict",
                                       f"purchase already recorded with total_cents={self.purchased[order_id]}",
                                       {**record, "flagged": True})
        if type(total) is not int or total < 0:
            return self._purchase_done(order_id, 409, "invalid_total",
                                       "total_cents must be a non-negative integer", {**record, "flagged": True})
        if total > order["max_total_cents"]:
            return self._purchase_done(order_id, 409, "over_limit",
                                       f"total_cents {total} exceeds the order's max_total_cents "
                                       f"{order['max_total_cents']}", {**record, "flagged": True})

        # Spend first, then audit: a crash in between over-counts (fails closed) rather than under-counts.
        # Dashboard orders aren't held to data/'s company caps, so they don't move those counters either.
        if order["company_caps"]:
            self.policy.record_purchase(order["job_number"], total)
        self.purchased[order_id] = total
        if order["company_caps"]:
            spent_today, spent_on_job = self.policy.spend(order["job_number"])
            record.update(spent_today_cents=spent_today, spent_on_job_cents=spent_on_job)
        return self._purchase_done(order_id, 200, "recorded", None, record)
