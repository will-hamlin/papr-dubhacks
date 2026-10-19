"""Compile product requirements into constraints for the verifier."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from .models import Constraint, SpecProposal

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
OP_TEXT = {"eq": "=", "ne": "\u2260", "ge": "\u2265", "le": "\u2264"}
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
    if len(items) > limit:
        errors.append(f"request has {len(items)} constraints; at most {limit} can be verified; none beyond the limit may be ignored")
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



def normalize_category(category: str) -> str:
    return category.strip().lower().replace("-", "_").replace(" ", "_")


def check_policy(proposal: SpecProposal, request_text: str, limits: dict) -> list[str]:
    blocked = {normalize_category(c) for c in limits["blocked_categories"]}
    reasons = []
    if normalize_category(proposal.category) in blocked:
        reasons.append(f"category '{proposal.category}' is blocked by company policy")
    searchable = " ".join([request_text, proposal.item] + [f"{c.field} {c.value}" for c in proposal.constraints])
    for category, words in limits.get("blocked_keywords", {}).items():
        if normalize_category(category) in blocked:
            for word in words:
                if re.search(r"(?<![a-z])" + re.escape(word.lower()) + r"(?![a-z])", searchable.lower()):
                    reasons.append(f"'{word}' falls under blocked category '{category}'")
    if not 1 <= proposal.quantity <= 100:
        reasons.append(f"quantity {proposal.quantity} is outside 1-100")
    return list(dict.fromkeys(reasons))


def build_search(proposal: SpecProposal, authorized_limits: dict, default_weights: dict) -> Search:
    limits = dict(authorized_limits)
    notes = []
    stated = proposal.stated_budget_cents
    if stated is not None and stated >= 0:
        ceiling = limits["max_total_cents"]
        limits["max_total_cents"] = min(ceiling, stated)
        notes.append(f"request budget {stated} cents; search capped at {limits['max_total_cents']} cents")
    limits.pop("blocked_keywords", None)
    limits["total_formula"] = ("sum(unit_price_cents * quantity) + round_half_up(subtotal * tax_rate_bp / 10000) "
                               "+ sum(freight_cents_by_supplier[s] for each distinct supplier)")
    compiled = compile_constraints(proposal.constraints, 20)
    compiled.errors.extend(f"unsupported request requirement: {value}" for value in proposal.unsupported_requirements)
    specs = {"item": proposal.item[:200], "category": normalize_category(proposal.category),
             "quantity": proposal.quantity, "condition": proposal.condition,
             "constraints": compiled.constraints, "english": compiled.english,
             "unsupported_requirements": proposal.unsupported_requirements}
    weights = normalize_weights(proposal, default_weights)
    return Search(specs, weights, priority_order(weights), limits, notes + compiled.notes, compiled.errors)
