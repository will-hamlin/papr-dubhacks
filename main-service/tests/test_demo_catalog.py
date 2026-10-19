import asyncio

import pytest

from main_service.candidates import Candidate
from main_service.demo_app import DemoPages, DemoVerifier, candidate, create_app
from main_service.listing_fetch import EvidenceError
from main_service.service import Settings
from main_service.spec import RuleSpecParser
from .conftest import handoff, SECRET


def test_demo_factory_is_explicit_and_forbidden_in_production(monkeypatch, tmp_path):
    settings = Settings(shared_secret=SECRET, database=tmp_path / 'demo.sqlite3')
    monkeypatch.delenv('PAPR_DEMO_MODE', raising=False)
    with pytest.raises(RuntimeError, match='Demo factory'):
        create_app(settings, RuleSpecParser())
    monkeypatch.setenv('PAPR_DEMO_MODE', '1')
    monkeypatch.setenv('PAPR_ENV', 'production')
    with pytest.raises(RuntimeError, match='Demo factory'):
        create_app(settings, RuleSpecParser())


def test_demo_managed_and_agent_checks_share_fixture_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv('PAPR_DEMO_MODE', '1')
    monkeypatch.setenv('PAPR_ENV', 'development')
    app = create_app(Settings(shared_secret=SECRET, database=tmp_path / 'demo.sqlite3'), RuleSpecParser())
    service = app.state.service

    async def run():
        payload = handoff('65W USB-C charger under $40')
        service.receive(payload)
        assert await service.process_next()
        record = service.store.get(payload['order_id'])
        assert record['status'] == 'completed'
        assert record['result']['engine']['demo'] is True
        reports = record['result']['verification']['candidates']
        assert reports[0]['claims_status'] == reports[0]['requirements_status'] == 'supported'
        assert reports[1]['claims_status'] == reports[1]['requirements_status'] == 'contradicted'
        for report in reports:
            assert report['simulated'] and not report['purchase_authorized']
            assert report['evidence']['basis'] == 'demo_fixture'
            assert report['evidence']['snapshot_utf8']
        agent_report = await DemoVerifier().verify(Candidate.model_validate(candidate('charger-65')),
                                                  record['result']['specs'], record['result']['limits'])
        assert agent_report['requirements_status'] == reports[0]['requirements_status']
        await service.aclose()
    asyncio.run(run())


def test_demo_fixture_fetcher_never_fetches_unknown_urls():
    with pytest.raises(EvidenceError, match='fictional catalog'):
        asyncio.run(DemoPages().fetch('https://127.0.0.1/private'))
