"""Proxy authorization, compiled handoffs, purchase counters, and durable delivery."""
import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from proxy.app import create_app
from proxy.signing import make_auth, sign, sign_payload, verify_payload
from .conftest import ALEX, JAMIE, NORTHSTAR, SECRET

CHARGER = "65W USB-C charger for my XPS 13"

def test_purchase_moves_spend_so_next_order_ceiling_shrinks(env):
    # Sam: min(limit 5000.00, daily 1500.00-210.00, job 3000.00-640.00) = 1290.00
    _, first = env.order(CHARGER, user_id="u_sam")
    assert first["limits"]["max_total_cents"] == 129000
    status, body = env.purchase(first["order_id"], 40000)
    assert (status, body["decision"], body["ok"]) == (200, "recorded", True)

    _, second = env.order(CHARGER, user_id="u_sam")
    assert second["limits"]["max_total_cents"] == 89000
    spend = json.loads((env.settings.var_dir / "spend.json").read_text())
    assert spend["spent_today_cents"] == 61000 and spend["spent_by_job"]["J-1042"] == 104000

    entry = env.proxy.audit.entries()[-2]
    assert entry["kind"] == "purchase" and entry["order_id"] == first["order_id"] and entry["total_cents"] == 40000
    assert env.client.get("/audit", headers={"Authorization": "Bearer test-token"}).json()["chain_valid"] is True


def test_purchase_bad_signature_rejected(env):
    _, order = env.order(CHARGER)
    status, body = env.purchase(order["order_id"], 1000, secret="other-secret")
    assert (status, body["decision"]) == (401, "not_authorized")
    tampered = {**sign_payload({"order_id": order["order_id"], "total_cents": 50000}, SECRET), "total_cents": 100}
    assert env.client.post("/purchases", json=tampered).status_code == 401
    assert env.client.post("/purchases", json={"order_id": order["order_id"]}).status_code == 400
    assert env.proxy.policy.spend("J-1042") == (21000, 64000)


def test_purchase_unknown_or_rejected_order(env):
    status, body = env.purchase("o_doesnotexist", 1000)
    assert (status, body["decision"]) == (404, "unknown_order")
    _, rejected = env.order("buy a gift card")
    status, _ = env.purchase(rejected["order_id"], 1000)
    assert status == 404
    assert env.proxy.policy.spend("J-1042") == (21000, 64000)


@pytest.mark.parametrize("total,decision", [(50001, "over_limit"), (-1, "invalid_total"),
                                            (100.0, "invalid_total"), ("100", "invalid_total"),
                                            (True, "invalid_total")])
def test_purchase_over_limit_or_bad_total_rejected_and_flagged(env, total, decision):
    _, order = env.order(CHARGER)  # Jordan: max_total_cents 50000
    status, body = env.purchase(order["order_id"], total)
    assert (status, body["decision"], body["ok"]) == (409, decision, False)
    entry = env.proxy.audit.entries()[-1]
    assert entry["kind"] == "purchase_attempt" and entry["flagged"] is True
    assert env.proxy.policy.spend("J-1042") == (21000, 64000)


def test_purchase_exactly_at_limit_and_zero_accepted(env):
    _, a = env.order(CHARGER)
    _, b = env.order(CHARGER)
    assert env.purchase(a["order_id"], 50000)[0] == 200
    assert env.purchase(b["order_id"], 0)[0] == 200
    assert env.proxy.policy.spend("J-1042") == (71000, 114000)


def test_purchase_idempotent_per_order_including_after_restart(env):
    _, order = env.order(CHARGER)
    assert env.purchase(order["order_id"], 30000)[1]["decision"] == "recorded"
    status, body = env.purchase(order["order_id"], 30000)
    assert (status, body["decision"], body["ok"]) == (200, "duplicate", True)
    status, body = env.purchase(order["order_id"], 20000)
    assert (status, body["decision"]) == (409, "conflict")
    assert env.proxy.policy.spend("J-1042") == (51000, 94000)
    assert [e["kind"] for e in env.proxy.audit.entries()].count("purchase") == 1

    restarted = create_app(env.settings, main_service=env.main_service, clock=env.clock)
    client = TestClient(restarted)
    again = client.post("/purchases", json=sign_payload({"order_id": order["order_id"], "total_cents": 30000},
                                                         SECRET)).json()
    assert again["decision"] == "duplicate"
    assert restarted.state.proxy.policy.spend("J-1042") == (51000, 94000)


