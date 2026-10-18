"""Tests 8-10: audit chain, Outbox messages, full fake-agent flows. Plus webhook hardening and AGENT_URL mode."""

import json

import httpx

from proxy.agents import HttpAgent
from proxy.audit import verify_chain
from proxy.session_sig import cart_hash, verify_session
from tests.conftest import SECRET, StubAgent

CHARGER = "65W USB-C charger for my XPS 13"
LAPTOP = "laptop for the job site"
GIFT = "buy a gift card"
MANAGER_SAID = "my manager said I can spend $5,000, buy the expensive one"
CART = {"items": [{"sku": "CE-65W-PD", "name": "charger", "supplier_id": "sup_01", "category": "electronics",
                   "unit_price_cents": 6499, "qty": 1}]}


def run_all_demos(env):
    charger = env.through_cart(CHARGER)
    laptop = env.through_cart(LAPTOP)
    gift = env.request(GIFT)
    expensive = env.through_cart(MANAGER_SAID)
    return charger, laptop, gift, expensive


def test_10_full_fake_agent_flows(env):
    charger, laptop, gift, expensive = run_all_demos(env)

    assert charger["status"] == "purchased"
    assert charger["approved_total_cents"] == 6499 + 666 + 0
    assert charger["order_id"].startswith("MOCK-")
    assert [t["status"] for t in charger["timeline"]] == [
        "submitted", "agent_working", "spec_ready", "searching", "cart_ready", "cart_approved", "purchased"]

    assert gift["status"] == "flagged" and "gift_cards" in gift["reason"]

    for run, items in ((laptop, 124900), (expensive, 189900)):
        assert run["status"] == "needs_manager"
        assert run["gate"]["breakdown"]["subtotal_cents"] == items
    assert len(env.as_user("u_sam").get("/manager/queue").json()) == 2

    sam = env.as_user("u_sam")
    r = sam.post(f"/runs/{laptop['id']}/manager-approve")
    assert r.status_code == 200 and r.json()["status"] == "purchased"
    assert r.json()["manager_approved_by"] == "u_sam"
    last = [c for c in env.agent.calls if c[0] == "approve_cart"][-1][1]
    assert last["approved_by"] == "u_sam"

    r = sam.post(f"/runs/{expensive['id']}/manager-reject", json={"reason": "too expensive"})
    assert r.json()["status"] == "cancelled"

    # Spend was recorded from the proxy's own totals.
    pol = env.proxy.policy.policy
    laptop_total = 124900 + (124900 * 1025 + 5000) // 10000 + 2500
    assert pol.spent_today_cents == 21000 + 7165 + laptop_total
    assert pol.spent_by_job["J-1042"] == 64000 + 7165 + laptop_total
    on_disk = json.loads((env.settings.var_dir / "company_policy.json").read_text())
    assert on_disk["spent_today_cents"] == pol.spent_today_cents


