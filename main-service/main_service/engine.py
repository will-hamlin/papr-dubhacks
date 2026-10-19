"""Client for the pbapo engine.

HttpEngine posts to ENGINE_URL (legacy /search).
AgentV1Engine talks to agent-purchase-verifier's Agent API / proxy bridge.
StubEngine stands in when ENGINE_URL is unset.
"""

from __future__ import annotations

import asyncio
import os
import time
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
                 transport: httpx.AsyncBaseTransport | None = None, api_key: str | None = None):
        self.path = path
        api_key = api_key or os.environ.get("ENGINE_API_KEY")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s,
                                       transport=transport, headers=headers)

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


class AgentV1Engine:
    """agent-purchase-verifier via POST /v1/proxy/search (+ optional poll).

    Env:
      VP_AGENT_KEY / ENGINE_AGENT_KEY — Required bearer key, issued by the verifier
      VP_PROXY_MODE / ENGINE_MODE — supervised | purchase_only | autonomous
      ENGINE_POLL_S — seconds to wait for search after create (0 = return immediately)
    """

    name = "agent_v1"

    def __init__(self, base_url: str, *, api_key: str | None = None, mode: str | None = None,
                 poll_s: float | None = None, timeout_s: float = 300.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("VP_AGENT_KEY") or os.environ.get("ENGINE_AGENT_KEY")
        if not self.api_key:
            raise RuntimeError("VP_AGENT_KEY or ENGINE_AGENT_KEY is required for the agent-v1 backend")
        self.mode = mode or os.environ.get("VP_PROXY_MODE") or os.environ.get("ENGINE_MODE") or "supervised"
        if self.mode not in {"supervised", "purchase_only", "autonomous"}:
            raise RuntimeError("VP_PROXY_MODE must be supervised, purchase_only, or autonomous")
        self.poll_s = float(os.environ["ENGINE_POLL_S"]) if poll_s is None and "ENGINE_POLL_S" in os.environ else (
            0.0 if poll_s is None else poll_s)
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            transport=transport,
        )

    async def search(self, payload: dict) -> Any:
        # Do not mutate the signed payload — mode travels as a query param.
        try:
            r = await self.client.post("/v1/proxy/search", params={"mode": self.mode}, json=payload)
            if r.status_code >= 400:
                raise EngineError(f"engine returned HTTP {r.status_code}")
            result = r.json() if r.content else {}
        except httpx.HTTPError as e:
            raise EngineError(f"{type(e).__name__}: {e}") from e

        if self.poll_s > 0 and result.get("request_id"):
            result = await self._poll(result["request_id"], result, self.poll_s)
        return result

    async def _poll(self, rid: str, current: dict, budget_s: float) -> dict:
        deadline = time.monotonic() + budget_s
        while time.monotonic() < deadline:
            status = current.get("status")
            if current.get("approval_url") or current.get("report") or current.get("top") or \
                    status in ("purchased", "failed", "escalated") or current.get("failure"):
                return current
            if status not in ("searching", "verifying", "needs_info"):
                # awaiting_user_approval without url is still a stop; otherwise keep going briefly
                if status == "awaiting_user_approval":
                    return current
            await asyncio.sleep(2.0)
            try:
                r = await self.client.get(f"/v1/requests/{rid}")
                r.raise_for_status()
                view = r.json()
            except httpx.HTTPError:
                return current
            current = {
                **current,
                "status": view.get("status"),
                "gate": view.get("gate"),
                "approval_url": view.get("approval_url"),
                "approval_settings": view.get("approval_settings"),
                "questions": view.get("questions") or [],
                "top": view.get("top") or [],
                "report": view.get("report"),
                "failure": view.get("failure"),
                "downgrades": view.get("downgrades") or [],
                "message": view.get("failure") or current.get("message"),
            }
        return current

    async def status(self, request_id: str) -> dict:
        from urllib.parse import quote
        try:
            response = await self.client.get(f"/v1/requests/{quote(request_id, safe='')}")
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("verifier returned an invalid status")
            return result
        except (httpx.HTTPError, ValueError) as exc:
            raise EngineError(str(exc)) from exc

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
