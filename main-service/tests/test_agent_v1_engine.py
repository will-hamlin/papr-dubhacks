"""AgentV1Engine posts the signed payload to /v1/proxy/search."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from main_service.engine import AgentV1Engine, EngineError


def test_agent_v1_posts_bridge_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["mode"] = request.url.params.get("mode")
        return httpx.Response(200, json={
            "engine": "agent-purchase-verifier",
            "status": "awaiting_user_approval",
            "request_id": "req_test",
            "approval_url": "http://127.0.0.1:8001/#/requests/req_test",
            "message": "approve",
        })

    eng = AgentV1Engine("http://engine.test", api_key="vpk_x", mode="supervised", poll_s=0,
                        transport=httpx.MockTransport(handler))

    async def run():
        out = await eng.search({"order_id": "o_1", "request_text": "shoes", "proxy_sig": "abc"})
        await eng.aclose()
        return out

    out = asyncio.run(run())
    assert seen["path"] == "/v1/proxy/search"
    assert seen["auth"] == "Bearer vpk_x"
    assert seen["mode"] == "supervised"
    assert out["approval_url"].endswith("req_test")


def test_agent_v1_maps_http_errors():
    eng = AgentV1Engine("http://engine.test", api_key="vpk_x", poll_s=0,
                        transport=httpx.MockTransport(lambda r: httpx.Response(502, text="down")))

    async def run():
        with pytest.raises(EngineError, match="502"):
            await eng.search({"order_id": "o_1", "request_text": "x"})
        await eng.aclose()

    asyncio.run(run())
