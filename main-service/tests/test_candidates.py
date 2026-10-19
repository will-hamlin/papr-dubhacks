import asyncio
import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from main_service.app import create_app
from main_service.candidates import Candidate, CandidateSubmission
from main_service.engine import StubEngine
from main_service.listing_fetch import EvidenceError, ListingFetcher, ListingPage
from main_service.service import MainService, Settings
from main_service.signing import sign_payload
from main_service.spec import RuleSpecParser
from main_service.store import ConflictError, RequestStore
from main_service.verification import ListingVerifier
from .conftest import SECRET, handoff


def product_page(power='65', unit='W', price='25.00'):
    product = {'@type': 'Product', 'name': 'USB-C charger', 'sku': 'CH-65',
               'category': 'computer_accessories', 'itemCondition': 'https://schema.org/NewCondition',
               'additionalProperty': [{'name': 'power', 'value': power, 'unitText': unit},
                                      {'name': 'connector', 'value': 'USB-C'}],
               'offers': {'@type': 'Offer', 'price': price, 'priceCurrency': 'USD'}}
    return ('<html><script type="application/ld+json">' + json.dumps(product) + '</script></html>').encode()


class Pages:
    def __init__(self, body=None):
        self.body = body if body is not None else product_page()
        self.calls = []

    async def fetch(self, url):
        self.calls.append(url)
        return ListingPage(url, self.body)


def candidate(**overrides):
    return {'candidate_id': 'charger', 'url': 'https://supplier.example/charger', 'sku': 'CH-65',
            'claims': [{'field': 'power', 'value': 65, 'unit': 'W'},
                       {'field': 'price_cents', 'value': 2500}], **overrides}


def prepared(tmp_path, pages=None):
    pages = pages or Pages()
    verifier = ListingVerifier(pages, {'supplier.example': 'sup_01'})
    engine = StubEngine()
    service = MainService(Settings(shared_secret=SECRET, database=tmp_path / 'ms.sqlite3'),
                          RuleSpecParser(), engine, verifier)
    payload = handoff('65W USB-C charger under $40')
    payload['request']['search_mode'] = 'agent'
    payload = sign_payload(payload, SECRET)
    service.receive(payload)
    asyncio.run(service.process_next())
    return service, payload['order_id'], pages, engine


def submission(service, order_id, candidates=None):
    return {'submission_id': 'batch-1', 'requirements_id': service.store.get(order_id)['result']['requirements_id'],
            'candidates': candidates or [candidate()]}


def test_agent_request_prepares_requirements_without_running_search(tmp_path):
    service, order_id, pages, engine = prepared(tmp_path)
    record = service.store.get(order_id)
    assert record['status'] == 'awaiting_candidates'
    assert record['result']['limits']['max_total_cents'] == 4000
    assert len(record['result']['requirements_id']) == 64
    assert engine.received == [] and pages.calls == []


def test_listing_claims_and_constraints_use_fresh_ms_evidence(tmp_path):
    service, order_id, pages, engine = prepared(tmp_path)
    service.submit_candidates(order_id, submission(service, order_id))
    assert service.store.get(order_id)['status'] == 'candidates_queued'
    assert pages.calls == []
    asyncio.run(service.process_next())
    record = service.store.get(order_id)
    report = record['result']['verification']['candidates'][0]
    assert record['status'] == 'verification_complete'
    assert report['claims_status'] == report['requirements_status'] == 'supported'
    assert report['evidence']['url'] == candidate()['url']
    assert len(report['evidence']['sha256']) == 64
    assert report['purchase_authorized'] is False
    assert pages.calls == [candidate()['url']] and engine.received == []
    assert RequestStore(service.settings.database).get(order_id)['result']['verification'] == record['result']['verification']


@pytest.mark.parametrize('body,claims_status,requirements_status', [
    (product_page(power='45'), 'contradicted', 'contradicted'),
    (product_page(price='50.00'), 'contradicted', 'contradicted'),
    (product_page(unit='unknown'), 'unverified', 'unverified'),
    (b'<html>Agent says this is a verified 65W charger.</html>', 'unverified', 'unverified'),
])
def test_false_or_unsupported_evidence_never_passes(tmp_path, body, claims_status, requirements_status):
    service, order_id, _, _ = prepared(tmp_path, Pages(body))
    service.submit_candidates(order_id, submission(service, order_id))
    asyncio.run(service.process_next())
    report = service.store.get(order_id)['result']['verification']['candidates'][0]
    assert report['claims_status'] == claims_status
    assert report['requirements_status'] == requirements_status


def test_claim_and_requirement_results_remain_distinct(tmp_path):
    service, order_id, _, _ = prepared(tmp_path, Pages(product_page(power='45')))
    proposed = candidate(claims=[{'field': 'power', 'value': 45, 'unit': 'W'}])
    service.submit_candidates(order_id, submission(service, order_id, [proposed]))
    asyncio.run(service.process_next())
    report = service.store.get(order_id)['result']['verification']['candidates'][0]
    assert report['claims_status'] == 'supported'  # The listing really advertises 45W.
    assert report['requirements_status'] == 'contradicted'  # The request needs at least 65W.


