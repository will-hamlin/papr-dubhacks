import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from main_service.app import create_app
from main_service.engine import HttpEngine, StubEngine
from main_service.service import MainService, Settings
from main_service.signing import sign_payload
from main_service.spec import RuleSpecParser
from main_service.store import ConflictError, RequestStore
from .conftest import SECRET, handoff


class CountingParser(RuleSpecParser):
    def __init__(self):
        self.calls = 0

    async def parse(self, text):
        self.calls += 1
        return await super().parse(text)


def test_denial_persists_and_never_runs_parser_or_search(tmp_path):
    parser, engine = CountingParser(), StubEngine()
    settings = Settings(shared_secret=SECRET, database=tmp_path / 'requests.sqlite3')
    service = MainService(settings, parser, engine)
    payload = handoff(accepted=False)
    receipt = service.receive(payload)
    assert receipt['status'] == 'rejected' and receipt['documented']
    assert asyncio.run(service.process_next()) is False
    assert parser.calls == 0 and engine.received == []
    restored = RequestStore(settings.database).get(payload['order_id'])
    assert restored['handoff'] == payload and restored['result'] == {}


def test_accepted_handoff_durable_before_processing_and_idempotent(tmp_path):
    parser, engine = CountingParser(), StubEngine()
    service = MainService(Settings(shared_secret=SECRET, database=tmp_path / 'requests.sqlite3'), parser, engine)
    payload = handoff('65W USB-C charger under $40')
    assert service.receive(payload)['status'] == 'queued'
    assert parser.calls == 0
    service.receive(payload)
    asyncio.run(service.process_next())
    assert not asyncio.run(service.process_next())
    assert parser.calls == 1 and len(engine.received) == 1
    stored = service.store.get(payload['order_id'])
    assert stored['status'] == 'not_searched'
    assert stored['result']['specs']['constraints'][0]['value'] == 65
    assert stored['result']['limits']['max_total_cents'] == 4000
    assert stored['result']['engine']['status'] == 'not_searched'
    assert service.receive(payload)['status'] == 'not_searched'
    assert len(engine.received) == 1
    changed = sign_payload({**payload, 'request': {'text': 'different'}}, SECRET)
    with pytest.raises(ConflictError):
        service.receive(changed)


def test_engine_failure_is_stored_without_changing_authorization(tmp_path):
    engine = HttpEngine('http://engine.test', transport=httpx.MockTransport(lambda r: httpx.Response(502)))
    service = MainService(Settings(shared_secret=SECRET, database=tmp_path / 'requests.sqlite3'), RuleSpecParser(), engine)
    payload = handoff()
    service.receive(payload)
    asyncio.run(service.process_next())
    record = service.store.get(payload['order_id'])
    assert record['status'] == 'interrupted'
    assert record['result']['processing_stage'] == 'submitting_backend'
    assert record['handoff']['authorization']['accepted'] is True
    assert record['result']['decision'] == 'processing_error'
    assert '502' in record['result']['reason']
    asyncio.run(engine.aclose())


def test_internal_endpoint_checks_signature_and_result_access(tmp_path):
    app = create_app(Settings(shared_secret=SECRET, database=tmp_path / 'requests.sqlite3'), RuleSpecParser(), StubEngine())
    client = TestClient(app)
    payload = handoff(accepted=False)
    assert client.post('/handoffs', json={**payload, 'proxy_sig': 'bad'}).status_code == 401
    assert client.post('/handoffs', json=payload).json()['status'] == 'rejected'
    route = '/requests/' + payload['order_id']
    assert client.get(route).status_code == 401
    assert client.get(route, headers={'Authorization': 'Bearer ' + SECRET}).json()['handoff'] == payload


def test_completed_verifier_output_is_saved(tmp_path):
    class Backend(StubEngine):
        name = 'agent_v1'
        async def search(self, payload):
            self.received.append(payload)
            return {'request_id': 'req_1', 'status': 'verifying'}
        async def status(self, request_id):
            assert request_id == 'req_1'
            return {'status': 'verified', 'report': {'passed': True, 'evidence': ['proof-1']}}
    service = MainService(Settings(shared_secret=SECRET, database=tmp_path / 'requests.sqlite3'), RuleSpecParser(), Backend())
    payload = handoff()
    service.receive(payload)
    asyncio.run(service.process_next())
    assert service.store.get(payload['order_id'])['status'] == 'submitted'
    asyncio.run(service.refresh_results())
    record = service.store.get(payload['order_id'])
    assert record['status'] == 'completed'
    assert record['result']['engine']['report']['evidence'] == ['proof-1']


def test_interrupted_processing_is_not_silently_repeated(tmp_path):
    store = RequestStore(tmp_path / 'requests.sqlite3')
    payload = handoff()
    store.receive(payload)
    store.save(payload['order_id'], 'processing', {'specs': {'item': 'charger'}})
    store.recover()
    assert store.get(payload['order_id'])['status'] == 'interrupted'
    assert store.next_queued() is None
