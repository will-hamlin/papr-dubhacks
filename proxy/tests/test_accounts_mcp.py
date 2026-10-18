import asyncio
import base64
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from proxy.app import create_app
from proxy.oauth import client_config
from proxy.service import Settings
from proxy.signing import make_request_token, sign_payload
from .conftest import DATA, RecordingMS

PASSWORD = 'test password only, never deployed'
REDIRECT = 'https://agent.example/callback'


class MS(RecordingMS):
    async def request_status(self, order_id, secret):
        return 200, {'order_id': order_id, 'status': 'awaiting_candidates', 'result': {}}

    async def candidates(self, order_id, payload):
        return 202, {'order_id': order_id, 'status': 'candidates_queued'}


@pytest.fixture
def account_env(tmp_path):
    now = [datetime.now(timezone.utc)]
    settings = Settings(shared_secret='account-test-secret', api_token='operator-token',
                        var_dir=tmp_path, public_url='http://127.0.0.1:8000', dynamic_registration=True)
    ms = MS()
    app = create_app(settings, ms, clock=lambda: now[0])
    store = app.state.proxy.accounts
    policy = json.loads((DATA / 'company_policy.json').read_text())
    store.company(policy)
    user = json.loads((DATA / 'users.json').read_text())[0]
    one = store.create_account(policy['id'], user, PASSWORD)
    other_company = {**policy, 'id': 'other-company', 'name': 'Other company', 'daily_cap_cents': 1000,
                     'spent_today_cents': 0, 'spent_by_job': {}}
    store.company(other_company)
    two = store.create_account(other_company['id'], {**user, 'email': 'other@example.test'}, PASSWORD)
    client_id = store.save_client(client_config({'client_name': 'Test agent', 'redirect_uris': [REDIRECT]}))
    with TestClient(app, base_url=settings.public_url) as client:
        yield {'app': app, 'client': client, 'store': store, 'one': one, 'two': two, 'client_id': client_id,
               'user': user, 'policy': policy, 'now': now, 'settings': settings, 'ms': ms}


def start_flow(env, **overrides):
    verifier = 'v' * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    params = {'client_id': env['client_id'], 'redirect_uri': REDIRECT, 'response_type': 'code',
              'code_challenge': challenge, 'code_challenge_method': 'S256', 'state': 'original-state',
              'resource': env['settings'].public_url + '/mcp', 'scope': 'purchasing', **overrides}
    response = env['client'].get('/authorize', params=params)
    return response, verifier


def fields(page):
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]+)">', page.text))


def code(env, email=None, decision='allow'):
    env['client'].cookies.clear()
    response, verifier = start_flow(env)
    assert response.status_code == 200
    response = env['client'].post('/account/login', data={**fields(response), 'email': email or env['user']['email'],
                                                        'password': PASSWORD, 'decision': decision}, follow_redirects=False)
    assert response.status_code == 303, response.text
    params = parse_qs(urlsplit(response.headers['location']).query)
    assert params['state'] == ['original-state']
    return params, verifier


def exchange(env, auth_code, verifier, **extra):
    return env['client'].post('/token', data={'grant_type': 'authorization_code', 'client_id': env['client_id'],
                            'code': auth_code, 'code_verifier': verifier, 'redirect_uri': REDIRECT,
                            'resource': env['settings'].public_url + '/mcp', **extra})


def login(env, email=None):
    params, verifier = code(env, email)
    response = exchange(env, params['code'][0], verifier)
    assert response.status_code == 200, response.text
    return response.json()


def headers(tokens):
    return {'Authorization': 'Bearer ' + tokens['access_token']}


def order(env, tokens, request_id='example', **extra):
    return env['client'].post('/orders', headers=headers(tokens), json={
        'request_id': request_id, 'request_text': '65W USB-C charger', **extra})


def rpc(env, tokens, method, params=None, request_id=1, **extra_headers):
    return env['client'].post('/mcp', headers={**headers(tokens), 'Accept': 'application/json, text/event-stream',
                             **extra_headers}, json={'jsonrpc': '2.0', 'id': request_id, 'method': method,
                                                    'params': params or {}})


def test_discovery_login_pkce_and_account_config(account_env):
    e = account_env
    missing = e['client'].post('/mcp', json={})
    assert missing.status_code == 401 and 'resource_metadata=' in missing.headers['www-authenticate']
    metadata = e['client'].get('/.well-known/oauth-protected-resource/mcp').json()
    assert metadata['resource'] == e['settings'].public_url + '/mcp'
    assert e['client'].get('/.well-known/oauth-authorization-server').json()['code_challenge_methods_supported'] == ['S256']
    tokens = login(e)
    response = order(e, tokens)
    assert response.status_code == 200 and 'request_token' not in response.json()
    handoff = e['ms'].received[-1]
    assert handoff['authorization']['identity_verified'] is True
    assert handoff['user']['id'] == e['user']['id'] and handoff['organization']['id'] == 'acme'
    assert response.json()['limits']['max_total_cents'] == e['user']['spend_limit_cents']
    assert tokens['access_token'] not in json.dumps(e['app'].state.proxy.audit.entries())
    assert PASSWORD not in e['store'].path.read_bytes().decode(errors='ignore')
    assert tokens['refresh_token'] not in e['store'].path.read_bytes().decode(errors='ignore')


