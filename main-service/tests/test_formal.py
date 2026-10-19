import asyncio
import copy

import pytest
from z3 import Solver

from main_service.candidates import Candidate
from main_service.demo_app import DemoVerifier, candidate
from main_service.formal import bind_proof, prove_listing
from main_service.proof import build_search
from main_service.spec import RuleSpecParser, DEFAULT_WEIGHTS
from main_service.vendor.purchase_verifier.types import sha256_of
from .conftest import handoff
from .test_candidates import prepared, product_page, Pages, submission


def reviewed(slug='charger-65'):
    search = build_search(asyncio.run(RuleSpecParser().parse('65W USB-C charger under $40')),
                          handoff()['limits'], DEFAULT_WEIGHTS)
    report = asyncio.run(DemoVerifier().verify(Candidate.model_validate(candidate(slug)), search.specs, search.limits))
    return report, search.specs, search.limits


@pytest.mark.parametrize('slug,status', [('charger-65', 'proven'), ('charger-30', 'rejected'), ('stapler', 'rejected')])
def test_real_solver_classifies_demo_products_and_replays_queries(slug, status):
    report, _, _ = reviewed(slug)
    proof = report['formal_proof']
    assert proof['status'] == status
    assert not proof['purchase_authorized']
    assert proof['evidence_sha256'] == report['evidence']['sha256']
    assert len(proof['solver_queries']) == 2
    for query in proof['solver_queries']:
        solver = Solver()
        solver.from_string(query['smt2'])
        assert str(solver.check()) == query['result']


def test_solver_uses_company_budget_and_exact_tax_total():
    report, specs, limits = reviewed()
    assert report['formal_proof']['status'] == 'proven'
    lower = {**limits, 'max_total_cents': 2700}
    new = asyncio.run(DemoVerifier().verify(Candidate.model_validate(candidate('charger-65')), specs, lower))
    assert new['formal_proof']['status'] == 'rejected'
    assert new['formal_proof']['contract_hash'] != report['formal_proof']['contract_hash']
    assert new['formal_proof']['spec_hash'] != report['formal_proof']['spec_hash']
    assert new['formal_proof']['counterexample']['policy_total_cents'] == 2756


def test_unknown_fact_cannot_prove_a_universal_nonnegative_bound():
    report, specs, limits = reviewed()
    specs['constraints'] = [{'field': 'power', 'op': 'ge', 'value': 0, 'unit': 'W', 'required': True}]
    report['facts'].pop('power')
    proof = prove_listing(report, specs, limits)
    assert proof['status'] == 'unknown'
    assert 'power' in proof['missing_fields']


@pytest.mark.parametrize('value,op,bound,expected', [
    ('64.999999999999', 'ge', 65, 'rejected'), ('65.000000000001', 'ge', 65, 'proven'),
    ('65.0000000000001', 'ge', 65, 'unknown'), ('65', 'ne', 65, 'rejected'), ('66', 'ne', 65, 'proven'),
])
def test_numeric_boundaries_are_exact_and_not_equal_is_preserved(value, op, bound, expected):
    report, specs, limits = reviewed()
    specs['constraints'] = [{'field': 'power', 'op': op, 'value': bound, 'unit': 'W', 'required': True}]
    report['facts']['power'] = {'value': value, 'unit': 'W'}
    assert prove_listing(report, specs, limits)['status'] == expected


def test_unseen_enum_value_and_missing_enum_evidence_are_distinct():
    report, specs, limits = reviewed()
    specs['constraints'] = [{'field': 'connector', 'op': 'ne', 'value': 'barrel', 'unit': None, 'required': True}]
    assert prove_listing(report, specs, limits)['status'] == 'proven'
    report['facts'].pop('connector')
    assert prove_listing(report, specs, limits)['status'] == 'unknown'


def test_contradictory_spec_and_unsupported_requirement_never_prove():
    report, specs, limits = reviewed()
    specs['constraints'] += [{'field': 'power', 'op': 'le', 'value': 30, 'unit': 'W', 'required': True}]
    assert prove_listing(report, specs, limits)['status'] == 'inconsistent_requirements'
    specs['constraints'].pop()
    specs['unsupported_requirements'] = ['quiet']
    assert prove_listing(report, specs, limits)['status'] == 'unknown'


def test_agent_candidates_persist_bound_real_proofs_not_claim_flags(tmp_path):
    service, order_id, _, _ = prepared(tmp_path)
    service.submit_candidates(order_id, submission(service, order_id))
    asyncio.run(service.process_next())
    result = service.store.get(order_id)['result']
    proof = result['verification']['candidates'][0]['formal_proof']
    assert proof['status'] == 'proven'
    assert proof['requirements_id'] == result['requirements_id']
    assert proof['receipt_hash'] == sha256_of({k: v for k, v in proof.items() if k != 'receipt_hash'})
    previous = copy.deepcopy(proof)
    bind_proof(proof, 'other-order-requirements')
    assert proof['receipt_hash'] != previous['receipt_hash']


@pytest.mark.parametrize('body', [b'not product evidence', product_page(unit='unknown')])
def test_inaccessible_or_unusable_evidence_gets_an_unknown_bound_proof(tmp_path, body):
    service, order_id, _, _ = prepared(tmp_path, Pages(body))
    service.submit_candidates(order_id, submission(service, order_id))
    asyncio.run(service.process_next())
    result = service.store.get(order_id)['result']
    proof = result['verification']['candidates'][0]['formal_proof']
    assert proof['status'] == 'unknown'
    assert proof['requirements_id'] == result['requirements_id']


def test_remote_backend_proof_flags_never_replace_local_policy_checks(tmp_path):
    service, order_id, _, _ = prepared(tmp_path, Pages(product_page(power='30')))
    result = service.store.get(order_id)['result']
    result['engine'] = {'status': 'verified', 'proven': True, 'top': [{
        'sku': 'CH-65', 'url': 'https://supplier.example/charger', 'price_cents': 2500, 'proven': True}]}
    asyncio.run(service.verify_managed_candidates(result))
    proof = result['verification']['candidates'][0]['formal_proof']
    assert proof['status'] == 'rejected'
    assert proof['requirements_id'] == result['requirements_id']


def test_solver_rejects_inconsistent_facts_before_entailment():
    from main_service.vendor.purchase_verifier.types import Candidate as SolverCandidate, Constraint, Fact, FieldDef, Spec
    from main_service.vendor.purchase_verifier.verify import verify
    spec = Spec(fields={'power': FieldDef(name='power', type='quantity', measures='power', base_unit='W')},
                constraints=[Constraint(field='power', op='min', value=65, tier='hard', origin='request', source_text='65 W')])
    spec.spec_hash = spec.compute_hash()
    item = SolverCandidate(listing_id='one', sku='one', seller='fixture', price_cents=2500, snapshot_id='snapshot',
                           facts=[Fact(field='power', values=[value], source_url='https://example.com', method='jsonld')
                                  for value in (30, 65)])
    assert verify(item, spec).status == 'vacuous'
