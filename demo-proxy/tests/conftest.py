import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from proxy.app import create_app
from proxy.engine import StubEngine
from proxy.service import Settings
from proxy.signing import make_auth, sign_payload
from proxy.spec import RuleSpecParser

DATA = Path(__file__).resolve().parent.parent / "data"
SECRET = "test-secret"


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class Env:
    def __init__(self, tmp_path: Path, policy: dict | None = None, parser=None, engine=None):
        self.data = tmp_path / "data"
        shutil.copytree(DATA, self.data)
        if policy:
            p = json.loads((self.data / "company_policy.json").read_text())
            p.update(policy)
            (self.data / "company_policy.json").write_text(json.dumps(p))
        self.clock = Clock()
        self.settings = Settings(shared_secret=SECRET, data_dir=self.data, var_dir=tmp_path / "var")
        self.engine = engine or StubEngine()
        self.app = create_app(self.settings, parser=parser or RuleSpecParser(), engine=self.engine,
                              clock=self.clock)
        self.proxy = self.app.state.proxy
        self.client = TestClient(self.app)

    def auth(self, user_id="u_jordan", **kw):
        return make_auth(user_id, SECRET, now=self.clock(), **kw)

    def order(self, text, user_id="u_jordan", auth=None):
        r = self.client.post("/orders", json={"auth": auth or self.auth(user_id), "request_text": text})
        return r.status_code, r.json()

    def purchase(self, order_id, total_cents, secret=SECRET):
        body = sign_payload({"order_id": order_id, "total_cents": total_cents}, secret)
        r = self.client.post("/purchases", json=body)
        return r.status_code, r.json()


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
