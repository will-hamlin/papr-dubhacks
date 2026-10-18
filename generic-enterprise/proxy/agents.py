"""Agent clients. HttpAgent talks to the real agent at AGENT_URL; FakeAgent is a scripted stand-in."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import quote

import httpx

from .session_sig import cart_hash, verify_session


class AgentError(Exception):
    pass


class Agent(Protocol):
    async def start_run(self, request_text: str, session: dict, session_sig: str, callback_url: str) -> str: ...
    async def approve_spec(self, run_id: str, approved_by: str) -> None: ...
    async def approve_cart(self, run_id: str, approved_by: str, cart_hash: str) -> None: ...


class HttpAgent:
    def __init__(self, base_url: str, timeout_s: float = 15.0, transport: httpx.AsyncBaseTransport | None = None):
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s, transport=transport)

    async def _post(self, path: str, body: dict) -> dict:
        try:
            r = await self.client.post(path, json=body)
            r.raise_for_status()
            return r.json() if r.content else {}
        except (httpx.HTTPError, ValueError) as e:
            raise AgentError(f"{type(e).__name__}: {e}") from e

    async def start_run(self, request_text, session, session_sig, callback_url) -> str:
        out = await self._post("/agent/runs", {"request_text": request_text, "session": session,
                                               "session_sig": session_sig, "callback_url": callback_url})
        run_id = out.get("run_id") if isinstance(out, dict) else None
        if not isinstance(run_id, str) or not run_id:
            raise AgentError("agent response has no run_id")
        return run_id

    async def approve_spec(self, run_id, approved_by) -> None:
        await self._post(f"/agent/runs/{quote(run_id, safe='')}/approve-spec", {"approved_by": approved_by})

    async def approve_cart(self, run_id, approved_by, cart_hash) -> None:
        await self._post(f"/agent/runs/{quote(run_id, safe='')}/approve-cart",
                         {"approved_by": approved_by, "cart_hash": cart_hash})

    async def aclose(self) -> None:
        await self.client.aclose()


# ---------------------------------------------------------------- fake agent

def _item(sku, name, supplier, category, price_cents, qty=1) -> dict:
    return {"sku": sku, "name": name, "supplier_id": supplier, "category": category,
            "unit_price_cents": price_cents, "qty": qty}


@dataclass
class Script:
    name: str
    keywords: tuple[str, ...]
    spec: dict | None = None
    cart: dict | None = None
    flag_on_start: str | None = None
    error_on_start: str | None = None
    # Extra events emitted after the user approves the cart, instead of "purchased".
    on_cart: list[tuple[str, dict, str | None]] | None = None

    def matches(self, text: str) -> bool:
        t = text.lower()
        return any(k in t for k in self.keywords)


def default_scripts() -> list[Script]:
    return [
        Script("gift_card", ("gift card", "giftcard"), flag_on_start="blocked category: gift_cards"),
        # Defense-in-depth demos: the agent misbehaves and the proxy still blocks the cart.
        Script("rogue_category", ("hunting knife",),
               spec={"item": "hunting knife", "qty": 1},
               cart={"items": [_item("CE-KN-01", "Fixed-blade hunting knife", "sup_01", "weapons", 3999)]}),
        Script("rogue_supplier", ("any seller", "any supplier"),
               spec={"item": "USB-C charger", "wattage_w": 65, "qty": 1, "seller": "any"},
               cart={"items": [_item("OS-65W", "65W USB-C charger (refurb)", "sup_02", "electronics", 2999)]}),
        Script("manager_said", ("manager said", "$5,000", "$5000", "expensive one"),
               spec={"item": "laptop", "tier": "most expensive available",
                     "requested_budget_cents": 500000,
                     "budget_source": "request text (not authoritative)", "qty": 1},
               cart={"items": [_item("PT-WS-9000", "Workstation laptop 16in, 64GB RAM", "sup_03",
                                     "electronics", 189900)]}),
        Script("laptop", ("laptop",),
               spec={"item": "laptop", "use": "job site", "rugged": True, "qty": 1},
               cart={"items": [_item("PT-RG-14", "Rugged 14in field laptop", "sup_03", "electronics", 124900)]}),
        Script("charger", ("charger",),
               spec={"item": "USB-C laptop charger", "wattage_w": 65, "connector": "USB-C (PD)",
                     "compatible_with": "Dell XPS 13", "qty": 1, "max_unit_price_cents": 10000},
               cart={"items": [_item("CE-65W-PD", "65W USB-C PD charger, XPS 13 compatible", "sup_01",
                                     "electronics", 6499)]}),
    ]


Deliver = Callable[[str, dict], Awaitable[None]]


@dataclass
class _FakeRun:
    script: Script
    callback_url: str
    cart_hash: str | None = None


@dataclass
class FakeAgent:
    """Emits scripted events to the proxy's webhook handler. delay_s=0 delivers inline (tests)."""
    secret: str
    deliver: Deliver
    clock: Callable[[], datetime]
    delay_s: float = 1.0
    scripts: list[Script] = field(default_factory=default_scripts)
    runs: dict[str, _FakeRun] = field(default_factory=dict)
    calls: list[tuple[str, dict]] = field(default_factory=list)
    _tasks: set = field(default_factory=set)

    def match(self, text: str) -> Script | None:
        return next((s for s in self.scripts if s.matches(text)), None)

    async def _emit(self, run_id: str, events: list[tuple[str, dict, str | None]]) -> None:
        async def go():
            for type_, payload, reason in events:
                if self.delay_s:
                    await asyncio.sleep(self.delay_s)
                await self.deliver(self.runs[run_id].callback_url,
                                   {"run_id": run_id, "type": type_, "payload": payload, "reason": reason})
        if self.delay_s:
            task = asyncio.create_task(go())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            await go()

    async def start_run(self, request_text, session, session_sig, callback_url) -> str:
        self.calls.append(("start_run", {"request_text": request_text, "session": session}))
        # A real agent must do this too: refuse anything the proxy didn't sign.
        if not verify_session(session, session_sig, self.secret, now=self.clock()):
            raise AgentError("fake agent rejected session: bad signature or expired")
        run_id = "fa_" + secrets.token_hex(4)
        script = self.match(request_text) or Script("unknown", ())
        self.runs[run_id] = _FakeRun(script, callback_url)
        if script.name == "unknown":
            await self._emit(run_id, [("error", {}, "fake agent has no script for this request; "
                                                     "try one of the demo requests")])
        elif script.flag_on_start:
            await self._emit(run_id, [("flagged", {}, script.flag_on_start)])
        else:
            await self._emit(run_id, [("spec_ready", {"spec": script.spec}, None)])
        return run_id

    async def approve_spec(self, run_id, approved_by) -> None:
        self.calls.append(("approve_spec", {"run_id": run_id, "approved_by": approved_by}))
        run = self.runs[run_id]
        cart: dict[str, Any] = run.script.cart
        run.cart_hash = cart_hash(cart)
        await self._emit(run_id, [("cart_ready", {"cart": cart, "cart_hash": run.cart_hash}, None)])

    async def approve_cart(self, run_id, approved_by, cart_hash) -> None:
        self.calls.append(("approve_cart", {"run_id": run_id, "approved_by": approved_by, "cart_hash": cart_hash}))
        run = self.runs[run_id]
        if cart_hash != run.cart_hash:
            raise AgentError("fake agent: approved cart hash does not match proposed cart")
        events = run.script.on_cart or [
            ("purchased", {"order_id": "MOCK-" + secrets.token_hex(3).upper(), "cart_hash": cart_hash}, None)]
        await self._emit(run_id, events)
