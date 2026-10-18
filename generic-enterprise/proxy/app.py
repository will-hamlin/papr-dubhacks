"""FastAPI wiring for the Acme Corp Purchasing proxy. Run with: uvicorn --factory proxy.app:create_app"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable

from fastapi import Cookie, FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from .agents import Agent, HttpAgent
from .models import AgentEvent, ApproveCartBody, LoginBody, RejectBody, RequestBody
from .service import Proxy, ProxyError, Settings

STATIC = Path(__file__).parent / "static"
COOKIE = "acme_sid"


def create_app(settings: Settings | None = None, agent: Agent | None = None,
               clock: Callable[[], datetime] | None = None) -> FastAPI:
    proxy = Proxy(settings or Settings.from_env(), agent, clock)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        if isinstance(proxy.agent, HttpAgent):
            await proxy.agent.aclose()

    app = FastAPI(title="Acme Corp Purchasing proxy (DEMO)", lifespan=lifespan)
    app.state.proxy = proxy

    @app.exception_handler(ProxyError)
    async def _proxy_error(_req: Request, exc: ProxyError):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/config")
    def config():
        return {"agent_mode": proxy.mode, "company": proxy.policy.policy.name, "demo": True}

    @app.get("/users")
    def users():
        return [{"id": u.id, "name": u.name, "role": u.role} for u in proxy.users.values()]

    @app.post("/login")
    def login(body: LoginBody, response: Response):
        lg = proxy.login(body.user_id)
        response.set_cookie(COOKIE, lg.token, httponly=True, samesite="lax",
                            max_age=int(proxy.settings.session_ttl.total_seconds()))
        return {"session_id": lg.session_id, "user_id": lg.user_id, "expires_at": lg.expires_at.isoformat()}

    @app.post("/logout")
    def logout(response: Response, acme_sid: str | None = Cookie(None)):
        proxy.logout(acme_sid)
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/me")
    def me(acme_sid: str | None = Cookie(None)):
        lg, user = proxy.current(acme_sid)
        return {"user": user.model_dump(), "session_id": lg.session_id,
                "expires_at": lg.expires_at.isoformat(), "limits": proxy.limits(user),
                "is_approver": bool(user.approves_for)}

    @app.post("/request")
    async def request(body: RequestBody, acme_sid: str | None = Cookie(None)):
        run = await proxy.submit(acme_sid, body.request_text)
        return proxy.run_view(run, proxy.users[run.user_id])

    @app.get("/runs")
    def runs(acme_sid: str | None = Cookie(None)):
        _, user = proxy.current(acme_sid, allow_expired=True)
        return proxy.my_runs(user)

    @app.get("/runs/{run_id}")
    def run(run_id: str, acme_sid: str | None = Cookie(None)):
        r, viewer = proxy.get_run(acme_sid, run_id)
        return proxy.run_view(r, viewer)

    @app.post("/runs/{run_id}/approve-spec")
    async def approve_spec(run_id: str, acme_sid: str | None = Cookie(None)):
        r = await proxy.approve_spec(acme_sid, run_id)
        return proxy.run_view(r, proxy.users[r.user_id])

    @app.post("/runs/{run_id}/approve-cart")
    async def approve_cart(run_id: str, body: ApproveCartBody, acme_sid: str | None = Cookie(None)):
        r = await proxy.approve_cart(acme_sid, run_id, body.cart_hash)
        return proxy.run_view(r, proxy.users[r.user_id])

    @app.post("/runs/{run_id}/manager-approve")
    async def manager_approve(run_id: str, acme_sid: str | None = Cookie(None)):
        r = await proxy.manager_approve(acme_sid, run_id)
        return proxy.run_view(r, proxy.current(acme_sid)[1])

    @app.post("/runs/{run_id}/manager-reject")
    def manager_reject(run_id: str, body: RejectBody, acme_sid: str | None = Cookie(None)):
        r = proxy.manager_reject(acme_sid, run_id, body.reason)
        return proxy.run_view(r, proxy.current(acme_sid)[1])

    @app.post("/runs/{run_id}/cancel")
    def cancel(run_id: str, acme_sid: str | None = Cookie(None)):
        r = proxy.cancel(acme_sid, run_id)
        return proxy.run_view(r, proxy.users[r.user_id])

    @app.get("/manager/queue")
    def manager_queue(acme_sid: str | None = Cookie(None)):
        _, user = proxy.current(acme_sid)
        return proxy.manager_queue(user)

    @app.post("/proxy/events")
    def events(ev: AgentEvent, token: str | None = None):
        r = proxy.handle_event(token, ev)
        return {"ok": True, "run_id": ev.run_id, "status": r.status}

    @app.get("/outbox")
    def outbox(acme_sid: str | None = Cookie(None)):
        proxy.current(acme_sid, allow_expired=True)
        return list(reversed(proxy.outbox.messages))

    @app.get("/audit")
    def audit(acme_sid: str | None = Cookie(None)):
        proxy.current(acme_sid, allow_expired=True)
        ok, bad = proxy.audit.verify()
        return {"chain_valid": ok, "first_bad_seq": bad, "entries": list(reversed(proxy.audit.entries()))}

    return app
