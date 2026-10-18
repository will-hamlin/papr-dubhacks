"""Offline demo regressions for incomplete requirements and wrong-product evidence."""
import asyncio
import json

import pytest

from main_service.candidates import Candidate
from main_service.listing_fetch import ListingPage
from main_service.models import Constraint
from main_service.proof import build_search, compile_constraints
from main_service.spec import DEFAULT_WEIGHTS, RuleSpecParser
from main_service.verification import ListingVerifier, product_identity


LIMITS = {'currency': 'USD', 'max_total_cents': 200000, 'tax_rate_bp': 0,
          'approved_suppliers': ['sup_01'], 'freight_cents_by_supplier': {'sup_01': 0},
          'blocked_categories': [], 'blocked_keywords': {}}


def prepare(text):
    return build_search(RuleSpecParser().parse_sync(text), LIMITS, DEFAULT_WEIGHTS)


def verify_laptop(name='Demo laptop', ram=32, request='laptop with 32GB RAM'):
    product = {'@type': 'Product', 'name': name, 'sku': 'DEMO', 'category': 'electronics',
               'offers': {'@type': 'Offer', 'price': '500.00', 'priceCurrency': 'USD'}}
    if ram is not None:
        product['additionalProperty'] = [{'name': 'ram', 'value': ram, 'unitText': 'GB'}]
    class Evidence:
        async def fetch(self, url):
            return ListingPage(url, json.dumps(product).encode())
    candidate = Candidate.model_validate({'candidate_id': 'demo', 'url': 'https://supplier.example/item',
        'sku': 'DEMO', 'claims': [{'field': 'name', 'value': name}, {'field': 'price_cents', 'value': 50000}]})
    compiled = prepare(request)
    assert not compiled.errors
    return asyncio.run(ListingVerifier(Evidence(), {'supplier.example': 'sup_01'}).verify(
        candidate, compiled.specs, compiled.limits))


def test_constraint_overflow_is_an_error_even_when_the_omitted_constraint_is_last():
    constraints = [Constraint(field=f'attribute_{i}', op='eq', value='present', required=True) for i in range(21)]
    compiled = compile_constraints(constraints)
    assert compiled.errors and '21 constraints' in compiled.errors[0]
    proposal = RuleSpecParser().parse_sync('laptop')
    proposal.constraints = constraints
    assert build_search(proposal, LIMITS, DEFAULT_WEIGHTS).errors
    assert not compile_constraints(constraints[:20]).errors


def test_overflow_stops_search_instead_of_sending_a_weakened_request(make_env):
    class TooManyRequirements:
        name = 'fixture'
        async def parse(self, text):
            proposal = RuleSpecParser().parse_sync('laptop')
            proposal.constraints = [Constraint(field=f'p{i}', op='eq', value='yes', required=True) for i in range(21)]
            return proposal
    env = make_env(parser=TooManyRequirements())
    status, result = env.order('laptop')
    assert status == 422 and result['decision'] == 'unclear_request'
    assert env.engine.received == []


@pytest.mark.parametrize('request_text,op', [
    ('laptop with 32GB RAM', 'ge'), ('laptop with at least 32 GB memory', 'ge'),
    ('laptop with exactly 32GB RAM', 'eq'), ('laptop with RAM at most 32GB', 'le'),
])
def test_rules_parser_preserves_ram_requirement_and_bound(request_text, op):
    compiled = prepare(request_text)
    assert not compiled.errors
    assert compiled.specs['constraints'] == [
        {'field': 'ram', 'op': op, 'value': 32000, 'unit': 'MB', 'required': True}]


@pytest.mark.parametrize('request_text', [
    'waterproof laptop', 'laptop with 1TB SSD', 'Dell laptop', 'wireless keyboard',
    'charger under 65W', 'charger with two ports', 'new and used laptop',
    'laptop without a webcam', 'USB-C charger and a laptop',
])
def test_rules_parser_reports_unrepresented_requirements(request_text):
    proposal = RuleSpecParser().parse_sync(request_text)
    assert proposal.unsupported_requirements
    compiled = build_search(proposal, LIMITS, DEFAULT_WEIGHTS)
    assert compiled.errors
    assert compiled.specs['unsupported_requirements'] == proposal.unsupported_requirements


def test_unsupported_rule_requirement_stops_main_service(make_env):
    env = make_env()
    status, result = env.order('waterproof laptop with 32GB RAM')
    assert status == 422
    assert 'unsupported request requirement' in result['reason']
    assert env.engine.received == []


def test_demo_charger_and_simple_noun_remain_usable():
    compiled = prepare('Please find a new 65W USB-C charger under $40')
    assert not compiled.errors
    assert compiled.specs['item'] == 'charger'
    assert compiled.limits['max_total_cents'] == 4000
    assert not prepare('stapler').errors
    assert not prepare('65W USB-C charger for my XPS 13').errors


@pytest.mark.parametrize('name,status', [
    ('Demo laptop', 'supported'), ('Demo notebook computer', 'supported'),
    ('Stapler', 'contradicted'), ('Laptop stand', 'contradicted'),
    ('Replacement laptop sleeve', 'contradicted'), ('USB-C charger for laptops', 'contradicted'),
    ('Laptop battery', 'contradicted'), ('Laptop backpack', 'contradicted'), ('Laptop bag', 'contradicted'),
    ('Laptop screen', 'contradicted'),
    ('Acme Pro 32', 'unverified'), ('Laptop and monitor bundle', 'unverified'),
])
def test_published_claims_cannot_substitute_an_unrelated_or_ambiguous_product(name, status):
    report = verify_laptop(name=name)
    # Every listing advertises the submitted name and price, even the wrong product.
    assert report['claims_status'] == 'supported'
    assert report['requirements_status'] == status
    assert report['purchase_authorized'] is False
    identity = next(check for check in report['requirement_checks'] if check['field'] == 'product_identity')
    assert identity['status'] == status


@pytest.mark.parametrize('ram,status', [(32, 'supported'), (64, 'supported'), (16, 'contradicted'), (None, 'unverified')])
def test_ram_evidence_is_required_independently_of_truthful_price_claims(ram, status):
    report = verify_laptop(ram=ram)
    assert report['claims_status'] == 'supported'
    assert report['requirements_status'] == status
    assert report['purchase_authorized'] is False


def test_zero_constraints_do_not_allow_price_only_stapler_to_meet_laptop_request():
    report = verify_laptop(name='Stapler', ram=None, request='laptop')
    assert report['claims_status'] == 'supported'
    assert report['requirements_status'] == 'contradicted'


def test_unknown_item_types_or_missing_identity_never_pass():
    assert product_identity({'item': 'equipment'}, {'name': {'value': 'Equipment', 'unit': None}})['status'] == 'unverified'
    assert product_identity({'item': 'laptop'}, {})['status'] == 'unverified'
    assert product_identity({'item': 'Dell laptop'}, {'name': {'value': 'HP laptop', 'unit': None}})['status'] == 'unverified'
    assert product_identity({'item': 'monitor'}, {'name': {'value': 'Monitor arm', 'unit': None}})['status'] == 'contradicted'