@pytest.mark.parametrize('extra', [{'companyConfig': {'approvalLimit': 99999999}}, {'userConfig': {'id': 'admin'}},
                                 {'account_id': 'other'}, {'auth': {}}])
def test_agent_config_and_identity_spoofing_rejected(account_env, extra):
    e = account_env
    response = order(e, login(e), **extra)
    assert response.status_code == 400
    assert e['ms'].received[-1]['authorization']['accepted'] is False
    assert e['ms'].received[-1]['user']['id'] == e['user']['id']


def test_live_policy_and_user_changes_apply_and_rejections_documented(account_env):
    e = account_env
    tokens = login(e)
    e['store'].update_user(e['one'], {**e['user'], 'spend_limit_cents': 700})
    assert order(e, tokens).json()['limits']['max_total_cents'] == 700
    e['store'].company({**e['policy'], 'daily_cap_cents': 21100})
    assert order(e, tokens, 'next').json()['limits']['max_total_cents'] == 100
    e['store'].update_user(e['one'], {**e['user'], 'purchasing_enabled': False})
    assert order(e, tokens, 'disabled-purchasing').status_code == 403
    assert e['ms'].received[-1]['authorization']['accepted'] is False
    assert e['ms'].received[-1]['authorization']['identity_verified'] is True


def test_owner_isolation_scoped_retries_and_restart(account_env):
    e = account_env
    one = login(e)
    two = login(e, 'other@example.test')
    first = order(e, one).json()
    second = order(e, two).json()
    oid = first['order_id']
    assert second['order_id'] != oid and second['limits']['max_total_cents'] == 1000
    assert order(e, one).json()['order_id'] == oid
    assert order(e, one, request_text='different request').status_code == 409
    assert e['client'].get('/orders/' + oid, headers=headers(two)).status_code == 404
    assert e['client'].post('/orders/' + oid + '/candidates', headers=headers(two), json={}).status_code == 404
    capability = make_request_token(oid, e['settings'].shared_secret, e['now'][0])
    assert e['client'].get('/orders/' + oid, headers={'Authorization': 'Bearer ' + capability}).status_code == 401
    restarted = create_app(e['settings'], e['ms'], clock=lambda: e['now'][0])
    with TestClient(restarted, base_url=e['settings'].public_url) as client:
        assert client.get('/orders/' + oid, headers=headers(one)).status_code == 200
        assert client.get('/orders/' + oid, headers=headers(two)).status_code == 404


@pytest.mark.parametrize('bad', [{'code_challenge_method': 'plain'}, {'resource': ''}, {'resource': 'https://other.example/mcp'},
                               {'redirect_uri': 'https://evil.example'}, {'response_type': 'token'}, {'scope': 'admin'}])
def test_authorization_validation(account_env, bad):
    response, _ = start_flow(account_env, **bad)
    assert response.status_code == 400
    assert 'location' not in response.headers


def test_pkce_code_expiry_replay_and_token_audience(account_env):
    e = account_env
    params, verifier = code(e)
    auth_code = params['code'][0]
    assert exchange(e, auth_code, 'x' * 64).status_code == 400
    assert exchange(e, auth_code, verifier, resource='https://wrong.example/mcp').status_code == 400
    assert exchange(e, auth_code, verifier, redirect_uri='https://wrong.example/callback').status_code == 400
    assert exchange(e, auth_code, verifier).status_code == 200
    assert exchange(e, auth_code, verifier).status_code == 400
    params, verifier = code(e)
    e['now'][0] += timedelta(minutes=3)
    assert exchange(e, params['code'][0], verifier).status_code == 400


