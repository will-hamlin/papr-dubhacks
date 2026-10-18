"""FastAPI wiring for the Acme Corp Purchasing proxy. Run with: uvicorn --factory proxy.app:create_app"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .engine import Engine, HttpEngine
from .service import Proxy, Settings


def create_app(settings: Settings | None = None, parser=None, engine: Engine | None = None,
               clock: Callable[[], datetime] | None = None) -> FastAPI:
    proxy = Proxy(settings or Settings.from_env(), parser, engine, clock)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        if isinstance(proxy.engine, HttpEngine):
            await proxy.engine.aclose()

    app = FastAPI(title="Acme Corp Purchasing proxy (DEMO COMPANY)", lifespan=lifespan)
    app.state.proxy = proxy

    @app.get("/health")
    def health():
        return {"ok": True, "company": proxy.policy.policy.name, "parser": proxy.parser.name,
                "engine": proxy.engine.name}

    @app.post("/orders")
    async def orders(request: Request):
        try:
            raw = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raw = None
        out = await proxy.handle_order(raw, request.headers.get("authorization"))
        return JSONResponse(out.body, status_code=out.status)

    @app.post("/purchases")
    async def purchases(request: Request):
        try:
            raw = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raw = None
        out = proxy.handle_purchase(raw)
        return JSONResponse(out.body, status_code=out.status)

    @app.get("/audit")
    def audit():
        ok, bad = proxy.audit.verify()
        return {"chain_valid": ok, "first_bad_seq": bad, "entries": list(reversed(proxy.audit.entries()))}

    return app
