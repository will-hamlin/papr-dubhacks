"""Internal HTTP ingress. Run one MS worker on the same server as the proxy."""
import asyncio
import hmac
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Any, Literal

from .service import MainService, Settings
from .signing import verify_payload
from .store import ConflictError, MissingRequestError


class Authorization(BaseModel):
    accepted: bool = Field(strict=True)
    decision: str
    reason: str | None
    http_status: int
    identity_verified: bool = Field(strict=True)


class Handoff(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1]
    order_id: str = Field(min_length=1, max_length=100)
    issued_at: str
    authorization: Authorization
    request: dict
    organization: Any
    user: Any
    company: dict
    requester: dict
    limits: dict
    proxy_sig: str


def create_app(settings: Settings | None = None, parser=None, engine=None, verifier=None):
    service = MainService(settings or Settings.from_env(), parser, engine, verifier)

    async def worker():
        while True:
            try:
                worked = await service.process_next()
            except Exception:
                logging.exception('MS worker failed; will retry')
                worked = False
            await asyncio.sleep(0 if worked else 1)

    async def poller():
        while True:
            try:
                await service.refresh_results()
            except Exception:
                logging.exception('MS polling failed; will retry')
            await asyncio.sleep(1)

    @asynccontextmanager
    async def lifespan(app):
        service.store.recover()
        tasks = [asyncio.create_task(worker()), asyncio.create_task(poller())]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            await service.aclose()

    app = FastAPI(title='Purchasing main service', lifespan=lifespan)
    app.state.service = service

    @app.get('/health')
    def health():
        return {'ok': True, 'parser': service.parser.name, 'engine': service.engine.name}

    @app.post('/handoffs')
    async def receive(request: Request):
        try:
            raw = await request.json()
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({'error': 'invalid JSON'}, status_code=400)
        if not verify_payload(raw, service.settings.shared_secret):
            return JSONResponse({'error': 'invalid handoff signature'}, status_code=401)
        try:
            body = Handoff.model_validate(raw)
            if body.authorization.accepted:
                if body.request.get('search_mode', 'managed') not in ('managed', 'agent'):
                    raise ValueError('search_mode must be managed or agent')
                if body.authorization.decision != 'accepted' or not body.authorization.identity_verified:
                    raise ValueError('accepted handoff must have an authenticated authorization decision')
                if not isinstance(body.request.get('text'), str) or not body.request['text'].strip():
                    raise ValueError('accepted handoff needs request text')
                if type(body.limits.get('max_total_cents')) is not int or body.limits['max_total_cents'] < 0:
                    raise ValueError('accepted handoff needs an authorized spending limit')
            return service.receive(raw)
        except (ValidationError, ValueError) as exc:
            return JSONResponse({'error': str(exc)}, status_code=400)
        except ConflictError as exc:
            return JSONResponse({'error': str(exc)}, status_code=409)

    @app.get('/requests/{order_id}')
    def result(order_id: str, request: Request):
        token = request.headers.get('authorization', '').removeprefix('Bearer ')
        if not hmac.compare_digest(token.encode(), service.settings.shared_secret.encode()):
            return JSONResponse({'error': 'not authorized'}, status_code=401)
        record = service.store.get(order_id)
        if record is None:
            return JSONResponse({'error': 'unknown order'}, status_code=404)
        return record

    @app.post('/requests/{order_id}/candidates')
    async def submit_candidates(order_id: str, request: Request):
        try:
            raw = await request.json()
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({'error': 'invalid JSON'}, status_code=400)
        if not verify_payload(raw, service.settings.shared_secret):
            return JSONResponse({'error': 'invalid proxy signature'}, status_code=401)
        if set(raw) != {'order_id', 'submission', 'proxy_sig'} or raw['order_id'] != order_id:
            return JSONResponse({'error': 'invalid candidate envelope'}, status_code=400)
        try:
            return JSONResponse(service.submit_candidates(order_id, raw['submission']), status_code=202)
        except ValidationError as exc:
            return JSONResponse({'error': str(exc)}, status_code=400)
        except MissingRequestError as exc:
            return JSONResponse({'error': str(exc)}, status_code=404)
        except ConflictError as exc:
            return JSONResponse({'error': str(exc)}, status_code=409)

    return app