@pytest.mark.parametrize('authorize_resource', [True, False])
@pytest.mark.parametrize('token_resource', [True, False])
def test_optional_resource_remains_bound_through_login_and_refresh(account_env, authorize_resource, token_resource):
    e = account_env
    resource = e['settings'].public_url + '/mcp'
    verifier = 'v' * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    params = {'client_id': e['client_id'], 'redirect_uri': REDIRECT, 'response_type': 'code',
              'code_challenge': challenge, 'code_challenge_method': 'S256', 'scope': 'purchasing', 'state': 'muse'}
    if authorize_resource:
        params['resource'] = resource
    page = e['client'].get('/authorize', params=params)
    assert page.status_code == 200
    consent = e['client'].post('/account/login', data={**fields(page), 'email': e['user']['email'],
                               'password': PASSWORD, 'decision': 'allow'}, follow_redirects=False)
    assert consent.status_code == 303
    callback = parse_qs(urlsplit(consent.headers['location']).query)
    assert callback['state'] == ['muse']
    auth_code = callback['code'][0]
    assert e['store'].get(auth_code, 'code')['resource'] == resource
    data = {'grant_type': 'authorization_code', 'client_id': e['client_id'], 'code': auth_code,
            'code_verifier': verifier, 'redirect_uri': REDIRECT}
    if token_resource:
        data['resource'] = resource
    for invalid in ('', 'https://other.example/mcp'):
        assert e['client'].post('/token', data={**data, 'resource': invalid}).status_code == 400
    assert e['client'].post('/token', data={**data, 'code_verifier': 'x' * 64}).status_code == 400
    response = e['client'].post('/token', data=data)
    assert response.status_code == 200
    tokens = response.json()
    assert e['store'].get(tokens['access_token'], 'access')['resource'] == resource
    assert e['store'].get(tokens['refresh_token'], 'refresh')['resource'] == resource
    assert rpc(e, tokens, 'tools/list').status_code == 200
    refresh = {'grant_type': 'refresh_token', 'client_id': e['client_id'], 'refresh_token': tokens['refresh_token']}
    for invalid in ('', 'https://other.example/mcp'):
        assert e['client'].post('/token', data={**refresh, 'resource': invalid}).status_code == 400
    renewed = e['client'].post('/token', data=refresh)
    assert renewed.status_code == 200
    assert e['store'].get(renewed.json()['access_token'], 'access')['resource'] == resource
    assert rpc(e, renewed.json(), 'tools/list').status_code == 200
    assert rpc(e, tokens, 'tools/list').status_code == 401


def test_refresh_rotation_replay_revokes_family(account_env):
    e = account_env
    old = login(e)
    data = {'grant_type': 'refresh_token', 'refresh_token': old['refresh_token'], 'client_id': e['client_id'],
            'resource': e['settings'].public_url + '/mcp'}
    new = e['client'].post('/token', data=data)
    assert new.status_code == 200
    new = new.json()
    assert new['refresh_token'] != old['refresh_token']
    assert order(e, old).status_code == 401
    assert order(e, new).status_code == 200
    assert e['client'].post('/token', data=data).status_code == 400
    assert order(e, new, 'after-replay').status_code == 401


def test_expired_revoked_and_disabled_tokens_fail(account_env):
    e = account_env
    tokens = login(e)
    e['now'][0] += timedelta(minutes=16)
    assert order(e, tokens).status_code == 401
    tokens = login(e)
    e['client'].post('/revoke', data={'token': tokens['access_token'], 'client_id': e['client_id']})
    assert order(e, tokens).status_code == 401
    tokens = login(e)
    e['store'].disable(e['one'])
    assert order(e, tokens).status_code == 401
    assert rpc(e, tokens, 'tools/list').status_code == 401


def test_browser_csrf_consent_login_and_disconnect(account_env):
    e = account_env
    response, _ = start_flow(e)
    assert response.headers['referrer-policy'] == 'same-origin'
    form = {**fields(response), 'email': e['user']['email'], 'password': PASSWORD, 'decision': 'allow'}
    assert e['client'].post('/account/login', data={**form, 'csrf': 'wrong'}).status_code == 400
    assert e['client'].post('/account/login', data=form, headers={'Origin': 'https://evil.example'}).status_code == 400
    assert e['client'].post('/account/login', data=form, headers={'Origin': 'null'}).status_code == 400
    params, _ = code(e, decision='deny')
    assert params['error'] == ['access_denied'] and 'code' not in params
    tokens = login(e)
    account_page = e['client'].get('/account')
    assert 'Acme Corp' in account_page.text
    csrf = fields(account_page)['csrf']
    assert e['client'].post('/account/logout', data={'action': 'revoke', 'csrf': 'bad'}).status_code == 403
    assert e['client'].post('/account/logout', data={'action': 'revoke', 'csrf': csrf}, follow_redirects=False).status_code == 303
    assert order(e, tokens).status_code == 401


