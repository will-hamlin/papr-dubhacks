import asyncio

import pytest

from main_service.app import create_app
from main_service.engine import StubEngine
from main_service.service import MainService, Settings
from main_service.spec import RuleSpecParser
from main_service.store import ConflictError, RequestStore
from .conftest import SECRET, handoff


class InterruptedParser(RuleSpecParser):
    async def parse(self, text):
        raise asyncio.CancelledError()


class Backend(StubEngine):
    name = 'agent_v1'

    def __init__(self):
        super().__init__()
        self.polled = []

    async def search(self, payload):
        self.received.append(payload)
        return {'request_id': payload['order_id'], 'status': 'verifying'}

    async def status(self, request_id):
        self.polled.append(request_id)
        return {'status': 'verifying'}


def service(tmp_path, parser=None, engine=None):
    return MainService(Settings(shared_secret=SECRET, database=tmp_path / 'requests.sqlite3'),
                       parser or RuleSpecParser(), engine or Backend())


def test_restart_requires_operator_retry_for_interrupted_preparation(tmp_path):
    first = service(tmp_path, parser=InterruptedParser())
    payload = handoff()
    payload['request']['search_mode'] = 'agent'
    first.receive(payload)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(first.process_next())
    assert first.store.get(payload['order_id'])['result']['processing_stage'] == 'preparing'
    restored = service(tmp_path)
    restored.store.recover()
    assert restored.store.next_queued() is None
    assert restored.store.interrupted() == [{'order_id': payload['order_id'], 'stage': 'preparing', 'retryable': True}]
    assert restored.store.retry_interrupted(payload['order_id'])['status'] == 'queued'
    asyncio.run(restored.process_next())
    result = restored.store.get(payload['order_id'])
    assert result['status'] == 'awaiting_candidates'
    assert result['result']['recovery']['retries'] == 1
    assert restored.engine.received == []
    with pytest.raises(ConflictError):
        restored.store.retry_interrupted(payload['order_id'])


def test_restart_retries_agent_evidence_with_original_batch_and_requirements(tmp_path):
    first = service(tmp_path)
    payload = handoff()
    payload['request']['search_mode'] = 'agent'
    first.receive(payload)
    asyncio.run(first.process_next())
    order_id = payload['order_id']
    requirements = first.store.get(order_id)['result']['requirements_id']
    batch = {'submission_id': 'batch-1', 'requirements_id': requirements, 'candidates': [
        {'candidate_id': 'one', 'url': 'https://supplier.example/item',
         'claims': [{'field': 'price_cents', 'value': 1000}]}]}
    first.submit_candidates(order_id, batch)

    async def interrupted(*_args):
        raise asyncio.CancelledError()
    first.verify_candidates = interrupted
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(first.process_next())
    restored = service(tmp_path)
    restored.store.recover()
    assert restored.store.retry_interrupted(order_id)['status'] == 'candidates_queued'

    async def checked(candidates, result, source):
        assert source == 'agent' and candidates[0].candidate_id == 'one'
        assert result['requirements_id'] == requirements
        return {'source': source, 'candidates': [], 'purchase_authorized': False}
    restored.verify_candidates = checked
    asyncio.run(restored.process_next())
    assert restored.store.get(order_id)['status'] == 'verification_complete'
    assert restored.submit_candidates(order_id, batch)['duplicate']
    assert restored.engine.received == []


def test_saved_backend_response_retries_only_local_verification(tmp_path):
    first = service(tmp_path)
    payload = handoff()
    first.receive(payload)

    async def interrupted(_result):
        raise asyncio.CancelledError()
    first.verify_managed_candidates = interrupted
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(first.process_next())
    persisted = first.store.get(payload['order_id'])['result']
    assert persisted['engine']['request_id'] == payload['order_id']
    assert persisted['processing_stage'] == 'managed_verification'
    assert len(first.engine.received) == 1
    restored = service(tmp_path)
    restored.store.recover()
    assert restored.store.retry_interrupted(payload['order_id'])['status'] == 'verification_queued'
    asyncio.run(restored.process_next())
    assert restored.store.get(payload['order_id'])['status'] == 'submitted'
    assert restored.engine.received == []


