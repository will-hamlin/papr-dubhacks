"""Persist proxy decisions and process accepted requests through the verifier."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .engine import AgentV1Engine, HttpEngine, StubEngine
from .proof import build_search, check_policy
from .signing import sign_payload
from .spec import DEFAULT_WEIGHTS, FallbackSpecParser, make_parser
from .store import RequestStore
from .candidates import Candidate, CandidateSubmission
from .verification import ListingVerifier
from pydantic import ValidationError

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    shared_secret: str = ''
    database: Path = ROOT / 'var' / 'requests.sqlite3'
    engine_url: str | None = None
    engine_kind: str = 'auto'
    supplier_hosts: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls):
        return cls(shared_secret=os.environ.get('PROXY_SHARED_SECRET', ''),
                   database=Path(os.environ.get('MS_DATABASE', str(cls.database))),
                   engine_url=os.environ.get('ENGINE_URL'), engine_kind=os.environ.get('ENGINE_KIND', 'auto'),
                   supplier_hosts=json.loads(os.environ.get('MS_SUPPLIER_HOSTS', '{}')))


class MainService:
    def __init__(self, settings: Settings, parser=None, engine=None, verifier=None):
        if not settings.shared_secret:
            raise RuntimeError('PROXY_SHARED_SECRET is not set; refusing to start')
        if os.environ.get('PAPR_ENV') == 'production':
            if len(settings.shared_secret) < 32:
                raise RuntimeError('Production requires PROXY_SHARED_SECRET of at least 32 characters')
            if settings.engine_kind not in ('agent_v1', 'http') or not settings.engine_url:
                raise RuntimeError('Production requires an explicit live ENGINE_KIND and ENGINE_URL')
            if os.environ.get('SPEC_PARSER') != 'claude' or os.environ.get('SPEC_ALLOW_RULE_FALLBACK', '0') != '0':
                raise RuntimeError('Production requires SPEC_PARSER=claude and SPEC_ALLOW_RULE_FALLBACK=0')
            if not os.environ.get('ANTHROPIC_MODEL') or not (os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('ANTHROPIC_AUTH_TOKEN')):
                raise RuntimeError('Production requires an explicit ANTHROPIC_MODEL and Anthropic credential')
            if settings.engine_kind == 'http' and not os.environ.get('ENGINE_API_KEY'):
                raise RuntimeError('Production HTTP backend requires ENGINE_API_KEY')
            if not settings.supplier_hosts:
                raise RuntimeError('Production requires MS_SUPPLIER_HOSTS supplier mappings')
        if not isinstance(settings.supplier_hosts, dict) or not all(
                isinstance(host, str) and isinstance(supplier, str) and host and supplier
                for host, supplier in settings.supplier_hosts.items()):
            raise RuntimeError('MS_SUPPLIER_HOSTS must map exact supplier hostnames to supplier IDs')
        self.settings = settings
        self.store = RequestStore(settings.database)
        self.parser = parser or make_parser()
        self.engine = engine or self._make_engine(settings)
        self.verifier = verifier or ListingVerifier(supplier_hosts=settings.supplier_hosts)
        self.lock = asyncio.Lock()
        self.poll_cursor = ''

    @staticmethod
    def _make_engine(settings):
        if settings.engine_kind == 'stub' or (settings.engine_kind == 'auto' and not settings.engine_url):
            return StubEngine()
        if not settings.engine_url:
            raise RuntimeError('ENGINE_URL is required for a live search/verifier backend')
        if settings.engine_kind in ('auto', 'agent_v1'):
            return AgentV1Engine(settings.engine_url)
        if settings.engine_kind == 'http':
            return HttpEngine(settings.engine_url)
        raise RuntimeError(f'Unknown ENGINE_KIND: {settings.engine_kind}')

    def receive(self, payload: dict):
        record = self.store.receive(payload)
        return {'order_id': record['order_id'], 'status': record['status'], 'documented': True}

    def submit_candidates(self, order_id, submission):
        body = CandidateSubmission.model_validate(submission)
        return self.store.add_candidates(order_id, body.model_dump())

    async def verify_candidates(self, candidates, result, source):
        reports = []
        for candidate in candidates:
            reports.append(await self.verifier.verify(candidate, result['specs'], result['limits']))
        return {'source': source, 'requirements_id': result['requirements_id'], 'candidates': reports,
                'scope': 'published_listing_claims_and_compiled_constraints', 'purchase_authorized': False}

    async def verify_managed_candidates(self, result):
        backend = result.get('engine')
        if not isinstance(backend, dict):
            return
        items = backend.get('candidates') or backend.get('top') or []
        if not isinstance(items, list):
            items = []
        candidates, unsupported = [], []
        for index, item in enumerate(items[:10]):
            candidate_id = f'managed-{index + 1}'
            try:
                if not isinstance(item, dict):
                    raise ValueError('candidate is not an object')
                claims = item.get('claims')
                if claims is None:
                    claims = [{'field': key, 'value': item[key]} for key in
                              ('name', 'sku', 'price_cents', 'currency') if key in item]
                candidates.append(Candidate.model_validate({
                    'candidate_id': candidate_id, 'url': item.get('url') or item.get('product_url'),
                    'sku': item.get('sku'), 'claims': claims,
                }))
            except (ValidationError, ValueError):
                unsupported.append({'candidate_id': candidate_id, 'claims_status': 'unverified',
                                    'requirements_status': 'unverified',
                                    'reason': 'search backend did not supply a usable listing URL and typed claims'})
        result['verification'] = await self.verify_candidates(candidates, result, 'managed')
        result['verification']['candidates'].extend(unsupported)
        if not items:
            result['verification']['reason'] = 'no candidate listings returned; backend verification flags are not listing evidence'
        if len(items) > 10:
            result['verification']['unprocessed_count'] = len(items) - 10

    async def process_next(self):
        async with self.lock:
            record = self.store.next_queued()
            if record is None:
                return False
            order_id, handoff = record['order_id'], record['handoff']
            local_check = record['status'] in ('candidates_queued', 'verification_queued')
            result = record['result'] if local_check else {
                key: record['result'][key] for key in ('recovery',) if key in record['result']}
            result['processing_stage'] = {'candidates_queued': 'agent_verification',
                                          'verification_queued': 'managed_verification'}.get(record['status'], 'preparing')
            self.store.save(order_id, 'processing', result)
            try:
                if record['status'] == 'candidates_queued':
                    submission = CandidateSubmission.model_validate(result['candidate_submission'])
                    result['verification'] = await self.verify_candidates(submission.candidates, result, 'agent')
                    result.pop('processing_stage', None)
                    self.store.finish_candidates(order_id, result)
                    return True
                if record['status'] == 'verification_queued':
                    await self.verify_managed_candidates(result)
                    self.finish_managed(order_id, result)
                    return True
                text = handoff['request']['text']
                note = None
                if isinstance(self.parser, FallbackSpecParser):
                    proposal, source, note = await self.parser.parse_with_source(text)
                else:
                    proposal, source = await self.parser.parse(text), self.parser.name
                result.update(parser=source, proposal=proposal.model_dump())
                violations = check_policy(proposal, text, handoff['limits'])
                if violations:
                    result.update(decision='violates_company_policy', reason='; '.join(violations))
                    self.store.save(order_id, 'failed', result)
                    return True
                if not proposal.understood or not proposal.item.strip():
                    result.update(decision='unclear_request', reason=proposal.unclear_reason or 'could not tell what to buy')
                    self.store.save(order_id, 'failed', result)
                    return True
                search = build_search(proposal, handoff['limits'], DEFAULT_WEIGHTS)
                result.update(specs=search.specs, weights=search.weights, priority=search.priority,
                              limits=search.limits, notes=search.notes + ([note] if note else []))
                if search.errors:
                    result.update(decision='unclear_request', reason='; '.join(search.errors))
                    self.store.save(order_id, 'failed', result)
                    return True
                requirements = {'order_id': order_id, 'specs': search.specs, 'limits': search.limits}
                result['requirements_id'] = hashlib.sha256(
                    json.dumps(requirements, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                if handoff['request'].get('search_mode', 'managed') == 'agent':
                    result['decision'] = 'awaiting_candidates'
                    result.pop('processing_stage', None)
                    self.store.save(order_id, 'awaiting_candidates', result)
                    return True
                payload = sign_payload({
                    'order_id': order_id, 'issued_at': handoff['issued_at'],
                    'company': handoff['company'], 'requester': handoff['requester'], 'request_text': text,
                    'specs': search.specs, 'weights': search.weights, 'priority': search.priority, 'limits': search.limits,
                }, self.settings.shared_secret)
                result['engine_kind'] = self.engine.name
                result['processing_stage'] = 'submitting_backend'
                self.store.save(order_id, 'processing', result)
                result['engine'] = await self.engine.search(payload)
                # Persist the response before fetching evidence: local retry must never repeat search.
                result['processing_stage'] = 'managed_verification'
                self.store.save(order_id, 'processing', result)
                await self.verify_managed_candidates(result)
                self.finish_managed(order_id, result)
            except Exception as exc:
                log.exception('Main service processing failed for %s', order_id)
                result.update(decision='processing_error', reason=str(exc))
                status = 'interrupted' if result.get('processing_stage') == 'submitting_backend' else 'failed'
                self.store.save(order_id, status, result)
            return True

    def finish_managed(self, order_id, result):
        # A backend's terminal state is not a passing local verification result.
        result['decision'] = 'submitted'
        engine_status = result['engine'].get('status', 'submitted') if isinstance(result['engine'], dict) else 'submitted'
        engine_kind = result.get('engine_kind', self.engine.name)
        status = 'not_searched' if engine_kind == 'stub' else 'submitted'
        if engine_kind != 'stub' and engine_status in ('purchased', 'completed', 'verified'):
            status = 'completed'
        elif engine_status in ('failed', 'escalated'):
            status = 'failed'
        result['engine_status'] = engine_status
        result.pop('processing_stage', None)
        self.store.save(order_id, status, result)

    async def aclose(self):
        close = getattr(self.engine, 'aclose', None)
        if close:
            await close()

    async def refresh_results(self, limit=5):
        if not hasattr(self.engine, 'status'):
            return
        records = sorted(self.store.submitted(), key=lambda record: record['order_id'])
        later = [record for record in records if record['order_id'] > self.poll_cursor]
        earlier = [record for record in records if record['order_id'] <= self.poll_cursor]
        for record in (later + earlier)[:limit]:
            self.poll_cursor = record['order_id']
            result = record['result']
            engine = result.get('engine', {})
            if not isinstance(engine, dict) or not engine.get('request_id'):
                continue
            try:
                async with asyncio.timeout(15):
                    view = await self.engine.status(engine['request_id'])
            except Exception:
                log.exception('Could not refresh verifier result for %s', record['order_id'])
                continue
            result['engine'] = {**engine, **view}
            result['engine_status'] = view.get('status')
            status = 'submitted'
            if view.get('status') in ('purchased', 'completed', 'verified'):
                status = 'completed'
            elif view.get('status') in ('failed', 'escalated'):
                status = 'failed'
            if (view.get('candidates') or view.get('top') or status == 'completed') and (
                    result['engine'] != engine or 'verification' not in result):
                await self.verify_managed_candidates(result)
            self.store.save(record['order_id'], status, result)