def test_browser_form_origin_login_and_logout(account_env):
    e = account_env
    response = e['client'].get('/account/login')
    assert response.headers['referrer-policy'] == 'same-origin'
    form = {**fields(response), 'email': e['user']['email'], 'password': PASSWORD, 'decision': 'allow'}
    response = e['client'].post('/account/login', data=form,
                               headers={'Origin': e['settings'].public_url}, follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'] == '/account'
    account = e['client'].get('/account')
    assert 'Your account' in account.text
    assert account.headers['referrer-policy'] == 'same-origin'
    response = e['client'].post('/account/logout', data={**fields(account), 'action': 'logout'},
                               headers={'Origin': e['settings'].public_url}, follow_redirects=False)
    assert response.status_code == 303
    assert e['client'].get('/account', follow_redirects=False).headers['location'] == '/account/login'


def test_legacy_config_disabled_and_audit_private(account_env):
    e = account_env
    assert e['client'].post('/orders', headers={'Authorization': 'Bearer operator-token'}, json={
        'request': {}, 'companyConfig': {}, 'userConfig': {}}).status_code == 401
    assert e['client'].get('/audit').status_code == 401
    assert e['client'].get('/audit', headers=headers(login(e))).status_code == 401
    assert e['client'].get('/audit', headers={'Authorization': 'Bearer operator-token'}).status_code == 200


def test_mcp_protocol_tools_account_bound_and_host_protection(account_env):
    e = account_env
    tokens = login(e)
    init = rpc(e, tokens, 'initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                                      'clientInfo': {'name': 'test', 'version': '1'}})
    assert init.status_code == 200 and 'tools' in init.json()['result']['capabilities']
    listed = rpc(e, tokens, 'tools/list').json()['result']['tools']
    assert {t['name'] for t in listed} == {'create_request', 'get_request', 'submit_candidates'}
    assert 'requirements_id' in json.dumps(listed)
    created = rpc(e, tokens, 'tools/call', {'name': 'create_request', 'arguments': {
        'request_id': 'mcp-order', 'request_text': '65W charger'}}).json()['result']
    assert not created.get('isError')
    oid = created['structuredContent']['order_id']
    status = rpc(e, tokens, 'tools/call', {'name': 'get_request', 'arguments': {'order_id': oid}}).json()['result']
    assert status['structuredContent']['status'] == 'awaiting_candidates'
    other = login(e, 'other@example.test')
    status = rpc(e, other, 'tools/call', {'name': 'get_request', 'arguments': {'order_id': oid}}).json()['result']
    assert status['structuredContent']['http_status'] == 404
    assert rpc(e, tokens, 'tools/list', Host='evil.example').status_code == 421
    assert rpc(e, tokens, 'tools/list', Origin='https://evil.example').status_code == 403


def test_company_spend_isolated_and_purchase_retry_safe(account_env):
    e = account_env
    tokens = login(e)
    e['store'].update_user(e['one'], {**e['user'], 'spend_limit_cents': 500000})
    result = order(e, tokens).json()
    body = sign_payload({'order_id': result['order_id'], 'total_cents': 40000}, e['settings'].shared_secret)
    assert e['client'].post('/purchases', json=body).status_code == 200
    assert e['client'].post('/purchases', json=body).json()['decision'] == 'duplicate'
    assert order(e, tokens, 'after-purchase').json()['limits']['max_total_cents'] == 89000
    assert order(e, login(e, 'other@example.test')).json()['limits']['max_total_cents'] == 1000


def test_registration_and_credential_limits(account_env):
    e = account_env
    for uri in ('https://evil.example/#fragment', 'javascript:alert(1)', 'http://agent.example/callback',
                'https://agent.example:invalid/callback'):
        assert e['client'].post('/register', json={'redirect_uris': [uri]}).status_code == 400
    response = e['client'].post('/register', json={'redirect_uris': [REDIRECT], 'client_name': '<script>agent</script>'})
    assert response.status_code == 201
    page, _ = start_flow(e, client_id=response.json()['client_id'])
    assert '<script>agent</script>' not in page.text and '&lt;script&gt;' in page.text
    for i in range(11):
        page, _ = start_flow(e)
        response = e['client'].post('/account/login', data={**fields(page), 'email': e['user']['email'],
                                   'password': 'incorrect', 'decision': 'allow'})
    assert response.status_code == 429


def test_account_purchase_recovers_without_undercounting_after_audit_interruption(account_env):
    e = account_env
    result = order(e, login(e)).json()
    oid = result['order_id']
    # Simulate a callback committed to the account ledger just before its audit append was interrupted.
    assert e['store'].record_purchase(oid, 'acme', e['user']['job_number'], 10000) == 10000
    conflicting = sign_payload({'order_id': oid, 'total_cents': 40000}, e['settings'].shared_secret)
    assert e['client'].post('/purchases', json=conflicting).status_code == 409
    original = sign_payload({'order_id': oid, 'total_cents': 10000}, e['settings'].shared_secret)
    assert e['client'].post('/purchases', json=original).status_code == 200
    user, policy = e['store'].profile(e['one'])
    assert e['store'].spend(policy, user.job_number) == (31000, 74000)