@pytest.mark.parametrize('stage', ['submitting_backend', None])
def test_uncertain_and_old_unclassified_jobs_cannot_be_replayed(tmp_path, stage):
    store = RequestStore(tmp_path / 'requests.sqlite3')
    payload = handoff()
    store.receive(payload)
    result = {'processing_stage': stage} if stage else {}
    store.save(payload['order_id'], 'processing', result)
    store.recover()
    assert store.interrupted()[0]['retryable'] is False
    with pytest.raises(ConflictError, match='external submission may have occurred'):
        store.retry_interrupted(payload['order_id'])
    assert store.next_queued() is None


def test_crash_during_backend_submission_is_never_replayed(tmp_path):
    class InterruptedBackend(Backend):
        async def search(self, payload):
            self.received.append(payload)
            raise asyncio.CancelledError()
    first = service(tmp_path, engine=InterruptedBackend())
    payload = handoff()
    first.receive(payload)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(first.process_next())
    first.store.recover()
    assert first.store.interrupted()[0]['stage'] == 'submitting_backend'
    assert first.store.interrupted()[0]['retryable'] is False
    assert not asyncio.run(first.process_next())
    assert len(first.engine.received) == 1


def test_polling_is_bounded_and_rotates_past_failing_backend_jobs(tmp_path):
    class PartlyOffline(Backend):
        async def status(self, request_id):
            self.polled.append(request_id)
            if request_id == 'o_0':
                raise RuntimeError('backend unavailable')
            return {'status': 'verifying'}
    current = service(tmp_path, engine=PartlyOffline())
    for index in range(7):
        payload = handoff()
        payload['order_id'] = f'o_{index}'
        current.receive(payload)
        asyncio.run(current.process_next())
    asyncio.run(current.refresh_results(limit=3))
    assert current.engine.polled == ['o_0', 'o_1', 'o_2']
    asyncio.run(current.refresh_results(limit=3))
    asyncio.run(current.refresh_results(limit=3))
    assert current.engine.polled == ['o_0', 'o_1', 'o_2', 'o_3', 'o_4', 'o_5', 'o_6', 'o_0', 'o_1']


def test_escalation_keeps_polling_after_human_review(tmp_path):
    class NeedsReview(Backend):
        async def search(self, payload):
            return {'request_id': 'review', 'status': 'escalated', 'approval_url': 'http://127.0.0.1:8002/#/requests/review'}

        async def status(self, request_id):
            return {'status': 'completed', 'approval_url': None}

    current = service(tmp_path, engine=NeedsReview())
    payload = handoff()
    current.receive(payload)
    asyncio.run(current.process_next())
    assert current.store.get(payload['order_id'])['status'] == 'submitted'
    asyncio.run(current.refresh_results())
    assert current.store.get(payload['order_id'])['status'] == 'completed'


def test_backend_polling_continues_while_local_queue_work_is_blocked(tmp_path):
    async def exercise():
        started, release, polled = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class WaitingParser(RuleSpecParser):
            async def parse(self, text):
                started.set()
                await release.wait()
                return await super().parse(text)

        class ObservableBackend(Backend):
            async def status(self, request_id):
                await started.wait()
                polled.set()
                return await super().status(request_id)

        app = create_app(Settings(shared_secret=SECRET, database=tmp_path / 'requests.sqlite3'),
                         WaitingParser(), ObservableBackend())
        current = app.state.service
        remote = handoff()
        current.receive(remote)
        current.store.save(remote['order_id'], 'submitted', {'engine': {'request_id': 'remote', 'status': 'verifying'},
                                                         'verification': {'candidates': []}})
        current.receive(handoff())
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(polled.wait(), 2)
            assert not release.is_set()
        assert current.engine.polled == ['remote']
    asyncio.run(exercise())