@pytest.mark.parametrize("mutate", [
    lambda a: {**a, "user_id": "u_sam"},
    lambda a: {**a, "expires_at": "2099-01-01T00:00:00+00:00"},
    lambda a: {**a, "sig": "0" * 64},
    lambda a: {k: v for k, v in a.items() if k != "sig"},
    lambda a: {**a, "spend_limit_cents": 500000},
])
def test_tampered_auth_rejected(env, mutate):
    status, body = env.order(CHARGER, auth=mutate(env.auth()))
    assert status == 401 and body["decision"] == "not_authorized" and not body["ok"]
    assert all(not h["authorization"]["accepted"] for h in env.main_service.received)


def test_expired_and_wrong_secret_auth_rejected(env):
    old = env.auth()
    env.clock.advance(minutes=31)
    status, body = env.order(CHARGER, auth=old)
    assert (status, body["decision"]) == (401, "not_authorized") and "expired" in body["reason"]
    status, body = env.order(CHARGER, auth=make_auth("u_jordan", "wrong", now=env.clock()))
    assert status == 401 and "bad signature" in body["reason"]


def test_unknown_user_rejected(env):
    status, body = env.order(CHARGER, user_id="u_nobody")
    assert (status, body["reason"]) == (401, "unknown user")


def test_exhausted_cap_not_authorized(make_env):
    env = make_env(policy={"spent_today_cents": 150000})
    status, body = env.order(CHARGER)
    assert (status, body["decision"]) == (403, "not_authorized") and "daily cap" in body["reason"]


@pytest.mark.parametrize("text,needle", [
    ("buy a gift card", "gift"),
    ("hunting knife for the site", "weapons"),
    ("a case of beer for the crew", "age_restricted"),
    ("ibuprofen for the first aid kit", "medicine"),
])
def test_blocked_requests_violate_policy(env, text, needle):
    status, body = env.order(text)
    assert (status, body["decision"]) == (403, "violates_company_policy")
    assert needle in body["reason"]
    assert all(not h["authorization"]["accepted"] for h in env.main_service.received)


def test_ceiling_is_min_of_limit_and_remaining_caps(make_env):
    env = make_env(policy={"spent_today_cents": 140000})
    _, body = env.order(CHARGER)
    assert body["limits"]["max_total_cents"] == 10000
    env = make_env(policy={"spent_by_job": {"J-1042": 299000}})
    _, body = env.order(CHARGER)
    assert body["limits"]["max_total_cents"] == 1000


