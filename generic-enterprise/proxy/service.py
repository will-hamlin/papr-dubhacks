"""Proxy core: logins, signed sessions, gates, run state machine, Outbox and audit.

The proxy never holds payment credentials, never edits a spec, never picks a product, and
never reads limits from request text. Limits come only from data/*.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import ValidationError

from .agents import Agent, AgentError, FakeAgent, HttpAgent
from .audit import AuditLog
from .gates import GateResult, evaluate_cart, money, preflight
from .models import AgentEvent, Cart, User
from .outbox import Outbox
from .session_sig import cart_hash as compute_cart_hash
from .session_sig import sign_session
from .store import PolicyStore, load_users

log = logging.getLogger("proxy")
ROOT = Path(__file__).resolve().parent.parent

TERMINAL = {"purchased", "flagged", "error", "cancelled"}


class ProxyError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class Settings:
    agent_url: str | None = None
    shared_secret: str = ""
    public_url: str = "http://localhost:8000"
    data_dir: Path = ROOT / "data"
    var_dir: Path = ROOT / "var"
    fake_delay_s: float = 1.2
    session_ttl: timedelta = timedelta(minutes=30)
    agent_audit_url: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls(agent_url=os.environ.get("AGENT_URL") or None,
                shared_secret=os.environ.get("PROXY_SHARED_SECRET", ""),
                public_url=os.environ.get("PROXY_PUBLIC_URL", "http://localhost:8000").rstrip("/"),
                agent_audit_url=os.environ.get("AGENT_AUDIT_URL") or None)
        if os.environ.get("FAKE_AGENT_DELAY_S"):
            s.fake_delay_s = float(os.environ["FAKE_AGENT_DELAY_S"])
        if os.environ.get("PROXY_VAR_DIR"):
            s.var_dir = Path(os.environ["PROXY_VAR_DIR"])
        return s


@dataclass
class Login:
    token: str
    session_id: str
    user_id: str
    issued_at: datetime
    expires_at: datetime


@dataclass
class Run:
    id: str
    user_id: str
    session_id: str | None
    request_text: str
    created_at: str
    callback_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    status: str = "submitted"
    agent_run_id: str | None = None
    session: dict | None = None
    session_sig: str | None = None
    spec: dict | None = None
    cart: dict | None = None
    cart_hash: str | None = None
    agent_total_cents: int | None = None
    agent_needs_manager: str | None = None
    gate: dict | None = None
    approved_cart_hash: str | None = None
    approved_total_cents: int | None = None
    spec_approved_by: str | None = None
    cart_approved_by: str | None = None
    manager_approved_by: str | None = None
    order_id: str | None = None
    reason: str | None = None
    audited: bool = False
    timeline: list[dict] = field(default_factory=list)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class Proxy:
    def __init__(self, settings: Settings, agent: Agent | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if settings.agent_url and not settings.shared_secret:
            raise RuntimeError("AGENT_URL is set but PROXY_SHARED_SECRET is not; refusing to start")
        if not settings.shared_secret:
            # Fake agent only: an ephemeral key nobody else knows.
            settings.shared_secret = secrets.token_hex(32)
        settings.var_dir.mkdir(parents=True, exist_ok=True)
        self.users: dict[str, User] = load_users(settings.data_dir)
        self.policy = PolicyStore(settings.data_dir, settings.var_dir, self.clock)
        self.audit = AuditLog(settings.var_dir / "audit.jsonl", on_append=self._forward_audit)
        self.outbox = Outbox(settings.var_dir / "outbox.jsonl", self.clock)
        self.logins: dict[str, Login] = {}
        self.runs: dict[str, Run] = {}
        self._by_token: dict[str, Run] = {}
        self._bg: set = set()
        if agent is not None:
            self.agent = agent
        elif settings.agent_url:
            self.agent = HttpAgent(settings.agent_url)
        else:
            self.agent = FakeAgent(settings.shared_secret, self._deliver_in_process, self.clock,
                                   settings.fake_delay_s)

    @property
    def mode(self) -> str:
        return "fake" if isinstance(self.agent, FakeAgent) else "real"

    # ------------------------------------------------------------ helpers

    def _forward_audit(self, entry: dict) -> None:
        url = self.settings.agent_audit_url
        if not url:
            return

        async def post():
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    await c.post(url, json=entry)
            except httpx.HTTPError as e:
                log.warning("audit forward failed: %s", e)
        try:
            task = asyncio.get_running_loop().create_task(post())
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)
        except RuntimeError:
            pass

    def _note(self, run: Run, status: str, note: str) -> None:
        run.status = status
        run.timeline.append({"at": _iso(self.clock()), "status": status, "note": note})

    def _send(self, to_users: list[User | str | None], type_: str, run: Run | None, subject: str, body: str):
        to = []
        for u in to_users:
            if isinstance(u, User):
                to.append(u.email)
            elif isinstance(u, str):
                to.append(u)
        self.outbox.send(list(dict.fromkeys(to)), type_, run.id if run else None, subject, body)

    def _compliance(self) -> str:
        return self.policy.policy.compliance_email

    def _finalize(self, run: Run, status: str, reason: str | None) -> None:
        """Terminal transition. Writes the run's single audit entry."""
        if status != "purchased":
            self.policy.release(run.id)
        run.reason = reason
        self._note(run, status, reason or status)
        if run.audited:
            return
        run.audited = True
        user = self.users.get(run.user_id)
        self.audit.append({
            "at": _iso(self.clock()),
            "kind": "purchase" if status == "purchased" else "attempt",
            "outcome": status,
            "reason": reason,
            "run_id": run.id,
            "agent_run_id": run.agent_run_id,
            "user_id": run.user_id,
            "user_name": user.name if user else None,
            "job_number": user.job_number if user else None,
            "cost_code": user.cost_code if user else None,
            "request_text": run.request_text,
            "total_cents": run.approved_total_cents if status == "purchased" else
            (run.gate or {}).get("effective_total_cents"),
            "cart_hash": run.approved_cart_hash or run.cart_hash,
            "order_id": run.order_id,
            "approved_by": run.manager_approved_by or run.cart_approved_by,
        })

    def _flag(self, run: Run, reason: str) -> None:
        user = self.users.get(run.user_id)
        self._finalize(run, "flagged", reason)
        self._send([user, self._compliance()], "flagged", run, "Purchase request flagged",
                   f"Request \"{run.request_text}\" was flagged and will not proceed.\nReason: {reason}")

    def _fail(self, run: Run, reason: str) -> None:
        user = self.users.get(run.user_id)
        self._finalize(run, "error", reason)
        self._send([user], "error", run, "Purchase request failed",
                   f"Request \"{run.request_text}\" could not be completed.\nReason: {reason}")

    # ------------------------------------------------------------ login

    def login(self, user_id: str) -> Login:
        if user_id not in self.users:
            raise ProxyError(404, "unknown user")
        now = self.clock()
        lg = Login(secrets.token_urlsafe(24), "s_" + secrets.token_hex(4), user_id, now,
                   now + self.settings.session_ttl)
        self.logins[lg.token] = lg
        return lg

    def logout(self, token: str | None) -> None:
        self.logins.pop(token or "", None)

    def current(self, token: str | None, allow_expired: bool = False) -> tuple[Login, User]:
        lg = self.logins.get(token or "")
        if not lg:
            raise ProxyError(401, "not signed in")
        if not allow_expired and self.clock() >= lg.expires_at:
            raise ProxyError(401, "session expired; sign in again")
        return lg, self.users[lg.user_id]

    def limits(self, user: User) -> dict:
        p = self.policy.policy
        today, job = self.policy.spend(user.job_number)
        return {"spend_limit_cents": user.spend_limit_cents,
                "auto_buy_threshold_cents": p.auto_buy_threshold_cents,
                "daily_cap_cents": p.daily_cap_cents, "spent_today_cents": today,
                "daily_remaining_cents": max(0, p.daily_cap_cents - today),
                "per_job_cap_cents": p.per_job_cap_cents, "spent_on_job_cents": job,
                "job_remaining_cents": max(0, p.per_job_cap_cents - job),
                "purchasing_enabled": user.purchasing_enabled}

    def build_session(self, lg: Login, user: User) -> dict:
        """Signed session params. Contract with the agent: do not add or rename fields."""
        p = self.policy.policy
        today, job = self.policy.spend(user.job_number)
        now = self.clock()
        return {
            "session_id": lg.session_id,
            "user": {"id": user.id, "name": user.name, "role": user.role,
                     "job_number": user.job_number, "cost_code": user.cost_code,
                     "spend_limit_cents": user.spend_limit_cents,
                     "approver_id": user.approver_id, "ship_to": user.ship_to},
            "company": {"id": p.id, "approved_suppliers": list(p.approved_suppliers),
                        "blocked_categories": list(p.blocked_categories),
                        "auto_buy_threshold_cents": p.auto_buy_threshold_cents,
                        "daily_cap_cents": p.daily_cap_cents, "per_job_cap_cents": p.per_job_cap_cents,
                        "spent_today_cents": today, "spent_on_job_cents": job,
                        "tax_rate_bp": p.tax_rate_bp},
            "issued_at": _iso(now),
            "expires_at": _iso(now + self.settings.session_ttl),
        }

    # ------------------------------------------------------------ request

    async def submit(self, token: str | None, request_text: str) -> Run:
        lg = self.logins.get(token or "")
        if not lg:
            self.audit.append({"at": _iso(self.clock()), "kind": "attempt", "outcome": "rejected",
                               "reason": "not signed in", "run_id": None, "user_id": None,
                               "request_text": request_text})
            raise ProxyError(401, "not signed in")
        user = self.users.get(lg.user_id)
        run = Run("r_" + secrets.token_hex(4), lg.user_id, lg.session_id, request_text, _iso(self.clock()))
        self.runs[run.id] = run
        self._by_token[run.callback_token] = run
        self._note(run, "submitted", "request received by proxy")

        today, job = self.policy.spend(user.job_number if user else None)
        reasons = preflight(user, lg.expires_at, self.clock(), self.policy.policy, today, job)
        if reasons:
            self._flag(run, "pre-flight: " + "; ".join(reasons))
            return run

        run.session = self.build_session(lg, user)
        run.session_sig = sign_session(run.session, self.settings.shared_secret)
        callback = f"{self.settings.public_url}/proxy/events?token={run.callback_token}"
        self._note(run, "agent_working", "pre-flight passed; signed session sent to agent")
        try:
            agent_run_id = await self.agent.start_run(request_text, run.session, run.session_sig, callback)
        except AgentError as e:
            if run.status not in TERMINAL:
                self._fail(run, f"agent call failed: {e}")
            return run
        if run.agent_run_id is None:
            run.agent_run_id = agent_run_id
        elif run.agent_run_id != agent_run_id:
            self._fail(run, "agent returned a different run_id than its events used")
        return run

    def get_run(self, token: str | None, run_id: str) -> tuple[Run, User]:
        _, viewer = self.current(token, allow_expired=True)
        run = self.runs.get(run_id)
        if not run:
            raise ProxyError(404, "unknown run")
        requester = self.users.get(run.user_id)
        if viewer.id != run.user_id and not (requester and requester.approver_id == viewer.id):
            raise ProxyError(403, "not your run")
        return run, viewer

    def _requester_run(self, token: str | None, run_id: str, status: str) -> tuple[Run, User]:
        _, user = self.current(token)
        run = self.runs.get(run_id)
        if not run:
            raise ProxyError(404, "unknown run")
        if run.user_id != user.id:
            raise ProxyError(403, "only the requester can do this")
        if run.status != status:
            raise ProxyError(409, f"run is {run.status}, expected {status}")
        return run, user

    async def approve_spec(self, token: str | None, run_id: str) -> Run:
        run, user = self._requester_run(token, run_id, "spec_ready")
        run.spec_approved_by = user.id
        self._note(run, "searching", f"spec approved by {user.name}; agent searching")
        try:
            await self.agent.approve_spec(run.agent_run_id, user.id)
        except AgentError as e:
            if run.status not in TERMINAL:
                self._fail(run, f"agent call failed: {e}")
        return run

    def _evaluate(self, run: Run, user: User) -> GateResult:
        cart = Cart.model_validate(run.cart)
        today, job = self.policy.spend(user.job_number)
        return evaluate_cart(cart, user, self.policy.policy, today, job,
                             run.agent_total_cents, run.agent_needs_manager)

    async def _forward_cart(self, run: Run, approver: User, result: GateResult, note: str) -> None:
        requester = self.users[run.user_id]
        self.policy.reserve(run.id, requester.job_number, result.effective_total_cents)
        run.approved_cart_hash = run.cart_hash
        run.approved_total_cents = result.effective_total_cents
        self._note(run, "cart_approved", note)
        try:
            await self.agent.approve_cart(run.agent_run_id, approver.id, run.cart_hash)
        except AgentError as e:
            if run.status not in TERMINAL:
                self._fail(run, f"agent call failed: {e}")

    async def approve_cart(self, token: str | None, run_id: str, client_hash: str) -> Run:
        run, user = self._requester_run(token, run_id, "cart_ready")
        if client_hash != run.cart_hash:
            raise ProxyError(409, "cart changed since you viewed it; reload")
        result = self._evaluate(run, user)
        run.gate = result.as_dict()
        run.cart_approved_by = user.id
        if result.decision == "flagged":
            self._flag(run, "cart gate: " + "; ".join(result.reasons))
        elif result.decision == "needs_manager":
            self._route_to_manager(run, user, result.reasons)
        else:
            await self._forward_cart(run, user, result, f"cart approved by {user.name} "
                                                        f"({money(result.effective_total_cents)}); within policy")
        return run

    def _route_to_manager(self, run: Run, user: User, reasons: list[str]) -> None:
        approver = self.users.get(user.approver_id or "")
        if not approver:
            self._flag(run, "needs manager approval but no approver is configured: " + "; ".join(reasons))
            return
        self._note(run, "needs_manager", "waiting for " + approver.name + ": " + "; ".join(reasons))
        total = (run.gate or {}).get("effective_total_cents")
        self._send([approver], "needs_manager", run, f"Approval needed: {user.name}'s purchase",
                   f"{user.name} (job {user.job_number}) requests \"{run.request_text}\".\n"
                   f"Total: {money(total) if total is not None else 'see cart'} (MOCK)\n"
                   f"Why you're needed: {'; '.join(reasons)}\nApprove or reject in the Manager queue.")

    async def manager_approve(self, token: str | None, run_id: str) -> Run:
        _, mgr = self.current(token)
        run = self.runs.get(run_id)
        if not run:
            raise ProxyError(404, "unknown run")
        requester = self.users[run.user_id]
        if requester.approver_id != mgr.id:
            raise ProxyError(403, f"{mgr.name} is not {requester.name}'s approver")
        if run.status != "needs_manager":
            raise ProxyError(409, f"run is {run.status}, not waiting for a manager")
        if not mgr.purchasing_enabled:
            raise ProxyError(403, "approver has purchasing disabled")
        # Re-run the gate: spend may have moved, and hard rules are never overridable.
        result = self._evaluate(run, requester)
        run.gate = result.as_dict()
        if result.decision == "flagged":
            self._flag(run, "cart gate: " + "; ".join(result.reasons))
            raise ProxyError(409, "cart violates hard policy; it cannot be manager-approved")
        if result.effective_total_cents > mgr.spend_limit_cents:
            raise ProxyError(403, f"total {money(result.effective_total_cents)} exceeds {mgr.name}'s "
                                  f"approval limit {money(mgr.spend_limit_cents)}")
        run.manager_approved_by = mgr.id
        await self._forward_cart(run, mgr, result, f"manager approval by {mgr.name} "
                                                   f"({money(result.effective_total_cents)})")
        return run

    def manager_reject(self, token: str | None, run_id: str, reason: str | None) -> Run:
        _, mgr = self.current(token)
        run = self.runs.get(run_id)
        if not run:
            raise ProxyError(404, "unknown run")
        requester = self.users[run.user_id]
        if requester.approver_id != mgr.id:
            raise ProxyError(403, f"{mgr.name} is not {requester.name}'s approver")
        if run.status != "needs_manager":
            raise ProxyError(409, f"run is {run.status}, not waiting for a manager")
        why = f"rejected by {mgr.name}" + (f": {reason}" if reason else "")
        self._finalize(run, "cancelled", why)
        self._send([requester], "manager_rejected", run, "Purchase rejected by your approver",
                   f"Request \"{run.request_text}\" was {why}.")
        return run

    def cancel(self, token: str | None, run_id: str) -> Run:
        _, user = self.current(token)
        run = self.runs.get(run_id)
        if not run or run.user_id != user.id:
            raise ProxyError(404, "unknown run")
        if run.status not in {"spec_ready", "cart_ready", "needs_manager"}:
            raise ProxyError(409, f"run is {run.status}; it can't be cancelled now")
        self._finalize(run, "cancelled", f"cancelled by {user.name}")
        return run

    # ------------------------------------------------------------ webhook

    async def _deliver_in_process(self, callback_url: str, event: dict) -> None:
        token = parse_qs(urlparse(callback_url).query).get("token", [""])[0]
        try:
            self.handle_event(token, AgentEvent.model_validate(event))
        except ProxyError as e:
            log.warning("fake agent event rejected: %s", e.detail)

    def handle_event(self, token: str | None, ev: AgentEvent) -> Run:
        run = self._by_token.get(token or "")
        if not run:
            raise ProxyError(403, "unknown callback token")
        if run.agent_run_id is None:
            run.agent_run_id = ev.run_id
        elif ev.run_id != run.agent_run_id:
            raise ProxyError(409, "run_id does not match this callback")
        if run.status in TERMINAL:
            raise ProxyError(409, f"run is already {run.status}")
        user = self.users[run.user_id]
        approver = self.users.get(user.approver_id or "")
        handler = getattr(self, f"_on_{ev.type}")
        handler(run, user, approver, ev)
        return run

    def _on_spec_ready(self, run: Run, user: User, approver, ev: AgentEvent) -> None:
        if run.status not in {"submitted", "agent_working"}:
            raise ProxyError(409, f"spec_ready not allowed while {run.status}")
        spec = ev.payload.get("spec")
        if not isinstance(spec, dict) or not spec:
            self._flag(run, "agent sent an empty or malformed spec")
            return
        run.spec = spec
        self._note(run, "spec_ready", "agent proposed a spec; waiting for your approval")
        self._send([user], "spec_ready", run, "Please review your purchase spec",
                   f"The agent turned \"{run.request_text}\" into a spec:\n"
                   f"{json.dumps(spec, indent=2)}\nApprove it in the portal before any search happens.")

    def _on_cart_ready(self, run: Run, user: User, approver, ev: AgentEvent) -> None:
        if run.status not in {"searching", "cart_ready"}:
            self._flag(run, f"agent sent a cart while run was {run.status} (spec not approved)")
            return
        raw = ev.payload.get("cart")
        try:
            cart = Cart.model_validate(raw)
        except ValidationError as e:
            self._flag(run, f"agent sent a malformed cart ({e.error_count()} problems; money must be integer cents)")
            return
        h = compute_cart_hash(raw)
        claimed = ev.payload.get("cart_hash")
        if claimed is not None and claimed != h:
            self._flag(run, "cart_hash from agent does not match the cart contents")
            return
        total = ev.payload.get("total_cents")
        if total is not None and (type(total) is not int or total < 0):
            self._flag(run, "agent total_cents is not a non-negative integer")
            return
        run.cart, run.cart_hash, run.agent_total_cents = raw, h, total
        preview = evaluate_cart(cart, user, self.policy.policy, *self.policy.spend(user.job_number),
                                total, run.agent_needs_manager)
        run.gate = preview.as_dict()
        self._note(run, "cart_ready", f"agent proposed a cart ({money(preview.effective_total_cents)}); "
                                      f"waiting for your approval")
        self._send([user], "cart_ready", run, "Your cart is ready for approval",
                   "\n".join(f"- {l['qty']} x {l['name']} @ {money(l['unit_price_cents'])}"
                             for l in preview.breakdown.lines)
                   + f"\nTotal incl. tax and freight: {money(preview.effective_total_cents)} (MOCK)")

    def _on_needs_manager(self, run: Run, user: User, approver, ev: AgentEvent) -> None:
        reason = ev.reason or ev.payload.get("reason") or "agent policy check"
        run.agent_needs_manager = reason
        if run.status == "cart_approved":
            self.policy.release(run.id)
            run.approved_cart_hash = run.approved_total_cents = None
            self._route_to_manager(run, user, [f"agent requires manager approval: {reason}"])
        elif run.status == "cart_ready":
            self._note(run, "cart_ready", f"agent says this cart needs manager approval: {reason}")
            self._send([user], "needs_manager", run, "Heads up: this cart will need manager approval",
                       f"The agent says: {reason}. After you approve, it goes to "
                       f"{approver.name if approver else 'your approver'}.")
        else:
            raise ProxyError(409, f"needs_manager not allowed while {run.status}")

    def _on_purchased(self, run: Run, user: User, approver, ev: AgentEvent) -> None:
        run.order_id = str(ev.payload.get("order_id") or "")[:64] or None
        claimed_hash = ev.payload.get("cart_hash")
        if run.status != "cart_approved" or (claimed_hash and claimed_hash != run.approved_cart_hash):
            # The agent says it spent money we never approved. Count it (conservative) and raise the alarm.
            if run.cart:
                try:
                    total = self._evaluate(run, user).effective_total_cents
                    self.policy.commit(run.id, user.job_number, total)
                except ValidationError:
                    pass
            reason = f"agent reported a purchase the proxy did not approve (run was {run.status})"
            self._finalize(run, "error", reason)
            self._send([user, approver, self._compliance()], "error", run, "ALERT: unapproved purchase reported",
                       f"Request \"{run.request_text}\": {reason}. Order {run.order_id}.")
            return
        claimed_total = ev.payload.get("total_cents")
        total = max(run.approved_total_cents or 0, claimed_total if type(claimed_total) is int else 0)
        run.approved_total_cents = total
        self.policy.commit(run.id, user.job_number, total)
        self._finalize(run, "purchased", f"order {run.order_id} placed ({money(total)})")
        to = [user] + ([approver] if run.manager_approved_by else [])
        self._send(to, "purchased", run, "Purchase confirmed (MOCK payment)",
                   f"Order {run.order_id} for \"{run.request_text}\" was placed.\n"
                   f"Total: {money(total)} charged to job {user.job_number}, cost code {user.cost_code}.\n"
                   f"Payment was handled by the payment gate (MOCK).")

    def _on_flagged(self, run: Run, user: User, approver, ev: AgentEvent) -> None:
        self._flag(run, "agent: " + (ev.reason or ev.payload.get("reason") or "no reason given"))

    def _on_error(self, run: Run, user: User, approver, ev: AgentEvent) -> None:
        self._fail(run, "agent: " + (ev.reason or ev.payload.get("reason") or "unknown error"))

    # ------------------------------------------------------------ views

    def run_view(self, run: Run, viewer: User) -> dict:
        requester = self.users[run.user_id]
        is_req = viewer.id == run.user_id
        is_mgr = requester.approver_id == viewer.id
        return {
            "id": run.id, "agent_run_id": run.agent_run_id, "status": run.status,
            "requester": {"id": requester.id, "name": requester.name, "job_number": requester.job_number},
            "request_text": run.request_text, "created_at": run.created_at, "reason": run.reason,
            "spec": run.spec, "cart": run.cart, "cart_hash": run.cart_hash, "gate": run.gate,
            "approved_total_cents": run.approved_total_cents, "order_id": run.order_id,
            "spec_approved_by": run.spec_approved_by, "cart_approved_by": run.cart_approved_by,
            "manager_approved_by": run.manager_approved_by,
            "session": run.session, "session_sig": run.session_sig,
            "timeline": run.timeline, "messages": self.outbox.for_run(run.id),
            "can": {"approve_spec": is_req and run.status == "spec_ready",
                    "approve_cart": is_req and run.status == "cart_ready",
                    "cancel": is_req and run.status in {"spec_ready", "cart_ready", "needs_manager"},
                    "manager": is_mgr and run.status == "needs_manager"},
        }

    def my_runs(self, user: User) -> list[dict]:
        return [self.run_view(r, user) for r in reversed(self.runs.values()) if r.user_id == user.id]

    def manager_queue(self, mgr: User) -> list[dict]:
        return [self.run_view(r, mgr) for r in self.runs.values()
                if r.status == "needs_manager" and self.users[r.user_id].approver_id == mgr.id]