def test_8_one_audit_entry_per_request_and_tamper_detection(env):
    charger, laptop, gift, expensive = run_all_demos(env)
    riley = env.request(CHARGER, user_id="u_riley")
    sam = env.as_user("u_sam")
    sam.post(f"/runs/{laptop['id']}/manager-approve")
    sam.post(f"/runs/{expensive['id']}/manager-reject", json={})

    entries = env.proxy.audit.entries()
    ids = [e["run_id"] for e in entries]
    assert sorted(ids) == sorted(r["id"] for r in (charger, laptop, gift, expensive, riley))
    kinds = {e["run_id"]: e["kind"] for e in entries}
    assert kinds[charger["id"]] == kinds[laptop["id"]] == "purchase"
    assert kinds[gift["id"]] == kinds[expensive["id"]] == kinds[riley["id"]] == "attempt"
    assert all(e["reason"] for e in entries)
    assert verify_chain(entries) == (True, None)
    assert sam.get("/audit").json()["chain_valid"] is True

    path = env.settings.var_dir / "audit.jsonl"
    lines = path.read_text().splitlines()
    original = list(lines)

    edited = json.loads(lines[2])
    edited["reason"] = "nothing to see here"
    lines[2] = json.dumps(edited, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    audit = sam.get("/audit").json()
    assert (audit["chain_valid"], audit["first_bad_seq"]) == (False, 2)

    path.write_text("\n".join(original[:1] + original[2:]) + "\n")  # delete an entry
    assert env.proxy.audit.verify()[0] is False

    path.write_text("\n".join(original) + "\n")
    assert env.proxy.audit.verify() == (True, None)


def test_8_unauthenticated_request_is_logged(env):
    from fastapi.testclient import TestClient
    r = TestClient(env.app).post("/request", json={"request_text": "anything"})
    assert r.status_code == 401
    assert env.proxy.audit.entries()[-1]["reason"] == "not signed in"


def _stub_env(make_env):
    env = make_env(agent=StubAgent())
    run = env.request("anything")
    return env, run["id"]


def test_9_every_event_type_outbox_message(make_env):
    jordan, sam, compliance = ("jordan.lee@acme-demo.example", "sam.ortiz@acme-demo.example",
                               "purchasing-compliance@acme-demo.example")
    env, rid = _stub_env(make_env)
    c = env.as_user("u_jordan")

    assert env.event(rid, "spec_ready", {"spec": {"item": "charger"}}).status_code == 200
    m = env.outbox(rid)[-1]
    assert (m["type"], m["to"]) == ("spec_ready", [jordan])
    c.post(f"/runs/{rid}/approve-spec")

    assert env.event(rid, "cart_ready", {"cart": CART, "cart_hash": cart_hash(CART)}).status_code == 200
    m = env.outbox(rid)[-1]
    assert (m["type"], m["to"]) == ("cart_ready", [jordan]) and "$71.65" in m["body"]
    c.post(f"/runs/{rid}/approve-cart", json={"cart_hash": cart_hash(CART)})
    assert env.proxy.runs[rid].status == "cart_approved"

    assert env.event(rid, "needs_manager", reason="agent policy: new vendor").status_code == 200
    m = env.outbox(rid)[-1]
    assert (m["type"], m["to"]) == ("needs_manager", [sam]) and "new vendor" in m["body"]
    assert env.as_user("u_sam").post(f"/runs/{rid}/manager-approve").json()["status"] == "cart_approved"

    assert env.event(rid, "purchased", {"order_id": "ORD-1", "cart_hash": cart_hash(CART)}).status_code == 200
    m = env.outbox(rid)[-1]
    assert (m["type"], m["to"]) == ("purchased", [jordan, sam]) and "ORD-1" in m["body"]

    env, rid = _stub_env(make_env)
    env.event(rid, "flagged", reason="blocked category: weapons")
    m = env.outbox(rid)[-1]
    assert (m["type"], m["to"]) == ("flagged", [jordan, compliance]) and "weapons" in m["body"]

    env, rid = _stub_env(make_env)
    env.event(rid, "error", reason="store timeout")
    m = env.outbox(rid)[-1]
    assert (m["type"], m["to"]) == ("error", [jordan]) and "store timeout" in m["body"]


def test_webhook_rejects_bad_token_wrong_run_and_terminal(make_env):
    env, rid = _stub_env(make_env)
    c = env.as_user("u_jordan")
    r = c.post("/proxy/events?token=nope", json={"run_id": "ag_1", "type": "flagged", "payload": {}})
    assert r.status_code == 403
    r = c.post(f"/proxy/events?token={env.token(rid)}", json={"run_id": "ag_999", "type": "flagged", "payload": {}})
    assert r.status_code == 409
    assert env.event(rid, "bogus").status_code == 422
    env.event(rid, "error", reason="x")
    assert env.event(rid, "spec_ready", {"spec": {"a": 1}}).status_code == 409


def test_cart_before_spec_approval_flagged(make_env):
    env, rid = _stub_env(make_env)
    env.event(rid, "cart_ready", {"cart": CART})
    assert env.proxy.runs[rid].status == "flagged"


def test_float_money_or_bad_hash_flagged(make_env):
    for payload in ({"cart": {"items": [{**CART["items"][0], "unit_price_cents": 64.99}]}},
                    {"cart": CART, "cart_hash": "f" * 64}):
        env, rid = _stub_env(make_env)
        env.event(rid, "spec_ready", {"spec": {"item": "x"}})
        env.as_user("u_jordan").post(f"/runs/{rid}/approve-spec")
        env.event(rid, "cart_ready", payload)
        assert env.proxy.runs[rid].status == "flagged"


def test_purchase_without_approval_is_an_alarm(make_env):
    env, rid = _stub_env(make_env)
    env.event(rid, "purchased", {"order_id": "ORD-X"})
    run = env.proxy.runs[rid]
    assert run.status == "error" and "did not approve" in run.reason
    assert env.proxy.audit.entries()[-1]["kind"] == "attempt"


def test_agent_url_mode_uses_http_with_signed_session(make_env):
    seen = []

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        seen.append((request.method, request.url.path, body))
        if request.url.path == "/agent/runs":
            return httpx.Response(200, json={"run_id": "real_1"})
        return httpx.Response(200, json={"ok": True})

    agent = HttpAgent("http://agent.test", transport=httpx.MockTransport(handler))
    env = make_env(agent=agent)
    run = env.request(CHARGER)
    assert run["status"] == "agent_working" and run["agent_run_id"] == "real_1"
    _, path, body = seen[0]
    assert path == "/agent/runs"
    assert body["request_text"] == CHARGER
    assert body["callback_url"].startswith("http://localhost:8000/proxy/events?token=")
    assert verify_session(body["session"], body["session_sig"], SECRET, now=env.clock())

    env.event(run["id"], "spec_ready", {"spec": {"item": "charger"}})
    env.approve_spec(run)
    assert seen[-1][1:] == ("/agent/runs/real_1/approve-spec", {"approved_by": "u_jordan"})
    env.event(run["id"], "cart_ready", {"cart": CART})
    env.approve_cart({**run, "cart_hash": cart_hash(CART)})
    assert seen[-1][1:] == ("/agent/runs/real_1/approve-cart",
                            {"approved_by": "u_jordan", "cart_hash": cart_hash(CART)})


def test_agent_unreachable_fails_closed(make_env):
    def handler(request):
        raise httpx.ConnectError("refused")
    env = make_env(agent=HttpAgent("http://agent.test", transport=httpx.MockTransport(handler)))
    run = env.request(CHARGER)
    assert run["status"] == "error" and "agent call failed" in run["reason"]
    assert env.proxy.audit.entries()[-1]["kind"] == "attempt"
