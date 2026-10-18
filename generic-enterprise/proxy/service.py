"""Order pipeline: authenticate -> authorize -> propose spec -> policy check -> search payload -> engine.

The proxy never holds payment credentials and never lets request text change limits or policy.
Every call to handle_order writes exactly one audit entry.
"""

from __future__ import annotations

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
from .models import OrderBody
from .signing import AuthError, check_auth, sign_payload
from .spec import DEFAULT_WEIGHTS, FallbackSpecParser, ParseError, make_parser
from .store import PolicyStore, load_users

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    shared_secret: str = ""
    engine_url: str | None = None
    engine_path: str = "/search"
    data_dir: Path = ROOT / "data"
    var_dir: Path = ROOT / "var"

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls(shared_secret=os.environ.get("PROXY_SHARED_SECRET", ""),
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

    def _done(self, order_id: str, status: int, decision: str, reason: str | None, record: dict,
              extra: dict | None = None) -> Outcome:
        ok = decision == "accepted"
        self.audit.append({"at": _iso(self.clock()), "order_id": order_id,
                           "kind": "order" if ok else "attempt", "decision": decision, "reason": reason,
                           **record})
        body = {"ok": ok, "order_id": order_id, "decision": decision}
        if reason:
            body["reason"] = reason
        return Outcome(status, {**body, **(extra or {})})

    async def handle_order(self, raw: Any) -> Outcome:
        order_id = "o_" + secrets.token_hex(6)
        text = raw.get("request_text") if isinstance(raw, dict) else None
        record: dict = {"user_id": None, "request_text": text if isinstance(text, str) else None}

        try:
            body = OrderBody.model_validate(raw)
        except ValidationError as e:
            return self._done(order_id, 400, "bad_request",
                              "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()), record)

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

        # 2. Authorize: user-level checks from company data only.
        spent_today, spent_on_job = self.policy.spend(user.job_number)
        reasons = authorize(user, self.policy.policy, spent_today, spent_on_job)
        if reasons:
            return self._done(order_id, 403, "not_authorized", "; ".join(reasons), record)

        # 3. Propose a spec (Claude, or rules). Probabilistic: checked below.
        note = None
        try:
            if isinstance(self.parser, FallbackSpecParser):
                proposal, source, note = await self.parser.parse_with_source(body.request_text)
            else:
                proposal, source = await self.parser.parse(body.request_text), self.parser.name
        except ParseError as e:
            return self._done(order_id, 503, "parser_error", str(e), record)
        record["parser"] = source
        record["proposal"] = proposal.model_dump()

        # 4. Company policy, checked deterministically on the proposal AND the raw text.
        violations = check_policy(proposal, body.request_text, self.policy.policy)
        if violations:
            return self._done(order_id, 403, "violates_company_policy", "; ".join(violations), record)
        if not proposal.understood or not proposal.item.strip():
            return self._done(order_id, 422, "unclear_request",
                              proposal.unclear_reason or "could not tell what to buy", record)

        # 5. Specs + weights + spending limits for the engine, signed so it can't be altered in transit.
        search = build_search(proposal, user, self.policy.policy, spent_today, spent_on_job, DEFAULT_WEIGHTS)
        if search.errors:
            return self._done(order_id, 422, "unclear_request", "; ".join(search.errors), record)
        notes = search.notes + ([note] if note else [])
        payload = sign_payload({
            "order_id": order_id,
            "issued_at": _iso(self.clock()),
            "requester": {"user_id": user.id, "name": user.name, "job_number": user.job_number,
                          "cost_code": user.cost_code, "ship_to": user.ship_to},
            "request_text": body.request_text,
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
