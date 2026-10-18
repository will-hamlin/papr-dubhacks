"""Client for the pbapo engine. HttpEngine posts to ENGINE_URL; StubEngine stands in when it's unset."""

from __future__ import annotations

from typing import Any, Protocol

import httpx


class EngineError(Exception):
    pass


class Engine(Protocol):
    name: str

    async def search(self, payload: dict) -> Any: ...


class HttpEngine:
    name = "http"

    def __init__(self, base_url: str, path: str = "/search", timeout_s: float = 30.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.path = path
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s, transport=transport)

    async def search(self, payload: dict) -> Any:
        try:
            r = await self.client.post(self.path, json=payload)
            r.raise_for_status()
            return r.json() if r.content else None
        except httpx.HTTPStatusError as e:
            raise EngineError(f"engine returned HTTP {e.response.status_code}") from e
        except (httpx.HTTPError, ValueError) as e:
            raise EngineError(f"{type(e).__name__}: {e}") from e

    async def aclose(self) -> None:
        await self.client.aclose()


class StubEngine:
    """No engine configured: accept the payload and say so, so the proxy can be demoed alone."""
    name = "stub"

    def __init__(self):
        self.received: list[dict] = []

    async def search(self, payload: dict) -> Any:
        self.received.append(payload)
        return {"engine": "stub", "status": "not_searched",
                "message": "ENGINE_URL is not set; the spec was validated but not searched"}
