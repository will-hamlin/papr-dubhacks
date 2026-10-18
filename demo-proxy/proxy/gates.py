"""Deterministic gates. Pure functions: same inputs, same decision. Fail closed.

1. authorize: may this user place an order right now?
2. check_policy: does the proposed order break company policy?
3. build_search: turn an accepted proposal into typed specs, integer weights + priority, and spending limits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation

from .models import Constraint, Policy, SpecProposal, User

MAX_QUANTITY = 100
MAX_CONSTRAINTS = 20


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def normalize_category(category: str) -> str:
    return category.strip().lower().replace("-", "_").replace(" ", "_")


def ceiling_cents(user: User, policy: Policy, spent_today: int, spent_on_job: int) -> int:
    """Most the user may spend on one order right now, tax and freight included."""
    caps = [user.spend_limit_cents, policy.daily_cap_cents - spent_today]
    if user.job_number:
        caps.append(policy.per_job_cap_cents - spent_on_job)
    return max(0, min(caps))


def authorize(user: User | None, policy: Policy, spent_today: int, spent_on_job: int) -> list[str]:
    """User-level checks. Empty list = authorized."""
    if user is None:
        return ["unknown user"]
    reasons = []
    if not user.purchasing_enabled:
        reasons.append(f"purchasing is disabled for {user.name} ({user.role})")
    if user.spend_limit_cents <= 0:
        reasons.append(f"{user.name} has a $0.00 spend limit")
    if spent_today >= policy.daily_cap_cents:
        reasons.append(f"company daily cap {money(policy.daily_cap_cents)} already reached")
    if user.job_number and spent_on_job >= policy.per_job_cap_cents:
        reasons.append(f"job {user.job_number} cap {money(policy.per_job_cap_cents)} already reached")
    return reasons


def _keyword_hits(text: str, policy: Policy) -> list[tuple[str, str]]:
    t = text.lower()
    hits = []
    for category, words in policy.blocked_keywords.items():
        for w in words:
            if re.search(r"(?<![a-z])" + re.escape(w.lower()) + r"(?![a-z])", t):
                hits.append((category, w))
    return hits


def check_policy(proposal: SpecProposal, request_text: str, policy: Policy) -> list[str]:
    """Company-policy checks on the proposed order. Empty list = compliant.

    The category comes from the (probabilistic) parser, so blocked keywords are also matched
    against the raw request and the proposal text: either one is enough to block.
    """
    blocked = {normalize_category(c) for c in policy.blocked_categories}
    reasons = []
    if normalize_category(proposal.category) in blocked:
        reasons.append(f"category '{proposal.category}' is blocked by company policy")
    searchable = " ".join([request_text, proposal.item] + [f"{c.field} {c.value}" for c in proposal.constraints])
    for category, word in _keyword_hits(searchable, policy):
        if normalize_category(category) in blocked:
            reasons.append(f"'{word}' falls under blocked category '{category}'")
    if not 1 <= proposal.quantity <= MAX_QUANTITY:
        reasons.append(f"quantity {proposal.quantity} is outside 1-{MAX_QUANTITY}")
    return list(dict.fromkeys(reasons))


# unit -> (base unit, factor). Numbers are compiled to integers in the base unit; no floats reach the engine.
UNITS: dict[str, tuple[str, Decimal]] = {
    "mm": ("mm", Decimal(1)), "cm": ("mm", Decimal(10)), "m": ("mm", Decimal(1000)),
    "in": ("mm", Decimal("25.4")), "ft": ("mm", Decimal("304.8")),
    "g": ("g", Decimal(1)), "kg": ("g", Decimal(1000)), "oz": ("g", Decimal("28.349523125")),
    "lb": ("g", Decimal("453.59237")),
    "MB": ("MB", Decimal(1)), "GB": ("MB", Decimal(1000)), "TB": ("MB", Decimal(1000000)),
    "W": ("W", Decimal(1)), "V": ("mV", Decimal(1000)), "mAh": ("mAh", Decimal(1)),
    "Hz": ("Hz", Decimal(1)), "GHz": ("Hz", Decimal(1000000000)), "count": ("count", Decimal(1)),
}
OP_TEXT = {"eq": "=", "ne": "≠", "ge": "≥", "le": "≤"}
# Round toward the user's side: "at least 15.6 in" must not become a smaller integer bound.
OP_ROUNDING = {"ge": ROUND_CEILING, "le": ROUND_FLOOR, "eq": ROUND_HALF_UP, "ne": ROUND_HALF_UP}


@dataclass
class Compiled:
    constraints: list[dict]
    english: list[str]
    errors: list[str]
    notes: list[str]


def _field_name(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")[:40] or "unnamed"


def compile_constraints(items: list[Constraint], limit: int = 20) -> Compiled:
    """Typed proposal constraints -> integer/enum constraints the engine can encode linearly.

    Unreadable values fail closed: a required one is an error, an optional one is dropped with a note.
    Numeric bounds that contradict each other are an error (they would make every check pass vacuously).
    """
    out, english, errors, notes = [], [], [], []
    for c in items[:limit]:
        name = _field_name(c.field)
        tag = "required" if c.required else "preferred"
        if c.unit is None:
            value = c.value.strip()[:200]
            if not value or c.op in ("ge", "le"):
                (errors if c.required else notes).append(
                    f"constraint '{c.field} {c.op} {c.value}' has no unit for a numeric comparison")
                continue
            out.append({"field": name, "op": c.op, "value": value, "unit": None, "required": c.required})
            english.append(f"{name.replace('_', ' ')} {OP_TEXT[c.op]} {value} ({tag})")
            continue
        try:
            number = Decimal(c.value.strip().replace(",", ""))
            if not number.is_finite():
                raise InvalidOperation
        except InvalidOperation:
            (errors if c.required else notes).append(f"could not read '{c.value}' as a number for {c.field}")
            continue
        base, factor = UNITS[c.unit]
        scaled = (number * factor).to_integral_value(rounding=OP_ROUNDING[c.op])
        if scaled != number * factor and c.op in ("eq", "ne"):
            notes.append(f"{c.field} {c.value} {c.unit} rounded to {scaled} {base}")
        out.append({"field": name, "op": c.op, "value": int(scaled), "unit": base, "required": c.required})
        english.append(f"{name.replace('_', ' ')} {OP_TEXT[c.op]} {c.value} {c.unit} ({tag})")
    errors += _contradictions(out)
    return Compiled(out, english, errors, notes)


def _contradictions(constraints: list[dict]) -> list[str]:
    bounds: dict[tuple, dict] = {}
    for c in constraints:
        if c["unit"] is None or not c["required"]:
            continue
        b = bounds.setdefault((c["field"], c["unit"]), {"lo": None, "hi": None, "eq": set(), "ne": set()})
        v = c["value"]
        if c["op"] == "ge":
            b["lo"] = v if b["lo"] is None else max(b["lo"], v)
        elif c["op"] == "le":
            b["hi"] = v if b["hi"] is None else min(b["hi"], v)
        else:
            b[c["op"]].add(v)
    problems = []
    for (fld, unit), b in bounds.items():
        lo, hi = b["lo"], b["hi"]
        for v in b["eq"]:
            lo = v if lo is None else max(lo, v)
            hi = v if hi is None else min(hi, v)
        if len(b["eq"]) > 1 or (lo is not None and hi is not None and lo > hi) or (b["eq"] & b["ne"]):
            problems.append(f"contradictory requirements for {fld} (no value in {unit} can satisfy all of them)")
    return problems


def priority_order(weights: dict[str, int]) -> list[str]:
    """Lexicographic tie-break order: highest weight first, then name."""
    return [k for k, _ in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))]


def normalize_weights(proposal: SpecProposal, default: dict[str, int]) -> dict[str, int]:
    """Integer weights that sum to exactly 100 (largest-remainder rounding)."""
    raw: dict[str, int] = {}
    for w in proposal.weights:
        raw[w.criterion] = raw.get(w.criterion, 0) + max(0, w.weight)
    raw = {k: v for k, v in raw.items() if v > 0}
    if not raw:
        raw = dict(default)
    total = sum(raw.values())
    floors = {k: v * 100 // total for k, v in raw.items()}
    remainders = sorted(raw, key=lambda k: (-(raw[k] * 100 % total), k))
    for k in remainders[: 100 - sum(floors.values())]:
        floors[k] += 1
    return dict(sorted(floors.items(), key=lambda kv: (-kv[1], kv[0])))


@dataclass
class Search:
    specs: dict
    weights: dict[str, int]
    priority: list[str]
    limits: dict
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def build_search(proposal: SpecProposal, user: User, policy: Policy, spent_today: int, spent_on_job: int,
                 default_weights: dict[str, int]) -> Search:
    ceiling = ceiling_cents(user, policy, spent_today, spent_on_job)
    notes = []
    max_total = ceiling
    stated = proposal.stated_budget_cents
    if stated is not None and stated >= 0:
        if stated > ceiling:
            notes.append(f"request mentions {money(stated)}, which exceeds what {user.name} is authorized to "
                         f"spend right now ({money(ceiling)}); search capped at {money(ceiling)}")
        else:
            max_total = stated
            notes.append(f"search capped at the request's own budget {money(stated)}")
    compiled = compile_constraints(proposal.constraints, MAX_CONSTRAINTS)
    notes += compiled.notes
    specs = {"item": proposal.item[:200], "category": normalize_category(proposal.category),
             "quantity": proposal.quantity, "condition": proposal.condition,
             "constraints": compiled.constraints, "english": compiled.english}
    limits = {
        "currency": "USD",
        "max_total_cents": max_total,
        "total_formula": "sum(unit_price_cents * quantity) + round_half_up(subtotal * tax_rate_bp / 10000) "
                         "+ sum(freight_cents_by_supplier[s] for each distinct supplier)",
        "tax_rate_bp": policy.tax_rate_bp,
        "freight_cents_by_supplier": {s: policy.freight_cents_by_supplier[s] for s in policy.approved_suppliers
                                      if s in policy.freight_cents_by_supplier},
        "approved_suppliers": [s for s in policy.approved_suppliers if s in policy.freight_cents_by_supplier],
        "blocked_categories": [normalize_category(c) for c in policy.blocked_categories],
    }
    weights = normalize_weights(proposal, default_weights)
    return Search(specs, weights, priority_order(weights), limits, notes, compiled.errors)