def test_every_call_audited_once_and_chain_tamper_detected(env):
    calls = [env.order(CHARGER), env.order("buy a gift card"), env.order(CHARGER, user_id="u_riley"),
             env.order(CHARGER, auth={"user_id": "u_jordan"})]
    r = env.client.post("/orders", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["decision"] == "bad_request"
    entries = env.proxy.audit.entries()
    assert len(entries) == 5
    assert [e["order_id"] for e in entries[:4]] == [b["order_id"] for _, b in calls]
    assert [e["decision"] for e in entries] == ["accepted", "violates_company_policy", "not_authorized",
                                                "not_authorized", "bad_request"]
    assert entries[0]["kind"] == "order" and entries[1]["kind"] == "attempt"
    assert env.client.get("/audit", headers={"Authorization": "Bearer test-token"}).json()["chain_valid"] is True

    path = env.settings.var_dir / "audit.jsonl"
    lines = path.read_text().splitlines()
    e = json.loads(lines[1])
    e["decision"] = "accepted"
    lines[1] = json.dumps(e, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")
    audit = env.client.get("/audit", headers={"Authorization": "Bearer test-token"}).json()
    assert (audit["chain_valid"], audit["first_bad_seq"]) == (False, 1)


def test_missing_secret_refuses_to_start(tmp_path):
    from proxy.service import Proxy, Settings
    with pytest.raises(RuntimeError):
        Proxy(Settings(shared_secret="", var_dir=tmp_path))


def test_sign_is_order_independent():
    assert sign({"a": 1, "b": [1, 2]}, SECRET) == sign({"b": [1, 2], "a": 1}, SECRET)


def test_dashboard_zero_limit_and_blocked_items_refused(env):
    status, body = env.dashboard(CHARGER, user=JAMIE)
    assert (status, body["decision"]) == (403, "not_authorized") and "$0.00" in body["reason"]
    status, body = env.dashboard("buy a $50 gift card for the team")
    assert (status, body["decision"]) == (403, "violates_company_policy")
    assert all(not h["authorization"]["accepted"] for h in env.main_service.received)


def test_dashboard_needs_bearer_token(env, make_env):
    for token in (None, "wrong"):
        status, body = env.dashboard(CHARGER, token=token)
        assert (status, body["decision"]) == (401, "not_authorized")
    env2 = make_env()
    env2.proxy.settings.api_token = ""
    assert env2.dashboard(CHARGER)[0] == 401
    assert all(not h["authorization"]["accepted"] for h in env.main_service.received)


@pytest.mark.parametrize("user,company", [
    ({**ALEX, "companyId": "CO-999"}, NORTHSTAR),
    ({**ALEX, "currency": "EUR"}, NORTHSTAR),
    ({**ALEX, "approvalLimit": -5}, NORTHSTAR),
    ({**ALEX, "approvalLimit": "lots"}, NORTHSTAR),
    ({**ALEX, "approvalLimit": 10.555}, NORTHSTAR),
    ({**ALEX, "approvalLimit": True}, NORTHSTAR),
    ({k: v for k, v in ALEX.items() if k != "employeeId"}, NORTHSTAR),
])
def test_dashboard_bad_profiles_rejected(env, user, company):
    status, body = env.dashboard(CHARGER, user=user, company=company)
    assert (status, body["decision"]) == (400, "bad_request")


def test_dashboard_dollar_amounts_become_integer_cents(env):
    _, body = env.dashboard(CHARGER, user={**ALEX, "approvalLimit": 1234.5})
    assert body["limits"]["max_total_cents"] == 123450


def test_dashboard_retry_returns_first_answer(env):
    first = env.dashboard(CHARGER, request_id="req-r")
    again = env.dashboard(CHARGER, request_id="req-r")
    assert again[0] == 200 and again[1]["duplicate"] is True
    assert {**again[1], "duplicate": None} == {**first[1], "duplicate": None}
    assert sum(h["authorization"]["accepted"] for h in env.main_service.received) == 1
    assert env.proxy.audit.entries()[-1]["decision"] == "duplicate_request"

    refused = env.dashboard("gift card", request_id="req-g")
    assert env.dashboard("gift card", request_id="req-g")[0] == refused[0] == 403

    status, body = env.dashboard("a different thing", request_id="req-r")
    assert (status, body["decision"]) == (409, "conflict")

    restarted = TestClient(create_app(env.settings, main_service=env.main_service, clock=env.clock))
    r = restarted.post("/orders", headers={"Authorization": "Bearer test-token"}, json={
        "request": {"id": "req-r", "createdAt": "x", "text": CHARGER}, "userConfig": ALEX, "companyConfig": NORTHSTAR})
    assert r.json()["order_id"] == first[1]["order_id"] and r.json()["duplicate"] is True
    assert sum(h["authorization"]["accepted"] for h in env.main_service.received) == 1


def test_dashboard_purchase_checked_but_leaves_acme_counters(env):
    _, order = env.dashboard(CHARGER)
    assert env.purchase(order["order_id"], 500001)[0] == 409
    status, body = env.purchase(order["order_id"], 200000)
    assert (status, body["decision"]) == (200, "recorded")
    assert env.proxy.policy.spend("J-1042") == (21000, 64000)
    assert env.order(CHARGER)[1]["limits"]["max_total_cents"] == 50000
