"""Vacuity, entailment, satisfiability, equivalence, refinement, boundary examples.

A candidate is proven only when its facts (plus approved rules) are satisfiable on their
own (invariant 6) and facts ∧ rules ∧ ¬hard_spec is unsat. Every other solver outcome,
including unknown and timeout, is a non-purchase (invariant 5).
"""
from __future__ import annotations

from z3 import Bool, Not, Solver, Z3Exception, sat, unknown, unsat

from . import units
from .compiler import (
    NUMERIC, Rule, compile_conditional, compile_constraint, compile_rules, domains,
    encode_facts, fact_is_usable, hard_constraints, hard_spec, make_vars, model_to_dict,
)
from .types import Candidate, Fact, ProofResult, Spec, sha256_of

DEFAULT_TIMEOUT_MS = 2000


def facts_hash(facts: list[Fact]) -> str:
    return sha256_of([f.model_dump(mode="json") for f in facts])


def blocking_unknowns(facts: list[Fact], spec: Spec) -> list[str]:
    out = []
    for name in spec.hard_fields():
        f = spec.fields[name]
        if not any(ft.field == name and fact_is_usable(ft, f) for ft in facts):
            out.append(name)
    return out


def _check(s: Solver):
    try:
        return s.check()
    except Z3Exception:
        return unknown


def verify(cand: Candidate, spec: Spec, rules: list[Rule] | None = None,
           timeout_ms: int = DEFAULT_TIMEOUT_MS, exclude_fields: set[str] = frozenset(),
           solver_log: list | None = None) -> ProofResult:
    rules = rules or []
    base = dict(candidate_sku=cand.sku, spec_hash=spec.spec_hash, facts_hash=facts_hash(cand.facts))
    v = make_vars(spec)
    s = Solver()
    s.set("timeout", timeout_ms)
    s.add(domains(spec, v))
    s.add(encode_facts(cand.facts, spec, v))
    s.add(compile_rules(rules, spec, v))

    r = _check(s)                                    # 1. vacuity check
    _log(solver_log, cand.sku, "vacuity", s, r)
    if r == unsat:
        return ProofResult(status="vacuous", **base)
    if r != sat:
        return ProofResult(status="unknown", **base)

    s.add(Not(hard_spec(spec, v, exclude_fields)))   # 2. entailment: facts ∧ rules ∧ ¬spec
    r = _check(s)
    _log(solver_log, cand.sku, "entailment", s, r)
    if r == unsat:
        return ProofResult(status="proven", **base)
    if r == sat:
        return ProofResult(status="rejected", counterexample=model_to_dict(s.model(), spec, v),
                           blocking_unknowns=[f for f in blocking_unknowns(cand.facts, spec)
                                              if f not in exclude_fields], **base)
    return ProofResult(status="unknown", **base)     # timeout = reject


def _log(solver_log, sku, kind, s: Solver, r) -> None:
    if solver_log is not None:
        solver_log.append({"sku": sku, "query": kind, "smt2": s.sexpr(), "result": str(r)})


def verify_with_accepted_risk(cand: Candidate, spec: Spec, accepted: list[str],
                              rules: list[Rule] | None = None) -> ProofResult:
    """Re-verify with only the accepted unknown fields removed (modes 1 and 2)."""
    full = verify(cand, spec, rules)
    if full.status != "rejected" or not full.blocking_unknowns:
        return full
    if not set(accepted) <= set(full.blocking_unknowns):
        return full                                  # only unknown fields can be accepted
    partial = verify(cand, spec, rules, exclude_fields=set(accepted))
    if partial.status != "proven":
        return full
    return partial.model_copy(update={"status": "risk_accepted", "accepted_risks": sorted(accepted)})


def necessary_unknowns(cand: Candidate, spec: Spec, rules: list[Rule] | None = None) -> list[str]:
    """The unknown fields that actually block the proof (e.g. an unknown return window doesn't matter when
    the policy rule that mentions it can't fire). Used to keep accept-risk offers minimal."""
    unknown = blocking_unknowns(cand.facts, spec)
    if verify(cand, spec, rules, exclude_fields=set(unknown)).status != "proven":
        return []                                        # something known fails too: risk can't fix it
    needed = []
    for f in unknown:
        if verify(cand, spec, rules, exclude_fields=set(unknown) - {f}).status != "proven":
            needed.append(f)
    return needed or unknown


# ---- Spec-level checks ---------------------------------------------------------------

def describe(c, spec: Spec) -> str:
    if hasattr(c, "when"):
        return f"if {describe(c.when, spec)} then {describe(c.then, spec)}"
    f = spec.fields.get(c.field)
    val = c.value
    if f is not None and f.type in NUMERIC and isinstance(val, int) and not isinstance(val, bool):
        val = units.display(val, f.display_unit, f.base_unit)
    return f"{c.field} {c.op} {val}"


