import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from proxy.app import create_app
from proxy.service import Settings

DATA = Path(__file__).resolve().parent.parent / "data"
SECRET = "test-secret"


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class StubAgent:
    """Records calls and does nothing; tests drive events through the real webhook."""

    def __init__(self):
        self.calls = []

    async def start_run(self, request_text, session, session_sig, callback_url):
        self.calls.append(("start_run", dict(request_text=request_text, session=session,
                                             session_sig=session_sig, callback_url=callback_url)))
        return f"ag_{len(self.calls)}"

    async def approve_spec(self, run_id, approved_by):
        self.calls.append(("approve_spec", dict(run_id=run_id, approved_by=approved_by)))

    async def approve_cart(self, run_id, approved_by, cart_hash):
        self.calls.append(("approve_cart", dict(run_id=run_id, approved_by=approved_by, cart_hash=cart_hash)))


class Env:
    def __init__(self, tmp_path: Path, policy: dict | None = None, agent=None):
        self.data = tmp_path / "data"
        shutil.copytree(DATA, self.data)
        if policy:
            p = json.loads((self.data / "company_policy.json").read_text())
            p.update(policy)
            (self.data / "company_policy.json").write_text(json.dumps(p))
        self.clock = Clock()
        self.settings = Settings(data_dir=self.data, var_dir=tmp_path / "var", fake_delay_s=0,
                                 shared_secret=SECRET)
        self.app = create_app(self.settings, agent=agent, clock=self.clock)
        self.proxy = self.app.state.proxy
        self.agent = self.proxy.agent
        self.clients = {}

    def as_user(self, user_id: str) -> TestClient:
        if user_id not in self.clients:
            c = TestClient(self.app)
            assert c.post("/login", json={"user_id": user_id}).status_code == 200
            self.clients[user_id] = c
        return self.clients[user_id]

    def request(self, text: str, user_id: str = "u_jordan") -> dict:
        r = self.as_user(user_id).post("/request", json={"request_text": text})
        assert r.status_code == 200, r.text
        return r.json()

    def approve_spec(self, run: dict, user_id: str = "u_jordan") -> dict:
        r = self.as_user(user_id).post(f"/runs/{run['id']}/approve-spec")
        assert r.status_code == 200, r.text
        return r.json()

    def approve_cart(self, run: dict, user_id: str = "u_jordan") -> dict:
        r = self.as_user(user_id).post(f"/runs/{run['id']}/approve-cart", json={"cart_hash": run["cart_hash"]})
        assert r.status_code == 200, r.text
        return r.json()

    def through_cart(self, text: str) -> dict:
        run = self.request(text)
        assert run["status"] == "spec_ready", run
        run = self.approve_spec(run)
        assert run["status"] == "cart_ready", run
        return self.approve_cart(run)

    def token(self, run_id: str) -> str:
        return self.proxy.runs[run_id].callback_token

    def event(self, run_id: str, type_: str, payload: dict | None = None, reason: str | None = None):
        run = self.proxy.runs[run_id]
        return self.as_user("u_jordan").post(
            f"/proxy/events?token={run.callback_token}",
            json={"run_id": run.agent_run_id, "type": type_, "payload": payload or {}, "reason": reason})

    def outbox(self, run_id: str) -> list[dict]:
        return self.proxy.outbox.for_run(run_id)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def make_env(tmp_path):
    n = [0]

    def make(**kw):
        n[0] += 1
        d = tmp_path / f"e{n[0]}"
        d.mkdir()
        return Env(d, **kw)
    return make
