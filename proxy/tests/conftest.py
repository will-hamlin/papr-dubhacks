import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from proxy.app import create_app
from proxy.handoff import HandoffError
from proxy.service import Settings
from proxy.signing import make_auth, sign_payload

DATA = Path(__file__).resolve().parent.parent / "data"
SECRET = "test-secret"
TOKEN = "test-token"

# Shaped like demo/configs (the employee dashboard's seed profiles).
NORTHSTAR = {"companyId": "CO-001", "name": "Northstar Industries", "industry": "Business services",
             "currency": "USD", "billingAddress": "120 Market Street, Seattle, WA 98101",
             "purchaseOrderPrefix": "NS",
             "purchasePolicy": {"approvalRequiredAbove": 5000, "preferredVendors": ["Staples", "Dell", "Grainger"],
                                "paymentTerms": "Net 30"}}
ALEX = {"employeeId": "EMP-1042", "companyId": "CO-001", "name": "Alex Morgan", "email": "alex.morgan@northstar.example",
        "department": "Executive", "role": "CEO", "costCenter": "EXEC-100", "approvalLimit": 50000, "currency": "USD"}
JAMIE = {**ALEX, "employeeId": "EMP-1088", "name": "Jamie Chen", "role": "Intern", "costCenter": "OPS-100",
         "approvalLimit": 0}


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class RecordingMS:
    def __init__(self):
        self.received = []
        self.fail = False

    async def submit(self, payload):
        if self.fail:
            raise HandoffError("MS offline")
        self.received.append(payload)
        return {"order_id": payload["order_id"], "documented": True,
                "status": "queued" if payload["authorization"]["accepted"] else "rejected"}

    async def aclose(self):
        pass


class Env:
    def __init__(self, tmp_path: Path, policy: dict | None = None, main_service=None):
        self.data = tmp_path / "data"
        shutil.copytree(DATA, self.data)
        if policy:
            p = json.loads((self.data / "company_policy.json").read_text())
            p.update(policy)
            (self.data / "company_policy.json").write_text(json.dumps(p))
        self.clock = Clock()
        self.settings = Settings(shared_secret=SECRET, api_token=TOKEN, data_dir=self.data, var_dir=tmp_path / "var",
                                 allow_legacy_config=True)
        self.main_service = main_service or RecordingMS()
        self.app = create_app(self.settings, main_service=self.main_service,
                              clock=self.clock)
        self.proxy = self.app.state.proxy
        self.client = TestClient(self.app)

    def auth(self, user_id="u_jordan", **kw):
        return make_auth(user_id, SECRET, now=self.clock(), **kw)

    def order(self, text, user_id="u_jordan", auth=None):
        r = self.client.post("/orders", json={"auth": auth or self.auth(user_id), "request_text": text})
        return r.status_code, r.json()

    def dashboard(self, text, user=None, company=None, request_id=None, token=TOKEN):
        body = {"request": {"id": request_id or str(uuid.uuid4()), "createdAt": self.clock().isoformat(), "text": text},
                "userConfig": user or ALEX, "companyConfig": company or NORTHSTAR}
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        r = self.client.post("/orders", json=body, headers=headers)
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
