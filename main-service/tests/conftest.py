import asyncio
import uuid
from pathlib import Path

import pytest

from main_service.engine import StubEngine
from main_service.service import MainService, Settings
from main_service.signing import sign_payload
from main_service.spec import RuleSpecParser

SECRET = 'test-secret'


def handoff(text='65W USB-C charger', accepted=True):
    return sign_payload({
        'version': 1, 'order_id': 'o_' + uuid.uuid4().hex, 'issued_at': '2026-10-18T00:00:00+00:00',
        'authorization': {'accepted': accepted, 'decision': 'accepted' if accepted else 'not_authorized',
                          'reason': None if accepted else 'purchasing disabled',
                          'http_status': 200 if accepted else 403, 'identity_verified': True},
        'request': {'id': 'client-request', 'text': text},
        'organization': {'companyId': 'acme'}, 'user': {'employeeId': 'u_jordan'},
        'company': {'id': 'acme', 'name': 'Acme'}, 'requester': {'user_id': 'u_jordan'},
        'limits': {'currency': 'USD', 'max_total_cents': 50000, 'tax_rate_bp': 1025,
                   'approved_suppliers': ['sup_01'], 'freight_cents_by_supplier': {'sup_01': 0},
                   'blocked_categories': ['weapons', 'medicine', 'age_restricted', 'gift_cards'],
                   'blocked_keywords': {'gift_cards': ['gift card']}},
    }, SECRET)


class Env:
    def __init__(self, path: Path, parser=None, engine=None):
        self.engine = engine or StubEngine()
        self.service = MainService(Settings(shared_secret=SECRET, database=path / 'requests.sqlite3'),
                                   parser=parser or RuleSpecParser(), engine=self.engine)

    def order(self, text):
        payload = handoff(text)
        self.service.receive(payload)
        asyncio.run(self.service.process_next())
        record = self.service.store.get(payload['order_id'])
        result = record['result']
        status = {'unclear_request': 422, 'violates_company_policy': 403,
                  'processing_error': 502}.get(result.get('decision'), 200)
        return status, {'order_id': payload['order_id'], **result}


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def make_env(tmp_path):
    def make(**kwargs):
        return Env(tmp_path / uuid.uuid4().hex, **kwargs)
    return make
