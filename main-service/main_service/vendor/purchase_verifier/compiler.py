"""Constraint -> Z3 expression. The only code that emits solver constraints (invariant 3).

Direction lives in the field name and the operator; the operator comes from the slot
schema, never from a model. Anything unexpected raises: a constraint that can't be
compiled exactly must never be approximated.
"""
from __future__ import annotations

from pydantic import BaseModel
from z3 import And, Bool, BoolRef, BoolVal, Implies, Int, Not, Or

from .types import ALLOWED_OPS, Conditional, Constraint, Fact, FieldDef, FieldType, Spec

NUMERIC = (FieldType.QUANTITY, FieldType.MONEY, FieldType.DATE)
CODED = (FieldType.ENUM, FieldType.IDENTITY)
BOOLEAN = (FieldType.BOOL, FieldType.COMPAT)


class CompileError(ValueError):
    pass


class Rule(BaseModel):
    """An H0-approved background rule: `when` (optional) implies `then`."""
    when: Constraint | None = None
    then: Constraint
    note: str = ""


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def make_vars(spec: Spec, prefix: str = "") -> dict:
    v = {}
    for f in spec.fields.values():
        if f.type == FieldType.SUBJECTIVE:
            continue
        name = prefix + f.name
        v[f.name] = Bool(name) if f.type in BOOLEAN else Int(name)
    return v


def domains(spec: Spec, v: dict) -> list[BoolRef]:
    """Enum/identity vars must hold a valid code; numeric quantities are non-negative."""
    out = []
    for f in spec.fields.values():
        if f.name not in v:
            continue
        if f.type in CODED:
            out.append(And(v[f.name] >= 0, v[f.name] < len(f.options)))
        elif f.type in NUMERIC:
            out.append(v[f.name] >= 0)
    return out


def _code(f: FieldDef, s) -> int:
    if not isinstance(s, str) or s not in f.options:
        raise CompileError(f"{f.name}: {s!r} is not one of the field's options")
    return f.options.index(s)


def check_constraint(c: Constraint, spec: Spec) -> None:
    """Raise CompileError unless the constraint is well-typed for its field."""
    if c.field not in spec.fields:
        raise CompileError(f"unknown field {c.field!r}")
    f = spec.fields[c.field]
    if c.op not in ALLOWED_OPS[f.type.value]:
        raise CompileError(f"operator {c.op!r} not allowed on {f.type.value} field {f.name}")
    if f.type in NUMERIC:
        if not _is_int(c.value):
            raise CompileError(f"{f.name}: numeric constraint needs an int in base units")
    elif f.type in CODED:
        if c.op == "eq":
            _code(f, c.value)
        else:
            if not isinstance(c.value, list) or not c.value:
                raise CompileError(f"{f.name}: {c.op} needs a non-empty list of options")
            for s in c.value:
                _code(f, s)
    elif f.type == FieldType.BOOL:
        if not isinstance(c.value, bool):
            raise CompileError(f"{f.name}: boolean constraint needs true/false")
    elif f.type == FieldType.COMPAT:
        if c.value is not True:
            raise CompileError(f"{f.name}: compatibility constraint value must be true")


def compile_constraint(c: Constraint, spec: Spec, v: dict) -> BoolRef:
    check_constraint(c, spec)
    x, f = v[c.field], spec.fields[c.field]
    match c.op:
        case "min":
            return x >= c.value
        case "max":
            return x <= c.value
        case "before":
            return x <= c.value
        case "eq":
            if f.type in CODED:
                return x == _code(f, c.value)
            return x == c.value
        case "ne":
            return x != c.value
        case "in":
            return Or([x == _code(f, s) for s in c.value])
        case "not_in":
            return And([x != _code(f, s) for s in c.value])
        case "contains":
            return x == True  # noqa: E712  (z3 expression, not a Python comparison)
    raise CompileError(f"unknown operator {c.op!r}")


def hard_constraints(spec: Spec) -> list[Constraint]:
    out = []
    for c in spec.constraints:
        if c.tier in ("hard", "essential"):
            if spec.fields.get(c.field) and spec.fields[c.field].type == FieldType.SUBJECTIVE:
                raise CompileError(f"subjective field {c.field} cannot be a hard constraint")
            out.append(c)
    return out


def compile_conditional(r: Conditional, spec: Spec, v: dict) -> BoolRef:
    """when ⇒ then. Both halves go through the same typed checks as any constraint."""
    return Implies(compile_constraint(r.when, spec, v), compile_constraint(r.then, spec, v))


def hard_spec(spec: Spec, v: dict, exclude_fields: set[str] = frozenset()) -> BoolRef:
    exprs = [compile_constraint(c, spec, v) for c in hard_constraints(spec) if c.field not in exclude_fields]
    exprs += [compile_conditional(r, spec, v) for r in spec.conditional
              if not set(r.fields()) & set(exclude_fields)]
    return And(exprs) if exprs else BoolVal(True)


def compile_rules(rules: list[Rule], spec: Spec, v: dict) -> list[BoolRef]:
    """Background rules only apply when every field they mention is in this spec."""
    out = []
    for r in rules:
        fields = [r.then.field] + ([r.when.field] if r.when else [])
        if not all(f in spec.fields for f in fields):
            continue
        then = compile_constraint(r.then, spec, v)
        out.append(Implies(compile_constraint(r.when, spec, v), then) if r.when else then)
    return out


def fact_is_usable(fact: Fact, f: FieldDef) -> bool:
    """Unknown, out-of-list or wrongly typed values are left free (they fail safe)."""
    if fact.values is None or not fact.values:
        return False
    if f.type == FieldType.SUBJECTIVE:
        return False
    if f.type in CODED:
        return all(isinstance(x, str) and x in f.options for x in fact.values)
    if f.type in BOOLEAN:
        return all(isinstance(x, bool) for x in fact.values)
    return all(_is_int(x) for x in fact.values)


def encode_fact_values(f: FieldDef, x, values: list) -> BoolRef:
    enc = (lambda s: f.options.index(s)) if f.type in CODED else (lambda s: s)
    return Or([x == enc(val) for val in values])


def encode_facts(facts: list[Fact], spec: Spec, v: dict) -> list[BoolRef]:
    out = []
    for fact in facts:
        if fact.field not in v or not fact_is_usable(fact, spec.fields[fact.field]):
            continue
        out.append(encode_fact_values(spec.fields[fact.field], v[fact.field], fact.values))
    return out


def model_to_dict(model, spec: Spec, v: dict) -> dict:
    out = {}
    for name, x in v.items():
        val = model.eval(x, model_completion=False)
        if val.eq(x):             # unconstrained by the model
            continue
        f = spec.fields[name]
        if f.type in BOOLEAN:
            out[name] = bool(val)
        elif f.type in CODED:
            i = val.as_long()
            out[name] = f.options[i] if 0 <= i < len(f.options) else i
        else:
            out[name] = val.as_long()
    return out


def negate(expr: BoolRef) -> BoolRef:
    return Not(expr)
