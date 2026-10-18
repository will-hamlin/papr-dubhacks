"""Bind the upstream SMT verifier to PAPR's compiled requirements and fetched facts.

The solver proves implications about published evidence. Product identity and
policy predicates remain explicit assumptions supplied by the listing checker.
Nothing in this module approves a purchase or trusts an external proof flag.
"""
from fractions import Fraction
from decimal import Decimal
import logging

from .vendor.purchase_verifier.types import Candidate, Constraint, Fact, FieldDef, FieldType, Spec, sha256_of
from .vendor.purchase_verifier.verify import spec_satisfiable, verify

UPSTREAM_REVISION = '79ac1403f263c49a655e723d811ba38115ea933e'
SCALE = 10**12
log = logging.getLogger(__name__)


def unavailable(reason):
    return {'status': 'unknown', 'engine': 'agent-purchase-verifier / Z3',
            'upstream_revision': UPSTREAM_REVISION, 'reason': reason,
            'purchase_authorized': False, 'scope': 'compiled_requirements_given_published_evidence'}


def prove_listing(report, specs, limits):
    """Use only MS-fetched facts; every hard condition must be represented."""
    from .proof import UNITS

    output = unavailable('Published evidence is incomplete.')
    output['contract_hash'] = sha256_of({'specs': specs, 'limits': limits})
    output['evidence_sha256'] = report.get('evidence', {}).get('sha256')
    if not report.get('facts') or not report.get('evidence'):
        return output
    fields, constraints, evidence, missing = {}, [], [], []
    published = report['facts']
    checks = {c['field']: c for c in report.get('requirement_checks', [])}

    def require(name, field_type, op, expected, observed, *, options=None, unit=None, label=None, policy=False):
        definition = FieldDef(name=name, type=field_type, measures=label or name,
                              base_unit=unit, options=options)
        if name in fields and fields[name] != definition:
            raise ValueError('incompatible constraints on the same field')
        is_new = name not in fields
        fields[name] = definition
        constraints.append(Constraint(field=name, op=op, value=expected, tier='hard',
                                      origin='company_policy' if policy else 'request', source_text=label or name))
        if is_new:
            if observed is None:
                missing.append(label or name)
            evidence.append(Fact(field=name, values=None if observed is None else [observed],
                                 source_url=report['evidence']['url'], quote_checked=True,
                                 method='policy' if policy else 'jsonld'))

    def exact_number(value, unit, expected_unit):
        if value is None:
            return None
        try:
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                return None
            if len(str(value)) > 100:
                return None
            decimal = Decimal(str(value))
            if not decimal.is_finite() or abs(decimal) > 10**18 or abs(decimal.as_tuple().exponent) > 48:
                return None
            base, factor = UNITS[unit] if unit in UNITS else ('mV', 1) if unit == 'mV' else (None, 1)
            if base != expected_unit:
                return None
            scaled = Fraction(value) * Fraction(factor) * SCALE
            if scaled < 0 or scaled.denominator != 1:
                return None
            return int(scaled)
        except (ValueError, TypeError, ArithmeticError):
            return None

    def enum(name, requirements, observed, label, policy=False):
        values = sorted({str(c['value']).strip().casefold() for c in requirements})
        other = '__unlisted_value__'
        while other in values:
            other += '_'
        options = values + [other]
        actual = observed.strip().casefold() if isinstance(observed, str) else None
        if actual is not None and actual not in values:
            actual = other
        for c in requirements:
            value = str(c['value']).strip().casefold()
            if c['op'] not in ('eq', 'ne'):
                raise ValueError('unsupported text comparison')
            require(name, FieldType.ENUM, 'eq' if c['op'] == 'eq' else 'not_in',
                    value if c['op'] == 'eq' else [value], actual, options=options, label=label, policy=policy)

    try:
        grouped = {}
        for c in specs['constraints']:
            if c['required']:
                grouped.setdefault(c['field'], []).append(c)
        for field, items in grouped.items():
            fact = published.get(field)
            unit = items[0]['unit']
            if any(c['unit'] != unit for c in items):
                raise ValueError('mixed units in compiled constraints')
            if unit is None:
                enum('product_' + field, items, fact['value'] if fact and fact['unit'] is None else None, field)
            else:
                actual = exact_number(fact['value'], fact['unit'], unit) if fact else None
                for c in items:
                    if type(c['value']) is not int:
                        raise ValueError('compiled numeric bound must be an integer')
                    require('product_' + field, FieldType.QUANTITY,
                            {'eq': 'eq', 'ne': 'ne', 'ge': 'min', 'le': 'max'}[c['op']],
                            c['value'] * SCALE, actual, unit=f'{unit}/{SCALE}', label=field)

        for field, value in [('currency', limits['currency']), ('condition', specs['condition'])]:
            if field == 'condition' and value == 'unspecified':
                continue
            fact = published.get(field)
            enum('required_' + field, [{'op': 'eq', 'value': value}],
                 fact['value'] if fact and fact['unit'] is None else None, field, policy=True)

        # These predicates deliberately retain the checker's semantic scope. Z3
        # reasons from their values; it does not independently identify a product.
        for field in ('product_identity', 'approved_supplier', 'category'):
            status = checks.get(field, {}).get('status')
            observed = {'supported': True, 'contradicted': False}.get(status)
            require('policy_' + field, FieldType.BOOL, 'eq', True, observed, label=field, policy=True)
        total = checks.get('max_total_cents', {}).get('observed')
        require('policy_total_cents', FieldType.MONEY, 'max', limits['max_total_cents'],
                total if type(total) is int and total >= 0 else None, unit='cents', label='max_total_cents', policy=True)
        if specs.get('unsupported_requirements'):
            require('unsupported_requirements', FieldType.BOOL, 'eq', True, None,
                    label='unsupported_requirements')

        spec = Spec(fields=fields, constraints=constraints, product_type=specs['item'])
        spec.spec_hash = spec.compute_hash()
        consistency = spec_satisfiable(spec)
        if consistency['status'] != 'sat':
            output.update(status='inconsistent_requirements' if consistency['status'] == 'unsat' else 'unknown',
                          reason='The compiled requirements have no proven consistent model.',
                          spec_hash=spec.spec_hash, conflicting_requirements=consistency.get('core'))
            return output
        candidate = Candidate(listing_id=report['candidate_id'], sku=report.get('sku') or report['candidate_id'],
                              seller='', price_cents=0, facts=evidence,
                              snapshot_id=report['evidence']['sha256'], url=report['evidence']['url'])
        queries = []
        proof = verify(candidate, spec, solver_log=queries)
        status = proof.status
        # Missing observations must never become proof merely because a bound is
        # true for every value in the field domain (e.g. an unknown price >= 0).
        contradicted = any(c.get('status') == 'contradicted' for c in checks.values())
        if missing and not contradicted and status in ('proven', 'rejected'):
            status = 'unknown'
        output.update(status=status, solver_status=proof.status, spec_hash=proof.spec_hash,
                      facts_hash=proof.facts_hash, missing_fields=sorted(set(missing)),
                      counterexample=proof.counterexample, solver_queries=queries,
                      assumptions=['Published source values', 'Product identity and category mapping',
                                   'Configured supplier identity, quantity, tax and freight'],
                      reason={'proven': 'Published evidence entails every compiled requirement and policy condition.',
                              'rejected': 'Published evidence does not satisfy the compiled requirements.',
                              'unknown': 'Missing or unsupported evidence prevents a complete proof.',
                              'vacuous': 'Inconsistent evidence cannot establish a proof.'}.get(status, 'No proof established.'))
    except (ValueError, KeyError, TypeError, ArithmeticError):
        log.exception('Unable to compile listing proof')
        output.update(status='unknown', reason='The evidence could not be represented exactly; no proof established.')
    return output


def bind_proof(proof, requirements_id):
    proof['requirements_id'] = requirements_id
    proof['receipt_hash'] = sha256_of({key: value for key, value in proof.items() if key != 'receipt_hash'})
    return proof
