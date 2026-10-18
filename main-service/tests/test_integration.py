"""Exercise the proxy-to-MS HTTP boundary and the independently owned processing stages."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from main_service.app import create_app
from main_service.engine import StubEngine
from main_service.service import Settings as MSSettings
from main_service.spec import RuleSpecParser
from proxy.handoff import MainServiceClient
from proxy.service import Proxy, Settings
from proxy.signing import make_auth


def test_personal_agent_flow_through_proxy_keeps_ms_credentials_private(tmp_path):
    from fastapi.testclient import TestClient
    from proxy.app import create_app as create_proxy
    from main_service.verification import ListingVerifier
    from .test_candidates import Pages, candidate

    secret = 'integration-secret'
    pages = Pages()
    engine = StubEngine()
    ms_app = create_app(MSSettings(shared_secret=secret, database=tmp_path / 'ms.sqlite3'),
                        RuleSpecParser(), engine, ListingVerifier(pages, {'supplier.example': 'sup_01'}))
    ms = ms_app.state.service
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    bridge = MainServiceClient('http://ms.test', transport=httpx.ASGITransport(app=ms_app))
    proxy_app = create_proxy(Settings(shared_secret=secret, var_dir=tmp_path / 'proxy'), bridge, clock=lambda: now)
    client = TestClient(proxy_app)
    request = {'auth': make_auth('u_jordan', secret, now=now),
               'request_text': '65W USB-C charger under $40', 'search_mode': 'agent'}
    response = client.post('/orders', json=request)
    assert response.status_code == 200
    result = response.json()
    order_id = result['order_id']
    token = result['request_token']
    assert secret not in token
    assert all('request_token' not in row.get('response', {}).get('body', {}) for row in proxy_app.state.proxy.audit.entries())
    assert client.get(f'/orders/{order_id}').status_code == 401
    assert client.get('/orders/another', headers={'Authorization': 'Bearer ' + token}).status_code == 401
    asyncio.run(ms.process_next())
    headers = {'Authorization': 'Bearer ' + token}
    status = client.get(f'/orders/{order_id}', headers=headers).json()
    assert status['status'] == 'awaiting_candidates' and 'handoff' not in status
    assert engine.received == []
    batch = {'submission_id': 'agent-batch', 'requirements_id': status['result']['requirements_id'],
             'candidates': [candidate()]}
    route = f'/orders/{order_id}/candidates'
    assert client.post(route, json=batch).status_code == 401
    assert client.post(route, headers=headers, json=batch).status_code == 202
    asyncio.run(ms.process_next())
    output = client.get(f'/orders/{order_id}', headers=headers).json()
    assert output['status'] == 'verification_complete'
    assert output['result']['verification']['candidates'][0]['claims_status'] == 'supported'
    assert client.post(route, headers=headers, json=batch).json()['duplicate'] is True
    assert not asyncio.run(ms.process_next()) and len(pages.calls) == 1
    asyncio.run(bridge.aclose())


def test_api_authorization_handoff_processing_and_database(tmp_path):
    secret = 'integration-secret'
    engine = StubEngine()
    ms_app = create_app(MSSettings(shared_secret=secret, database=tmp_path / 'ms' / 'requests.sqlite3'),
                        RuleSpecParser(), engine)
    ms = ms_app.state.service
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    async def run():
        client = MainServiceClient('http://ms.test', transport=httpx.ASGITransport(app=ms_app))
        proxy = Proxy(Settings(shared_secret=secret, var_dir=tmp_path / 'proxy', allow_legacy_config=True),
                      main_service=client, clock=lambda: now)
        auth = make_auth('u_jordan', secret, now=now)
        accepted = await proxy.handle_order({'auth': auth, 'request_text': '65W USB-C charger under $40'})
        rejected = await proxy.handle_order({'auth': auth, 'request_text': 'buy a gift card'})
        malformed = await proxy.handle_order({'request': {'text': 'charger'}, 'userConfig': None, 'companyConfig': []})
        assert accepted.status == 200 and accepted.body['main_service']['status'] == 'queued'
        assert rejected.status == 403 and rejected.body['main_service']['status'] == 'rejected'
        assert malformed.status == 400 and malformed.body['main_service']['status'] == 'rejected'
        assert engine.received == []
        assert ms.store.get(rejected.body['order_id'])['handoff']['authorization']['reason']
        assert await ms.process_next()
        assert not await ms.process_next()
        stored = ms.store.get(accepted.body['order_id'])
        assert stored['result']['limits']['max_total_cents'] == 4000
        assert len(engine.received) == 1
        assert 'specs' not in accepted.body
        assert proxy.outbox.pending() == []
        await client.aclose()
    asyncio.run(run())
