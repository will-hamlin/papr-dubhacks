"""FastAPI wiring for the Acme Corp Purchasing proxy. Run with: uvicorn --factory proxy.app:create_app"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .service import Proxy, Settings
from .handoff import HandoffError
from .signing import check_request_token, make_request_token, sign_payload
from .oauth import OAuth
from .agent_connection import AgentConnection


def create_app(settings: Settings | None = None, main_service=None,
               clock: Callable[[], datetime] | None = None) -> FastAPI:
    proxy = Proxy(settings or Settings.from_env(), main_service, clock)
    oauth = OAuth(proxy)
    agent = AgentConnection(proxy, oauth)
    mcp = agent.mcp()
    mcp_app = mcp.streamable_http_app()

    async def deliver():
        while True:
            try:
                await proxy.flush_outbox()
            except Exception:
                logging.exception('MS delivery failed; will retry')
            await asyncio.sleep(5)

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(deliver())
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await proxy.main_service.aclose()

    app = FastAPI(title="Acme Corp Purchasing proxy (DEMO COMPANY)", lifespan=lifespan)
    app.state.proxy = proxy
    app.state.oauth = oauth
    app.state.agent = agent
    oauth.register_routes(app)

    @app.get("/health")
    def health():
        return {"ok": True, "company": proxy.policy.policy.name,
                "main_service": proxy.settings.main_service_url, "pending_handoffs": len(proxy.outbox.pending())}

    @app.post("/orders")
    async def orders(request: Request):
        try:
            raw = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raw = None
        authorization = request.headers.get('authorization')
        account_id = await oauth.account(authorization)
        if account_id:
            out = await proxy.account_order(account_id, raw)
            return JSONResponse(out.body, status_code=out.status)
        # Account requests must never fall back to the demo's caller-supplied identity/configuration.
        if isinstance(raw, dict) and 'request_id' in raw:
            return oauth.unauthorized()
        out = await proxy.handle_order(raw, authorization)
        if out.body.get('ok'):
            out.body = {**out.body, 'request_token': make_request_token(
                out.body['order_id'], proxy.settings.shared_secret, proxy.clock())}
        return JSONResponse(out.body, status_code=out.status)

    def request_access(request, order_id):
        if order_id in proxy.owners:
            return False
        authorization = request.headers.get('authorization', '')
        return authorization.startswith('Bearer ') and check_request_token(
            authorization[7:], order_id, proxy.settings.shared_secret, proxy.clock())

    @app.get('/orders/{order_id}')
    async def order_status(order_id: str, request: Request):
        account_id = await oauth.account(request.headers.get('authorization'))
        if account_id:
            status, body = await agent.status(account_id, order_id)
            return JSONResponse(body, status_code=status)
        if not request_access(request, order_id):
            return oauth.unauthorized()
        try:
            status, body = await proxy.main_service.request_status(order_id, proxy.settings.shared_secret)
            return JSONResponse(body, status_code=status)
        except HandoffError:
            return JSONResponse({'error': 'main service unavailable; retry later'}, status_code=503)

    @app.post('/orders/{order_id}/candidates')
    async def candidates(order_id: str, request: Request):
        account_id = await oauth.account(request.headers.get('authorization'))
        if not account_id and not request_access(request, order_id):
            return oauth.unauthorized()
        try:
            raw = await request.json()
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({'error': 'invalid JSON'}, status_code=400)
        if account_id:
            status, body = await agent.candidates(account_id, order_id, raw)
            return JSONResponse(body, status_code=status)
        payload = sign_payload({'order_id': order_id, 'submission': raw}, proxy.settings.shared_secret)
        try:
            status, body = await proxy.main_service.candidates(order_id, payload)
            return JSONResponse(body, status_code=status)
        except HandoffError:
            return JSONResponse({'error': 'delivery uncertain; retry with the same submission_id'}, status_code=503)

    @app.post("/purchases")
    async def purchases(request: Request):
        try:
            raw = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raw = None
        out = proxy.handle_purchase(raw)
        return JSONResponse(out.body, status_code=out.status)

    @app.get("/audit")
    def audit(request: Request):
        import hmac
        expected = proxy.settings.api_token
        given = request.headers.get('authorization', '').removeprefix('Bearer ')
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            return JSONResponse({'error': 'operator token required'}, status_code=401)
        ok, bad = proxy.audit.verify()
        return {"chain_valid": ok, "first_bad_seq": bad, "entries": list(reversed(proxy.audit.entries()))}

    # Mount last so the SDK owns /mcp and its RFC 9728 metadata without shadowing API routes.
    app.mount('/', mcp_app)
    return app
