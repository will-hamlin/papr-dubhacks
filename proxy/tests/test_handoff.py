import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from proxy.app import create_app
from proxy.handoff import HandoffError, MainServiceClient
from proxy.signing import verify_payload
from .conftest import ALEX, NORTHSTAR, SECRET


def test_proxy_compiles_context_without_product_specs(env):
    user = {**ALEX, 'customUserField': 'retained'}
    company = {**NORTHSTAR, 'customOrgField': {'region': 'west'}}
    status, response = env.dashboard('65W USB-C charger under $40', user=user, company=company)
    assert status == 200 and response['main_service']['status'] == 'queued'
    sent = env.main_service.received[0]
    assert verify_payload(sent, SECRET)
    assert sent['user'] == user and sent['organization'] == company
    assert sent['request']['text'] == '65W USB-C charger under $40'
    assert sent['limits']['max_total_cents'] == 500000
    assert sent['authorization']['accepted'] is True
    for key in ('specs', 'weights', 'priority', 'proposal', 'parser'):
        assert key not in sent and key not in response
    assert not hasattr(env.proxy, 'parser') and not hasattr(env.proxy, 'engine')


def test_rejected_and_malformed_requests_reach_ms_without_credentials(env):
    for raw in (None, {'request_text': 'charger', 'auth': {'user_id': 'u_jordan', 'sig': 'secret'}}):
        response = env.client.post('/orders', json=raw)
        assert response.status_code in (400, 401)
        sent = env.main_service.received[-1]
        assert not sent['authorization']['accepted']
        assert sent['authorization']['reason']
        assert sent['limits'] == {}
        assert 'secret' not in json.dumps(sent)


def test_ms_outage_preserves_denial_and_replays_after_restart(env):
    env.main_service.fail = True
    status, body = env.order('buy a gift card')
    assert status == 403 and not body['ok']
    assert body['main_service']['status'] == 'delivery_pending'
    pending = env.proxy.outbox.pending()
    assert len(pending) == 1 and not pending[0]['authorization']['accepted']
    env.main_service.fail = False
    restarted = create_app(env.settings, main_service=env.main_service, clock=env.clock).state.proxy
    asyncio.run(restarted.flush_outbox())
    assert restarted.outbox.pending() == []
    assert env.main_service.received[0] == pending[0]


def test_blank_request_and_non_ascii_signature_are_documented_rejections(env):
    assert env.dashboard('   ')[0] == 400
    auth = {**env.auth(), 'sig': '\u2603'}
    assert env.order('charger', auth=auth)[0] == 401
    assert len(env.main_service.received) == 2
    assert all(not row['authorization']['accepted'] for row in env.main_service.received)


def test_accepted_request_is_queued_once_during_ms_outage(env):
    env.main_service.fail = True
    first = env.dashboard('charger', request_id='retry')
    again = env.dashboard('charger', request_id='retry')
    assert first[0] == again[0] == 200
    assert again[1]['duplicate'] is True
    assert len(env.proxy.outbox.pending()) == 1
    env.main_service.fail = False
    asyncio.run(env.proxy.flush_outbox())
    assert len(env.main_service.received) == 1


def test_changed_profiles_cannot_reuse_authorization(env):
    env.dashboard('charger', request_id='same')
    status, body = env.dashboard('charger', request_id='same', user={**ALEX, 'approvalLimit': 999999})
    assert status == 409 and body['decision'] == 'conflict'


def test_connector_org_policy_and_user_permission_are_enforced(env):
    company = {**NORTHSTAR, 'purchasePolicy': {**NORTHSTAR['purchasePolicy'],
               'blockedCategories': ['custom'], 'blockedKeywords': {'custom': ['printer']}}}
    status, result = env.dashboard('buy a printer', company=company)
    assert status == 403 and result['decision'] == 'violates_company_policy'
    status, result = env.dashboard('charger', user={**ALEX, 'purchasingEnabled': False})
    assert status == 403 and result['decision'] == 'not_authorized'
    assert env.dashboard('buy a printer')[0] == 200  # Policy overrides are scoped to this organization/request.


def test_http_client_uses_handoff_contract(env):
    env.order('charger')
    payload = env.main_service.received[0]
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'order_id': payload['order_id'], 'status': 'queued'})
    async def send():
        client = MainServiceClient('http://ms.test', transport=httpx.MockTransport(handler))
        try:
            return await client.submit(payload)
        finally:
            await client.aclose()
    assert asyncio.run(send())['status'] == 'queued'
    assert seen[0].url.path == '/handoffs' and json.loads(seen[0].content) == payload
