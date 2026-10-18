"""Tests 1-2: signed session parameters."""

import copy
from datetime import datetime, timedelta

import pytest

from proxy.service import Proxy
from proxy.session_sig import check_session, SessionError, sign_session, verify_session
from tests.conftest import SECRET


@pytest.fixture
def signed(env):
    run = env.request("65W USB-C charger for my XPS 13")
    r = env.proxy.runs[run["id"]]
    return r.session, r.session_sig, env.clock()


def leaf_paths(obj, prefix=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from leaf_paths(v, prefix + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from leaf_paths(v, prefix + (i,))
    else:
        yield prefix


def mutate(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if value is None:
        return "x"
    return str(value) + "x"


def test_session_matches_contract(signed):
    session, sig, now = signed
    assert set(session) == {"session_id", "user", "company", "issued_at", "expires_at"}
    assert set(session["user"]) == {"id", "name", "role", "job_number", "cost_code", "spend_limit_cents",
                                    "approver_id", "ship_to"}
    assert set(session["company"]) == {"id", "approved_suppliers", "blocked_categories",
                                       "auto_buy_threshold_cents", "daily_cap_cents", "per_job_cap_cents",
                                       "spent_today_cents", "spent_on_job_cents", "tax_rate_bp"}
    issued = datetime.fromisoformat(session["issued_at"])
    assert issued.utcoffset() is not None
    assert datetime.fromisoformat(session["expires_at"]) - issued == timedelta(minutes=30)
    assert verify_session(session, sig, SECRET, now=now)


def test_1_any_tampered_field_fails(signed):
    session, sig, now = signed
    paths = list(leaf_paths(session))
    assert len(paths) > 15
    for path in paths:
        s = copy.deepcopy(session)
        node = s
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = mutate(node[path[-1]])
        assert not verify_session(s, sig, SECRET, now=now), path


def test_1_added_field_wrong_key_and_bad_sig_fail(signed):
    session, sig, now = signed
    assert not verify_session({**session, "extra": 1}, sig, SECRET, now=now)
    s = copy.deepcopy(session)
    s["user"]["spend_limit_cents"] = 500000
    assert not verify_session(s, sig, SECRET, now=now)
    assert not verify_session(s, sign_session(s, "wrong-secret"), SECRET, now=now)
    assert not verify_session(session, sig, "wrong-secret", now=now)
    assert not verify_session(session, "", SECRET, now=now)
    assert not verify_session(session, None, SECRET, now=now)


def test_2_expired_session_rejected(signed):
    session, sig, now = signed
    assert verify_session(session, sig, SECRET, now=now + timedelta(minutes=29))
    assert not verify_session(session, sig, SECRET, now=now + timedelta(minutes=30))
    with pytest.raises(SessionError, match="expired"):
        check_session(session, sig, SECRET, now=now + timedelta(hours=2))


def test_2_expired_login_flagged_preflight(env):
    env.as_user("u_jordan")
    env.clock.advance(minutes=31)
    run = env.request("65W USB-C charger for my XPS 13")
    assert run["status"] == "flagged"
    assert "expired" in run["reason"]
    assert env.agent.calls == []


def test_real_agent_requires_secret(tmp_path):
    from proxy.service import Settings
    with pytest.raises(RuntimeError):
        Proxy(Settings(agent_url="http://agent.test", shared_secret="", var_dir=tmp_path))
