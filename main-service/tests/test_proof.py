"""Spec and proof regression tests moved with their implementation into MS."""
import asyncio
import json
import httpx
import pytest
from main_service.engine import HttpEngine
from main_service.models import Constraint, SpecProposal, Weight
from main_service.signing import verify_payload
from main_service.spec import ClaudeSpecParser, FallbackSpecParser, ParseError, RuleSpecParser, money_to_cents

SECRET = "test-secret"
CHARGER = "65W USB-C charger for my XPS 13"

class FixedParser:
    """Stands in for Claude: returns a fixed proposal, or raises."""
    name = "claude"

    def __init__(self, proposal=None, error=None):
        self.proposal, self.error, self.calls = proposal, error, 0

    async def parse(self, text):
        self.calls += 1
        if self.error:
            raise ParseError(self.error)
        return self.proposal


def proposal(**kw):
    base = dict(understood=True, item="usb-c charger", category="computer_accessories", quantity=1,
                condition="unspecified",
                constraints=[Constraint(field="power", op="ge", value="65", unit="W", required=True)],
                weights=[Weight(criterion="price", weight=50), Weight(criterion="compatibility", weight=50)],
                stated_budget_cents=None)
    return SpecProposal(**{**base, **kw})


class _Resp:
    def __init__(self, stop_reason, parsed):
        self.stop_reason, self.parsed_output = stop_reason, parsed


class _FakeAnthropic:
    def __init__(self, resp):
        self.kwargs = None
        outer = self

        class Messages:
            async def parse(self, **kw):
                outer.kwargs = kw
                return resp

        self.messages = Messages()


def _with(*cons):
    return proposal(constraints=list(cons))


def test_money_parsing_is_integer():
    assert money_to_cents("up to $1,249.50 please") == 124950
    assert money_to_cents("$64") == 6400
    assert money_to_cents("no money here") is None


def test_weights_normalized_to_integers_summing_to_100(make_env):
    p = proposal(weights=[Weight(criterion="price", weight=1), Weight(criterion="quality", weight=1),
                          Weight(criterion="warranty", weight=1), Weight(criterion="price", weight=0)])
    env = make_env(parser=FixedParser(p))
    _, body = env.order(CHARGER)
    assert body["weights"] == {"price": 34, "quality": 33, "warranty": 33}


def test_zero_weights_fall_back_to_defaults(make_env):
    env = make_env(parser=FixedParser(proposal(weights=[Weight(criterion="price", weight=0)])))
    _, body = env.order(CHARGER)
    assert sum(body["weights"].values()) == 100 and len(body["weights"]) > 1


def test_claude_failure_falls_back_to_rules(make_env):
    env = make_env(parser=FallbackSpecParser(FixedParser(error="Claude unreachable"), RuleSpecParser()))
    status, body = env.order(CHARGER)
    assert status == 200 and body["parser"] == "rules"
    assert any("Claude unavailable" in n for n in body["notes"])


def test_claude_proposal_used_when_available(make_env):
    env = make_env(parser=FallbackSpecParser(FixedParser(proposal()), RuleSpecParser()))
    _, body = env.order(CHARGER)
    assert body["parser"] == "claude"
    assert body["weights"] == {"compatibility": 50, "price": 50}


def test_claude_parser_request_shape_and_refusal():
    fake = _FakeAnthropic(_Resp("end_turn", proposal()))
    out = asyncio.run(ClaudeSpecParser(client=fake).parse("<b>hi</b>"))
    assert out.item == "usb-c charger"
    kw = fake.kwargs
    assert kw["model"] == "claude-opus-5-5" and kw["output_format"] is SpecProposal
    assert "fallbacks" not in kw and "betas" not in kw
    assert "<request>" in kw["messages"][0]["content"]

    with pytest.raises(ParseError):
        asyncio.run(ClaudeSpecParser(client=_FakeAnthropic(_Resp("refusal", None))).parse("x"))


def test_http_engine_receives_signed_payload(make_env):
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"candidates": [{"sku": "CE-65W-PD", "proved": True}]})

    env = make_env(engine=HttpEngine("http://engine.test", "/search", transport=httpx.MockTransport(handler)))
    status, body = env.order(CHARGER)
    assert status == 200 and body["engine"] == {"candidates": [{"sku": "CE-65W-PD", "proved": True}]}
    path, payload = seen[0]
    assert path == "/search" and verify_payload(payload, SECRET)


def test_units_normalized_to_integers_rounding_toward_the_user(make_env):
    env = make_env(parser=FixedParser(_with(
        Constraint(field="screen size", op="ge", value="15.6", unit="in", required=True),
        Constraint(field="weight", op="le", value="1.5", unit="kg", required=False),
        Constraint(field="RAM", op="ge", value="32", unit="GB", required=True))))
    _, body = env.order("laptop")
    assert body["specs"]["constraints"] == [
        {"field": "screen_size", "op": "ge", "value": 397, "unit": "mm", "required": True},   # 396.24 -> 397
        {"field": "weight", "op": "le", "value": 1500, "unit": "g", "required": False},
        {"field": "ram", "op": "ge", "value": 32000, "unit": "MB", "required": True}]
    assert all(type(c["value"]) is int for c in body["specs"]["constraints"])


def test_contradictory_numeric_constraints_rejected(make_env):
    env = make_env(parser=FixedParser(_with(
        Constraint(field="length", op="ge", value="300", unit="mm", required=True),
        Constraint(field="length", op="le", value="29", unit="cm", required=True))))
    status, body = env.order("cable")
    assert (status, body["decision"]) == (422, "unclear_request") and "contradictory" in body["reason"]
    assert env.engine.received == []


def test_unreadable_required_value_rejected_optional_dropped(make_env):
    env = make_env(parser=FixedParser(_with(Constraint(field="power", op="ge", value="lots", unit="W", required=True))))
    status, body = env.order("charger")
    assert status == 422 and "could not read" in body["reason"]
    env = make_env(parser=FixedParser(_with(Constraint(field="power", op="ge", value="lots", unit="W", required=False))))
    status, body = env.order("charger")
    assert status == 200 and body["specs"]["constraints"] == []
    assert any("could not read" in n for n in body["notes"])


def test_condition_passed_through(env):
    _, body = env.order("refurbished laptop")
    assert body["specs"]["condition"] == "refurbished"
    _, body = env.order(CHARGER)
    assert body["specs"]["condition"] == "unspecified"


def test_lower_stated_budget_tightens_search(env):
    _, body = env.order("USB-C charger for my XPS 13, under $40")
    assert body["limits"]["max_total_cents"] == 4000


def test_blocked_category_from_parser_alone(make_env):
    env = make_env(parser=FixedParser(proposal(item="multitool blade", category="weapons")))
    status, body = env.order("something sharp for opening boxes")
    assert (status, body["decision"]) == (403, "violates_company_policy")


def test_quantity_out_of_range_violates_policy(make_env):
    env = make_env(parser=FixedParser(proposal(quantity=5000)))
    status, body = env.order("5000 chargers")
    assert status == 403 and "quantity" in body["reason"]


def test_unclear_request(make_env):
    env = make_env(parser=FixedParser(proposal(understood=False, unclear_reason="not a purchase", item="")))
    status, body = env.order("what's the weather")
    assert (status, body["decision"]) == (422, "unclear_request")
