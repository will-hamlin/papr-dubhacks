from datetime import timedelta

from proxy.signing import check_request_token, make_request_token
from .conftest import SECRET


def test_request_token_is_scoped_expiring_and_tamper_resistant(env):
    now = env.clock()
    token = make_request_token('order-1', SECRET, now)
    assert check_request_token(token, 'order-1', SECRET, now)
    assert not check_request_token(token, 'order-2', SECRET, now)
    assert not check_request_token(token, 'order-1', 'different', now)
    assert not check_request_token(token, 'order-1', SECRET, now + timedelta(hours=24))
    assert not check_request_token('not a token', 'order-1', SECRET, now)


def test_invalid_search_mode_is_documented_and_mode_cannot_change_on_retry(env):
    status = env.client.post('/orders', json={
        'auth': env.auth(), 'request_text': 'charger', 'search_mode': 'skip-verification'})
    assert status.status_code == 400 and not env.main_service.received[-1]['authorization']['accepted']
    request = {'request': {'id': 'mode-retry', 'createdAt': 'now', 'text': 'charger', 'search_mode': 'agent'},
               'userConfig': {'employeeId': 'EMP-1', 'companyId': 'CO-1', 'name': 'Alex', 'approvalLimit': 100},
               'companyConfig': {'companyId': 'CO-1', 'name': 'Company'}}
    headers = {'Authorization': 'Bearer test-token'}
    assert env.client.post('/orders', json=request, headers=headers).status_code == 200
    request['request']['search_mode'] = 'managed'
    assert env.client.post('/orders', json=request, headers=headers).status_code == 409