def spec_satisfiable(spec: Spec, rules: list[Rule] | None = None, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict:
    v = make_vars(spec)
    s = Solver()
    s.set("timeout", timeout_ms)
    s.set("core.minimize", True)
    s.add(domains(spec, v))
    s.add(compile_rules(rules or [], spec, v))
    hard = hard_constraints(spec)
    labels = {}
    for i, c in enumerate(hard):
        tag = Bool(f"c_{i}")
        labels[str(tag)] = c
        s.assert_and_track(compile_constraint(c, spec, v), tag)
    for i, r in enumerate(spec.conditional):
        tag = Bool(f"r_{i}")
        labels[str(tag)] = r
        s.assert_and_track(compile_conditional(r, spec, v), tag)
    r = _check(s)
    if r == sat:
        return {"status": "sat", "example": model_to_dict(s.model(), spec, v), "core": None}
    if r == unsat:
        core = [describe(labels[str(t)], spec) for t in s.unsat_core()]
        return {"status": "unsat", "example": None, "core": core,
                "core_constraints": [labels[str(t)] for t in s.unsat_core()]}
    return {"status": "unknown", "example": None, "core": None}


def _merged(s1: Spec, s2: Spec) -> tuple[Spec | None, list[str]]:
    fields = dict(s1.fields)
    conflicts = []
    for name, f in s2.fields.items():
        if name in fields and fields[name].model_dump(exclude={"registry_status", "measures", "vocab_ref"}) != \
                f.model_dump(exclude={"registry_status", "measures", "vocab_ref"}):
            conflicts.append(name)
        fields.setdefault(name, f)
    if conflicts:
        return None, conflicts
    return Spec(fields=fields, constraints=[]), []


def _difference(a: Spec, b: Spec, merged: Spec, timeout_ms: int) -> dict | None:
    """A product allowed by `a` but not by `b`, or None if there is none."""
    v = make_vars(merged)
    s = Solver()
    s.set("timeout", timeout_ms)
    s.add(domains(merged, v))
    s.add(hard_spec(a.model_copy(update={"fields": merged.fields}), v))
    s.add(Not(hard_spec(b.model_copy(update={"fields": merged.fields}), v)))
    r = _check(s)
    if r == sat:
        return model_to_dict(s.model(), merged, v)
    if r == unsat:
        return None
    raise TimeoutError("solver returned unknown")


def equivalence(s1: Spec, s2: Spec, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict:
    """Translation equivalence: s1 ∧ ¬s2, then s2 ∧ ¬s1."""
    merged, conflicts = _merged(s1, s2)
    if merged is None:
        return {"equivalent": False, "field_conflicts": conflicts, "only_first": None, "only_second": None}
    try:
        a = _difference(s1, s2, merged, timeout_ms)
        b = _difference(s2, s1, merged, timeout_ms)
    except TimeoutError:
        return {"equivalent": False, "field_conflicts": [], "only_first": None, "only_second": None,
                "unknown": True}
    return {"equivalent": a is None and b is None, "field_conflicts": [], "only_first": a, "only_second": b}


def refinement(new: Spec, old: Spec, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> dict:
    """new ∧ ¬old: sat means the edit loosens the spec (full re-approval)."""
    merged, conflicts = _merged(new, old)
    if merged is None:
        return {"loosens": True, "example": None, "field_conflicts": conflicts}
    try:
        ex = _difference(new, old, merged, timeout_ms)
    except TimeoutError:
        return {"loosens": True, "example": None, "field_conflicts": [], "unknown": True}
    return {"loosens": ex is not None, "example": ex, "field_conflicts": []}


def boundary_examples(spec: Spec, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> list[dict]:
    """For each numeric bound: an at-the-limit example the spec allows, shown to the user."""
    out = []
    v = make_vars(spec)
    hs = hard_spec(spec, v)
    for c in hard_constraints(spec):
        f = spec.fields[c.field]
        if f.type not in NUMERIC or c.op not in ("min", "max", "before"):
            continue
        s = Solver()
        s.set("timeout", timeout_ms)
        s.add(domains(spec, v))
        s.add(hs)
        s.add(v[c.field] == c.value)
        r = _check(s)
        shown = units.display(c.value, f.display_unit, f.base_unit)
        word = {"max": "at most", "before": "on or before", "min": "at least"}[c.op]
        said = f'You said "{c.source_text}".' if c.origin == "request" else \
            f"From your answer, {f.measures} must be {word} {shown}."
        out.append({
            "field": c.field, "op": c.op, "bound": c.value, "bound_display": shown,
            "allowed": r == sat, "source_text": c.source_text,
            "example": model_to_dict(s.model(), spec, v) if r == sat else None,
            "question": f"{said} A product with {f.measures} of exactly {shown} "
                        f"is currently allowed ({word} {shown}). Is exactly {shown} acceptable?",
        })
    return out


PAIR_IGNORED = {"max_total_price_cents", "rating_x10"}   # price and rating may differ in a counterfactual pair


def counterfactual_pair(cands: list[Candidate], field: str, spec: Spec) -> tuple[Candidate, Candidate] | None:
    """Two real candidates whose known facts agree on every field except `field`."""
    def known(c: Candidate) -> dict:
        d = {}
        for ft in c.facts:
            f = spec.fields.get(ft.field)
            if f is not None and fact_is_usable(ft, f) and len(ft.values) == 1:
                d[ft.field] = ft.values[0]
        return d
    ks = [(c, known(c)) for c in cands]
    for i, (a, ka) in enumerate(ks):
        for b, kb in ks[i + 1:]:
            if field not in ka or field not in kb or ka[field] == kb[field]:
                continue
            vocab = spec.fields[field].vocab_ref
            same = {field} | {n for n, f in spec.fields.items() if vocab and f.vocab_ref == vocab}
            rest_a, rest_b = set(ka) - same - PAIR_IGNORED, set(kb) - same - PAIR_IGNORED
            if rest_a and rest_a == rest_b and all(ka[k] == kb[k] for k in rest_a):
                return a, b
    return None
