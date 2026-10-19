"""Durable delivery of authorization decisions to the co-located main service."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager, closing
from pathlib import Path

import httpx
from urllib.parse import quote


class HandoffError(Exception):
    pass


class MainServiceClient:
    def __init__(self, base_url: str, transport=None):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=10, transport=transport)

    async def submit(self, payload: dict) -> dict:
        try:
            response = await self.client.post('/handoffs', json=payload)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or result.get('order_id') != payload['order_id']:
                raise ValueError('invalid main-service receipt')
            return result
        except (httpx.HTTPError, ValueError) as exc:
            raise HandoffError(str(exc)) from exc

    async def aclose(self):
        await self.client.aclose()

    async def request_status(self, order_id, secret):
        try:
            response = await self.client.get('/requests/' + quote(order_id, safe=''),
                                             headers={'Authorization': 'Bearer ' + secret})
            body = response.json()
            if response.status_code == 200:
                # Internal handoff/signatures and full organization profiles stay on the server.
                body = {key: body[key] for key in ('order_id', 'status', 'result')}
            return response.status_code, body
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise HandoffError(str(exc)) from exc

    async def candidates(self, order_id, payload):
        try:
            response = await self.client.post('/requests/' + quote(order_id, safe='') + '/candidates', json=payload)
            return response.status_code, response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HandoffError(str(exc)) from exc


class Outbox:
    def __init__(self, path: Path):
        self.path = path
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS handoffs (order_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            yield db

    def add(self, payload: dict):
        with self.connect() as db:
            db.execute('INSERT INTO handoffs VALUES (?, ?)', (payload['order_id'], json.dumps(payload)))

    def pending(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT payload FROM handoffs ORDER BY rowid')]

    def delivered(self, order_id: str):
        with self.connect() as db:
            db.execute('DELETE FROM handoffs WHERE order_id = ?', (order_id,))