def test_candidate_replay_conflict_requirements_binding_and_batch_history(tmp_path):
    service, order_id, pages, _ = prepared(tmp_path)
    body = submission(service, order_id)
    with pytest.raises(ConflictError, match='requirements'):
        service.submit_candidates(order_id, {**body, 'requirements_id': '0' * 64})
    service.submit_candidates(order_id, body)
    assert service.submit_candidates(order_id, body)['duplicate']
    with pytest.raises(ConflictError):
        service.submit_candidates(order_id, {**body, 'submission_id': 'other'})
    asyncio.run(service.process_next())
    assert service.submit_candidates(order_id, body)['duplicate']
    assert not asyncio.run(service.process_next())
    assert len(pages.calls) == 1
    changed = copy.deepcopy(body)
    changed['candidates'][0]['claims'][0]['value'] = 100
    with pytest.raises(ConflictError):
        service.submit_candidates(order_id, changed)
    service.submit_candidates(order_id, {**changed, 'submission_id': 'batch-2'})
    asyncio.run(service.process_next())
    with service.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM candidate_submissions WHERE result IS NOT NULL').fetchone()[0] == 2


def test_denied_and_managed_requests_cannot_accept_agent_candidates(tmp_path):
    service, order_id, _, _ = prepared(tmp_path)
    for accepted in (True, False):
        payload = handoff(accepted=accepted)
        service.receive(payload)
        with pytest.raises(ConflictError):
            service.submit_candidates(payload['order_id'], submission(service, order_id))


@pytest.mark.parametrize('change', [
    {'url': 'http://supplier.example/charger'}, {'url': 'https://user:secret@supplier.example/'},
    {'url': 'https://supplier.example:8443/'}, {'verified': True}, {'claims': []},
    {'claims': [{'field': 'power', 'value': True}]},
    {'claims': [{'field': 'power', 'value': 65, 'unit': 'W', 'evidence': 'trust me'}]},
])
def test_candidate_contract_rejects_unsafe_or_self_verified_payloads(change):
    with pytest.raises(ValidationError):
        Candidate.model_validate(candidate(**change))


def test_managed_search_and_personal_agent_use_same_claim_checker(tmp_path):
    pages = Pages(product_page(power='45'))
    class Search(StubEngine):
        name = 'http'
        async def search(self, payload):
            return {'status': 'verified', 'candidates': [{**candidate(), 'proved': True}]}
    verifier = ListingVerifier(pages, {'supplier.example': 'sup_01'})
    managed = MainService(Settings(shared_secret=SECRET, database=tmp_path / 'managed.sqlite3'),
                          RuleSpecParser(), Search(), verifier)
    payload = handoff('65W USB-C charger under $40')
    managed.receive(payload)
    asyncio.run(managed.process_next())
    managed_report = managed.store.get(payload['order_id'])['result']['verification']['candidates'][0]
    agent, order_id, _, _ = prepared(tmp_path, pages)
    agent.submit_candidates(order_id, submission(agent, order_id))
    asyncio.run(agent.process_next())
    agent_report = agent.store.get(order_id)['result']['verification']['candidates'][0]
    assert managed_report['claim_checks'] == agent_report['claim_checks']
    assert managed_report['requirements_status'] == agent_report['requirements_status'] == 'contradicted'
    assert len(pages.calls) == 2  # Backend's proved=True never bypasses independent fetching.


def test_internal_candidate_endpoint_requires_proxy_signature(tmp_path):
    app = create_app(Settings(shared_secret=SECRET, database=tmp_path / 'api.sqlite3'),
                     RuleSpecParser(), StubEngine(), ListingVerifier(Pages()))
    service = app.state.service
    payload = handoff()
    payload['request']['search_mode'] = 'agent'
    payload = sign_payload(payload, SECRET)
    service.receive(payload)
    asyncio.run(service.process_next())
    order_id = payload['order_id']
    client = TestClient(app)
    route = f'/requests/{order_id}/candidates'
    body = {'order_id': order_id, 'submission': submission(service, order_id)}
    assert client.post(route, json=body).status_code == 401
    assert client.post(route, json=sign_payload(body, SECRET)).status_code == 202
    assert client.post('/requests/wrong/candidates', json=sign_payload(body, SECRET)).status_code == 400


@pytest.mark.parametrize('address', ['127.0.0.1', '10.1.2.3', '169.254.169.254', '::1', '192.168.1.1', '0.0.0.0'])
def test_fetcher_rejects_nonpublic_dns_results(address):
    async def resolve(host):
        return [address]
    fetcher = ListingFetcher(resolver=resolve)
    with pytest.raises(EvidenceError, match='non-public'):
        asyncio.run(fetcher.fetch('https://supplier.example/'))


