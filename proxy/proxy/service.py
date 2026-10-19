"""Authenticate, authorize, and deliver decisions to MS. No proof or product parsing."""
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
from .handoff import HandoffError, MainServiceClient, Outbox
from .gates import authorize, check_request_policy, compile_limits
from .models import DashboardOrder, OrderBody, User
from .signing import AuthError, canonical_json, check_auth, sign_payload, verify_payload
from .store import PolicyStore, load_users
from .accounts import AccountStore
from .models import AccountOrder

ROOT = Path(__file__).resolve().parent.parent
PURCHASE_FIELDS = {"order_id", "total_cents", "proxy_sig"}
# Malformed, unauthenticated, and conflicting attempts can be retried after correction.
NOT_REPLAYED = {400, 401, 409, 502, 503}


@dataclass
class Settings:
    shared_secret: str = ""
    api_token: str = ""
    main_service_url: str = "http://127.0.0.1:8001"
    data_dir: Path = ROOT / "data"
    var_dir: Path = ROOT / "var"
    public_url: str = "http://127.0.0.1:8000"
    allow_legacy_config: bool = False
    dynamic_registration: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls(shared_secret=os.environ.get("PROXY_SHARED_SECRET", ""),
                api_token=os.environ.get("PROXY_API_TOKEN", ""),
                main_service_url=os.environ.get("MAIN_SERVICE_URL", "http://127.0.0.1:8001"),
                public_url=os.environ.get("PROXY_PUBLIC_URL", "http://127.0.0.1:8000").rstrip('/'),
                allow_legacy_config=os.environ.get("PROXY_ALLOW_LEGACY_CONFIG") == "1",
                dynamic_registration=os.environ.get("PROXY_DYNAMIC_REGISTRATION") == "1")
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
    def __init__(self, settings: Settings, main_service=None,
                 clock: Callable[[], datetime] | None = None):
        if not settings.shared_secret:
            raise RuntimeError("PROXY_SHARED_SECRET is not set; refusing to start")
        if os.environ.get("PAPR_ENV") == "production":
            from urllib.parse import urlsplit
            public = urlsplit(settings.public_url)
            if (len(settings.shared_secret) < 32 or len(settings.api_token) < 32
                    or settings.shared_secret == settings.api_token):
                raise RuntimeError("Production requires distinct PROXY_SHARED_SECRET and PROXY_API_TOKEN of at least 32 characters")
            if public.scheme != "https" or not public.hostname or public.username or public.password:
                raise RuntimeError("Production requires an HTTPS PROXY_PUBLIC_URL")
            if settings.allow_legacy_config:
                raise RuntimeError("Production forbids PROXY_ALLOW_LEGACY_CONFIG=1")
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        settings.var_dir.mkdir(parents=True, exist_ok=True)
        self.users = load_users(settings.data_dir)
        self.policy = PolicyStore(settings.data_dir, settings.var_dir, self.clock)
        self.audit = AuditLog(settings.var_dir / "audit.jsonl")
        self.main_service = main_service or MainServiceClient(settings.main_service_url)
        self.outbox = Outbox(settings.var_dir / "outbox.sqlite3")
        self.accounts = AccountStore(settings.var_dir / "accounts.sqlite3", self.clock)
        self.owners: dict[str, str] = {}
        # Rebuilt from the audit log so a restart remembers accepted orders, recorded purchases and
        # dashboard request ids.
        self.accepted: dict[str, dict] = {}   # order_id -> {max_total_cents, job_number, company_caps}
        self.purchased: dict[str, int] = {}   # order_id -> total_cents
        self.requests: dict[str, dict] = {}   # dashboard request.id -> {fingerprint, status, body}
        self.in_flight: set[str] = set()
        for e in self.audit.entries():
            if e.get("account_id") and e.get("order_id"):
                self.owners[e["order_id"]] = e["account_id"]
            if e.get("kind") == "order" and e.get("decision") == "accepted":
                self._remember_order(e["order_id"], e)
            elif e.get("kind") == "purchase":
                self.purchased[e["order_id"]] = e["total_cents"]
            if e.get("response") and e.get("request_id"):
                self.requests[e["request_id"]] = {"fingerprint": e["request_fingerprint"], **e["response"]}

    def _remember_order(self, order_id: str, record: dict) -> None:
        self.accepted[order_id] = {"max_total_cents": record["max_total_cents"],
                                   "job_number": record.get("job_number"),
                                   "company_caps": record.get("source") != "dashboard",
                                   "account_company": record.get("account_company")}

    async def _done(self, order_id: str, status: int, decision: str, reason: str | None, record: dict,
              extra: dict | None = None) -> Outcome:
        ok = decision == "accepted"
        if record.get('account_id'):
            self.owners[order_id] = record['account_id']
        handoff = sign_payload({
            "version": 1, "order_id": order_id, "issued_at": _iso(self.clock()),
            "authorization": {"accepted": ok, "decision": decision, "reason": reason,
                              "http_status": status, "identity_verified": record.get("identity_verified", False)},
            "request": record.get("request", {"text": record.get("request_text")}),
            "organization": record.get("organization", {}),
            "user": record.get("user", {}),
            "company": record.get("company", {}),
            "requester": record.get("requester", {}),
            "limits": record.get("limits", {}) if ok else {},
        }, self.settings.shared_secret)
        self.outbox.add(handoff)
        receipt = {"order_id": order_id, "status": "delivery_pending"}
        extra = {**(extra or {}), "main_service": receipt}
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
        try:
            receipt = await self.main_service.submit(handoff)
            self.outbox.delivered(order_id)
            body["main_service"] = receipt
        except HandoffError:
            pass  # The lifespan worker retries the durable handoff, including rejections.
        return Outcome(status, body)

    async def handle_order(self, raw: Any, authorization: str | None = None) -> Outcome:
        order_id = "o_" + secrets.token_hex(6)
        if isinstance(raw, dict) and "request" in raw:
            return await self._dashboard_order(order_id, raw, authorization)
        text = raw.get("request_text") if isinstance(raw, dict) else None
        record: dict = {"user_id": None, "request_text": text if isinstance(text, str) else None,
                        "request": {"text": text if isinstance(text, str) else None},
                        "user": {"id": raw.get("auth", {}).get("user_id")} if isinstance(raw, dict) and isinstance(raw.get("auth"), dict) else {}}

        try:
            body = OrderBody.model_validate(raw)
        except ValidationError as e:
            return await self._done(order_id, 400, "bad_request", _errors(e), record)

        record['request']['search_mode'] = body.search_mode

        # 1. Authenticate the caller's signed auth object.
        try:
            user_id = check_auth(body.auth, self.settings.shared_secret, now=self.clock())
        except AuthError as e:
            return await self._done(order_id, 401, "not_authorized", f"invalid auth: {e}", record)
        user = self.users.get(user_id)
        record["user_id"] = user_id
        if user is None:
            return await self._done(order_id, 401, "not_authorized", "unknown user", record)
        record.update(user_name=user.name, job_number=user.job_number, cost_code=user.cost_code,
                      identity_verified=True, user=user.model_dump(), organization=self.policy.policy.model_dump())

        company = {"id": self.policy.policy.id, "name": self.policy.policy.name}
        return await self._run_order(order_id, user, body.request_text, record, company, company_caps=True)

    async def _dashboard_order(self, order_id: str, raw: dict, authorization: str | None) -> Outcome:
        if not self.settings.allow_legacy_config:
            return await self._done(order_id, 401, "not_authorized", "account authentication required", {})
        req = raw.get("request")
        text = req.get("text") if isinstance(req, dict) else None
        rid = req.get("id") if isinstance(req, dict) else None
        record: dict = {"source": "dashboard", "user_id": None,
                        "request_id": rid[:200] if isinstance(rid, str) else None,
                        "request_text": text if isinstance(text, str) else None,
                        "request": req if isinstance(req, dict) else {"text": None},
                        "organization": raw.get("companyConfig", {}), "user": raw.get("userConfig", {})}

        try:
            body = DashboardOrder.model_validate(raw)
        except ValidationError as e:
            return await self._done(order_id, 400, "bad_request", _errors(e), record)

        # 1. Authenticate: the dashboard relay sends "Authorization: Bearer <PROXY_API_TOKEN>".
        token = self.settings.api_token
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not token:
            return await self._done(order_id, 401, "not_authorized", "PROXY_API_TOKEN is not set on the proxy", record)
        if not hmac.compare_digest(given.encode(), token.encode()):
            return await self._done(order_id, 401, "not_authorized", "missing or wrong bearer token", record)

        record["identity_verified"] = True
        u, c = body.userConfig, body.companyConfig
        record.update(user_id=u.employeeId, user_name=u.name, company_id=c.companyId, cost_code=u.costCenter)
        if u.companyId != c.companyId:
            return await self._done(order_id, 400, "bad_request",
                              f"userConfig.companyId {u.companyId} does not match companyConfig.companyId", record)
        if u.currency != "USD" or c.currency != "USD":
            return await self._done(order_id, 400, "bad_request", "only USD is supported", record)

        # 2. Retries: the dashboard keeps request.id on a retry. Same request -> the first answer again.
        fingerprint = hashlib.sha256(canonical_json(
            {"userConfig": raw["userConfig"], "companyConfig": raw["companyConfig"], "text": body.request.text,
             "search_mode": body.request.search_mode})).hexdigest()
        prior = self.requests.get(body.request.id)
        if prior is not None:
            if prior["fingerprint"] != fingerprint:
                return await self._done(order_id, 409, "conflict",
                                  "request.id was already used for a different employee, company or text", record)
            self.audit.append({"at": _iso(self.clock()), "order_id": prior["body"]["order_id"],
                               "kind": "attempt", "decision": "duplicate_request", "reason": None, **record})
            return Outcome(prior["status"], {**prior["body"], "duplicate": True})
        if body.request.id in self.in_flight:
            return await self._done(order_id, 409, "conflict", "this request.id is still being processed", record)
        record["request_fingerprint"] = fingerprint

        # The dashboard profile sets the limit: approvalLimit, lowered to approvalRequiredAbove when set
        # (the proxy has no approval step). The company's daily/job caps in data/ don't apply.
        limit = u.approvalLimit
        if c.purchasePolicy.approvalRequiredAbove is not None:
            limit = min(limit, c.purchasePolicy.approvalRequiredAbove)
        user = User(id=u.employeeId, name=u.name, email=u.email, role=u.role, cost_code=u.costCenter,
                    spend_limit_cents=limit, purchasing_enabled=u.purchasingEnabled, ship_to=c.billingAddress)
        extra_limits = {"preferred_vendors": c.purchasePolicy.preferredVendors[:20]}
        policy_updates = {}
        if c.purchasePolicy.blockedCategories is not None:
            policy_updates["blocked_categories"] = c.purchasePolicy.blockedCategories
        if c.purchasePolicy.blockedKeywords is not None:
            policy_updates["blocked_keywords"] = c.purchasePolicy.blockedKeywords
        policy = self.policy.policy.model_copy(update=policy_updates)
        self.in_flight.add(body.request.id)
        try:
            return await self._run_order(order_id, user, body.request.text, record,
                                         {"id": c.companyId, "name": c.name}, company_caps=False,
                                         extra_limits=extra_limits, policy=policy)
        finally:
            self.in_flight.discard(body.request.id)

    async def _run_order(self, order_id: str, user: User, request_text: str, record: dict, company: dict,
                         company_caps: bool, extra_limits: dict | None = None, policy=None, spend=None) -> Outcome:
        if not request_text.strip():
            return await self._done(order_id, 400, "bad_request", "request text cannot be blank", record)
        # 2. Authorize: user-level checks.
        spent_today, spent_on_job = spend if spend is not None else (self.policy.spend(user.job_number) if company_caps else (0, 0))
        policy = policy or self.policy.policy
        reasons = authorize(user, policy, spent_today, spent_on_job, company_caps)
        if reasons:
            return await self._done(order_id, 403, "not_authorized", "; ".join(reasons), record)

        violations = check_request_policy(request_text, policy)
        if violations:
            return await self._done(order_id, 403, "violates_company_policy", "; ".join(violations), record)
        limits = compile_limits(user, policy, spent_today, spent_on_job, company_caps)
        limits.update(extra_limits or {})
        record.update(company=company,
                      requester={"user_id": user.id, "name": user.name, "job_number": user.job_number,
                                 "cost_code": user.cost_code, "ship_to": user.ship_to},
                      limits=limits, max_total_cents=limits["max_total_cents"])
        return await self._done(order_id, 200, "accepted", None, record, {"limits": limits})

    async def flush_outbox(self):
        for payload in self.outbox.pending():
            try:
                await self.main_service.submit(payload)
            except HandoffError:
                continue
            self.outbox.delivered(payload["order_id"])

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
        if order.get('account_company'):
            recorded = self.accounts.record_purchase(order_id, order['account_company'], order['job_number'], total)
            if recorded != total:
                return self._purchase_done(order_id, 409, 'conflict',
                                           f'purchase already recorded with total_cents={recorded}',
                                           {**record, 'flagged': True})
        elif order["company_caps"]:
            self.policy.record_purchase(order["job_number"], total)
        self.purchased[order_id] = total
        if order["company_caps"] and not order.get('account_company'):
            spent_today, spent_on_job = self.policy.spend(order["job_number"])
            record.update(spent_today_cents=spent_today, spent_on_job_cents=spent_on_job)
        return self._purchase_done(order_id, 200, "recorded", None, record)

    async def account_order(self, account_id: str, raw: Any) -> Outcome:
        """Resolve current policy and identity from our account directory on every request."""
        order_id = 'o_' + secrets.token_hex(12)
        account = self.accounts.profile(account_id)
        record = {'source': 'account', 'account_id': account_id, 'identity_verified': bool(account)}
        if account is None:
            return await self._done(order_id, 401, 'not_authorized', 'account is unavailable', record)
        user, policy = account
        record.update(account_company=policy.id, user_id=user.id, user=user.model_dump(),
                      organization=policy.model_dump(), job_number=user.job_number)
        try:
            body = AccountOrder.model_validate(raw)
        except ValidationError:
            return await self._done(order_id, 400, 'bad_request',
                                    'expected request_id, request_text and optional search_mode; config fields are forbidden', record)
        record.update(request_text=body.request_text,
                      request={'id': body.request_id, 'text': body.request_text, 'search_mode': body.search_mode})
        # Account namespaces prevent one employee from colliding with another employee's request IDs.
        rid = 'account:' + hashlib.sha256(canonical_json([account_id, body.request_id])).hexdigest()
        fingerprint = hashlib.sha256(canonical_json(body.model_dump())).hexdigest()
        record.update(request_id=rid, request_fingerprint=fingerprint)
        prior = self.requests.get(rid)
        if prior:
            if prior['fingerprint'] != fingerprint:
                return await self._done(order_id, 409, 'conflict', 'request_id already used with different content', record)
            return Outcome(prior['status'], {**prior['body'], 'duplicate': True})
        if rid in self.in_flight:
            return Outcome(409, {'error': 'request is still being processed'})
        self.in_flight.add(rid)
        try:
            return await self._run_order(order_id, user, body.request_text, record,
                                        {'id': policy.id, 'name': policy.name}, company_caps=True,
                                        policy=policy, spend=self.accounts.spend(policy, user.job_number))
        finally:
            self.in_flight.discard(rid)
