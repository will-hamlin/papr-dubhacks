"""Typed contract for every module: fields, constraints, specs, facts, candidates, carts.

All quantities that reach the solver are ints in a field's base unit (invariant 13).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator

Op = Literal["min", "max", "eq", "ne", "in", "not_in", "before", "contains"]
Tier = Literal["hard", "essential", "preference", "unverifiable"]
Origin = Literal["request", "essential_answer", "profile_rule", "profile_pref", "agent_answer", "company_policy"]
Mode = Literal["supervised", "purchase_only", "autonomous"]
MODE_RANK = {"supervised": 1, "purchase_only": 2, "autonomous": 3}

# Operators each field type accepts. "range" is expressed as a min plus a max constraint.
ALLOWED_OPS: dict[str, set[str]] = {
    "quantity": {"min", "max", "eq", "ne"},
    "money": {"max", "min", "eq"},
    "enum": {"in", "not_in", "eq"},
    "bool": {"eq"},
    "identity": {"in", "not_in", "eq"},
    "date": {"before", "min", "max"},
    "compat": {"contains"},
    "subjective": set(),
}


class FieldType(str, Enum):
    QUANTITY = "quantity"
    MONEY = "money"
    ENUM = "enum"
    BOOL = "bool"
    IDENTITY = "identity"
    DATE = "date"
    COMPAT = "compat"
    SUBJECTIVE = "subjective"


def canonical_json(obj: Any) -> str:
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_of(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


class FieldDef(BaseModel):
    name: str                      # direction + user-facing unit in the name: max_cable_length_mm
    type: FieldType
    measures: str                  # "length of the cable from plug to connector"
    dimension: str | None = None   # "[length]"
    base_unit: str | None = None   # solver unit (exact integer): "um", "cents", "mW", "days"
    display_unit: str | None = None  # unit the user sees: "mm"
    options: list[str] | None = None  # ENUM / IDENTITY
    vocab_ref: str | None = None
    registry_status: Literal["new", "approved"] = "new"

    @model_validator(mode="after")
    def _check(self) -> "FieldDef":
        if self.type in (FieldType.ENUM, FieldType.IDENTITY):
            if not self.options:
                raise ValueError(f"{self.name}: enum/identity field needs options")
            if len(set(self.options)) != len(self.options):
                raise ValueError(f"{self.name}: duplicate options")
        elif self.options:
            raise ValueError(f"{self.name}: only enum/identity fields carry options")
        if self.type in (FieldType.QUANTITY, FieldType.MONEY, FieldType.DATE) and not self.base_unit:
            raise ValueError(f"{self.name}: numeric field needs a base_unit")
        return self


class Constraint(BaseModel):
    field: str
    op: Op
    value: int | bool | list[str] | str
    tier: Tier
    origin: Origin
    source_text: str

    @field_validator("value")
    @classmethod
    def _no_float(cls, v):
        if isinstance(v, float):
            raise ValueError("floats are not allowed in constraints (invariant 13)")
        return v


class Conditional(BaseModel):
    """A hard requirement that applies only when `when` holds: when ⇒ then.

    Example (company policy): a low-trust seller must offer at least 30-day returns.
    """
    when: Constraint
    then: Constraint
    origin: Origin
    source_text: str

    def fields(self) -> list[str]:
        return [self.when.field, self.then.field]


class Spec(BaseModel):
    fields: dict[str, FieldDef]
    constraints: list[Constraint]
    conditional: list[Conditional] = []
    preference_order: list[str] = []
    mode: Mode = "supervised"
    status: Literal["draft", "approved"] = "draft"
    spec_hash: str | None = None
    product_type: str = ""
    unverifiable_ok: list[str] = []      # subjective fields the user marked "OK to leave unverified"
    any_fields: list[str] = []           # essential questions the user answered "any"
    assumptions: list[str] = []          # stricter-reading choices (modes 2 and 3)

    def hashable(self) -> dict:
        d = self.model_dump(mode="json")
        d.pop("spec_hash"); d.pop("status")
        return d

    def compute_hash(self) -> str:
        return sha256_of(self.hashable())

    def hard_constraints(self) -> list[Constraint]:
        return [c for c in self.constraints if c.tier in ("hard", "essential")]

    def hard_fields(self) -> list[str]:
        out: list[str] = []
        for c in self.hard_constraints():
            if c.field not in out:
                out.append(c.field)
        for r in self.conditional:
            for f in r.fields():
                if f not in out:
                    out.append(f)
        return out

    def determines(self, field: str) -> bool:
        return any(c.field == field and c.op in ("eq", "in") and c.tier in ("hard", "essential")
                   for c in self.constraints) or field in self.any_fields


FactValue = int | bool | str


class Fact(BaseModel):
    field: str
    values: list[FactValue] | None   # 1 value = known; >1 = disjunction; None = unknown
    source_url: str
    span: str | None = None
    quote_checked: bool = False
    method: Literal["jsonld", "api", "regex", "llm_span", "manufacturer", "checkout_api", "policy"]
    path: str | None = None          # structured-data path the value was read from
    sources: list[str] = []          # merged facts: every source URL that contributed
    methods: list[str] = []          # merged facts: every method that contributed

    @field_validator("values")
    @classmethod
    def _no_float(cls, v):
        if v is not None and any(isinstance(x, float) for x in v):
            raise ValueError("floats are not allowed in facts (invariant 13)")
        return v


class Candidate(BaseModel):
    listing_id: str
    sku: str
    seller: str
    title: str = ""
    price_cents: int
    shipping_cents: int = 0
    shipping_known: bool = True      # False: total unknown until a checkout quote; carts refuse to build
    facts: list[Fact]
    snapshot_id: str
    flags: list[str] = []
    variant: dict[str, str] = {}
    url: str = ""
    raw_facts: list[Fact] = []       # per-source facts before cross-source merging
    flag_quotes: list[str] = []      # screening quotes behind `flags`
    soft: dict = {}                  # soft, unproven ranking signals (e.g. review_quality); never in the spec
    mfr_url: str | None = None
    page_url: str | None = None      # retailer page for people; `url` is what re-verification fetches
    brand: str = ""
    category: str = ""


ProofStatus = Literal["proven", "risk_accepted", "rejected", "vacuous", "unknown", "challenged"]


class ProofResult(BaseModel):
    candidate_sku: str
    status: ProofStatus
    counterexample: dict | None = None
    blocking_unknowns: list[str] = []
    unsat_core: list[str] | None = None
    accepted_risks: list[str] = []
    challenge_quote: str | None = None
    challenge_reason: str | None = None
    spec_hash: str | None = None
    facts_hash: str | None = None


class Cart(BaseModel):
    lines: list[tuple[str, int]]      # (sku, qty)
    total_cents: int
    spec_hash: str
    cart_hash: str = ""
    proofs: list[ProofResult]
    merchant: str = "mockstore"
    line_prices: dict[str, int] = {}   # sku -> unit total (price + shipping) in cents
    category: str = ""
    seller: str = ""
    request_id: str = ""                # binds the idempotency key to one request
    binding: dict = {}                  # LIVE: merchant, product id, quote, address hash, token ref

    def compute_hash(self) -> str:
        return sha256_of({
            "request_id": self.request_id, "seller": self.seller, "category": self.category, "binding": self.binding,
            "lines": [list(l) for l in self.lines], "total_cents": self.total_cents,
            "spec_hash": self.spec_hash, "merchant": self.merchant,
            "line_prices": self.line_prices,
            "proofs": [{"sku": p.candidate_sku, "status": p.status, "facts_hash": p.facts_hash,
                        "accepted_risks": p.accepted_risks} for p in self.proofs],
        })


class Envelope(BaseModel):
    max_order_cents: int
    max_day_cents: int
    max_orders_per_day: int
    category_allowlist: list[str] = []
    seller_allowlist: list[str] = []
    min_return_window_days: int = 30
    allow_unverified: list[str] = []

    def compute_hash(self) -> str:
        return sha256_of(self)


class Profile(BaseModel):
    preferences: list[Constraint] = []
    standing_rules: list[Constraint] = []
    seller_allowlist: list[str] = []
    spend_cap_cents: int = 50_000
    day_cap_cents: int = 100_000
    default_mode: Mode = "supervised"
    autonomy_envelope: Envelope | None = None
    envelope_hash: str | None = None
    price_threshold_cents: int = 25_000
    variant_defaults: dict[str, str] = {}   # axis -> preferred value ("color": "black")
    ranking: list[str] = ["price"]          # lexicographic: price, -price, rating, review_quality, delivery_days, made_in_us
    conditional_rules: list[Conditional] = []
    live_enabled: bool = False
    live_order_cap_cents: int = 10_000

    def default_for(self, axis: str) -> str | None:
        return self.variant_defaults.get(axis)


class PaymentMethod(BaseModel):
    kind: Literal["enrolled", "one_time"]
    provider: Literal["crossmint"] = "crossmint"
    token_ref: str
    network_token: bool = False
    brand: str
    last4: str
    bound_cart_hash: str | None = None
    used: bool = False
    max_cents: int = 0                 # Crossmint spending rule (enrolled) or exact total (one_time)


class LiveQuote(BaseModel):
    route: Literal["fast_checkout", "agent_checkout", "browser"]
    merchant: str
    product_id: str
    variant_id: str | None = None
    qty: int
    subtotal_cents: int
    tax_cents: int
    shipping_cents: int
    total_cents: int
    delivery_estimate_days: int | None = None
    return_window_days: int | None = None
    quote_id: str
    fetched_at: datetime

    def comparable(self) -> dict:
        d = self.model_dump(mode="json")
        d.pop("quote_id"); d.pop("fetched_at")
        return d


RANKING_KEYS = {
    "price": "lowest total price", "-price": "highest total price", "rating": "highest star rating",
    "review_quality": "fewest quality complaints in reviews (soft, can be gamed)",
    "delivery_days": "fastest delivery", "made_in_us": "made in the US first",
}


class RolePolicy(BaseModel):
    max_order_cents: int
    allowed_categories: list[str] = []      # empty = every category not excluded in v1
    approval_over_cents: int | None = None  # above this, a second approver must approve the cart
    approver_role: str | None = None


class CompanyPolicy(BaseModel):
    name: str = "Company purchasing policy"
    roles: dict[str, RolePolicy]
    rules: list[Constraint] = []            # hard, origin company_policy
    conditional: list[Conditional] = []
    supplier_allowlist: list[str] = []      # empty = any supplier
    seller_trust: dict[str, str] = {}       # seller -> "high" | "low"; merged over the H0 table
    trust_brand_direct: bool = True         # a seller with the same name as the brand (manufacturer store) is high
    brand_direct_is_new: bool = True        # the manufacturer's own store sells new items when no condition is stated

    def compute_hash(self) -> str:
        return sha256_of(self)


class UserAccount(BaseModel):
    username: str
    role: str
    cost_center: str = ""
    display_name: str = ""