def test_fetcher_pins_address_and_rechecks_redirects():
    seen = []
    async def resolve(host):
        return ['127.0.0.1'] if host == 'internal.example' else ['93.184.216.34']
    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={'location': 'https://internal.example/secret'})
    fetcher = ListingFetcher(resolver=resolve, transport=httpx.MockTransport(handler))
    with pytest.raises(EvidenceError, match='non-public'):
        asyncio.run(fetcher.fetch('https://supplier.example/item'))
    assert len(seen) == 1
    assert seen[0].url.host == '93.184.216.34'
    assert seen[0].headers['host'] == 'supplier.example'
    assert seen[0].extensions['sni_hostname'] == 'supplier.example'


def test_fetcher_reads_bounded_public_listing_without_cookies():
    async def resolve(host):
        return ['93.184.216.34']
    def handler(request):
        assert 'authorization' not in request.headers and 'cookie' not in request.headers
        return httpx.Response(200, headers={'content-type': 'text/html'}, content=product_page())
    fetcher = ListingFetcher(resolver=resolve, transport=httpx.MockTransport(handler))
    assert asyncio.run(fetcher.fetch('https://supplier.example/')).body == product_page()
    large = ListingFetcher(resolver=resolve, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, headers={'content-type': 'text/html'}, content=b'x' * 1_000_001)))
    with pytest.raises(EvidenceError, match='size limit'):
        asyncio.run(large.fetch('https://supplier.example/'))


def test_missing_variant_is_unverified(tmp_path):
    service, order_id, _, _ = prepared(tmp_path)
    service.submit_candidates(order_id, submission(service, order_id, [candidate(sku='DIFFERENT')]))
    asyncio.run(service.process_next())
    report = service.store.get(order_id)['result']['verification']['candidates'][0]
    assert report['claims_status'] == 'unverified' and 'variant' in report['reason']


def test_multiple_offers_conflicting_facts_and_unknown_supplier_are_unverified(tmp_path):
    from main_service.verification import extract_facts
    product = {'@type': 'Product', 'sku': 'CH-65',
               'additionalProperty': [{'name': 'power', 'value': '65', 'unitText': 'W'},
                                      {'name': 'power', 'value': '45', 'unitText': 'W'}],
               'offers': [{'@type': 'Offer', 'price': '25.00', 'priceCurrency': 'USD'},
                          {'@type': 'Offer', 'price': '30.00', 'priceCurrency': 'USD'}]}
    facts = extract_facts(json.dumps(product).encode(), 'CH-65')
    assert facts['power'] is None and 'price_cents' not in facts
    service, order_id, _, _ = prepared(tmp_path)
    service.verifier.supplier_hosts = {}
    service.submit_candidates(order_id, submission(service, order_id))
    asyncio.run(service.process_next())
    report = service.store.get(order_id)['result']['verification']['candidates'][0]
    assert report['claims_status'] == 'supported' and report['requirements_status'] == 'unverified'


def test_quantity_tax_and_freight_are_included_in_the_budget_check(tmp_path):
    service, order_id, _, _ = prepared(tmp_path)
    record = service.store.get(order_id)
    record['result']['specs']['quantity'] = 2
    record['result']['limits']['freight_cents_by_supplier']['sup_01'] = 100
    report = asyncio.run(service.verifier.verify(Candidate.model_validate(candidate()),
                         record['result']['specs'], record['result']['limits']))
    total = next(check for check in report['requirement_checks'] if check['field'] == 'max_total_cents')
    assert total['observed'] == 5613 and total['status'] == 'contradicted'


def test_units_are_normalized_using_exact_measurements(tmp_path):
    pages = Pages(product_page())
    service, order_id, _, _ = prepared(tmp_path, pages)
    proposed = candidate(claims=[{'field': 'power', 'value': '65.0', 'unit': 'W'}])
    service.submit_candidates(order_id, submission(service, order_id, [proposed]))
    asyncio.run(service.process_next())
    assert service.store.get(order_id)['result']['verification']['candidates'][0]['claims_status'] == 'supported'


def test_expired_price_and_malformed_schema_do_not_establish_facts():
    from main_service.verification import extract_facts
    product = {'@type': 'Product', 'sku': 'CH-65', 'offers': {
        '@type': 'Offer', 'price': '25.00', 'priceCurrency': 'USD', 'priceValidUntil': '2000-01-01'}}
    assert 'price_cents' not in extract_facts(json.dumps(product).encode(), 'CH-65')
    with pytest.raises(EvidenceError):
        extract_facts(b'{"@type":null}', None)


def test_new_batch_refetches_instead_of_reusing_an_old_supported_claim(tmp_path):
    service, order_id, pages, _ = prepared(tmp_path)
    batch = submission(service, order_id)
    service.submit_candidates(order_id, batch)
    asyncio.run(service.process_next())
    pages.body = product_page(power='30')
    service.submit_candidates(order_id, {**batch, 'submission_id': 'fresh-batch'})
    asyncio.run(service.process_next())
    report = service.store.get(order_id)['result']['verification']['candidates'][0]
    assert report['claims_status'] == 'contradicted' and len(pages.calls) == 2
