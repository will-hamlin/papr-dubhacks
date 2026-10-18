"""Typed data: users, company policy, request bodies, and the spec proposal. Money is integer cents."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class User(BaseModel):
    id: str
    name: str
    email: str
    role: str
    job_number: str | None = None
    cost_code: str | None = None
    spend_limit_cents: int = Field(strict=True, ge=0)
    approver_id: str | None = None
    approves_for: list[str] = []
    purchasing_enabled: bool
    ship_to: str


class Policy(BaseModel):
    id: str
    name: str
    timezone: str = "UTC"
    compliance_email: str
    suppliers: dict[str, str] = {}
    approved_suppliers: list[str]
    blocked_categories: list[str]
    blocked_keywords: dict[str, list[str]] = {}
    daily_cap_cents: int = Field(strict=True, ge=0)
    per_job_cap_cents: int = Field(strict=True, ge=0)
    tax_rate_bp: int = Field(strict=True, ge=0, le=10000)
    freight_cents_by_supplier: dict[str, int]
    spent_today_cents: int = Field(strict=True, ge=0)
    spent_by_job: dict[str, int]
    spent_date: str | None = None


class OrderBody(BaseModel):
    auth: dict[str, Any]
    request_text: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------- spec proposal (what Claude / rules return)

Category = Literal["electronics", "computer_accessories", "office_supplies", "tools", "safety_equipment",
                   "furniture", "software", "cleaning_supplies", "weapons", "medicine", "age_restricted",
                   "gift_cards", "other"]

Criterion = Literal["price", "quality", "delivery_speed", "brand_match", "warranty", "supplier_rating",
                    "durability", "compatibility"]


Op = Literal["eq", "ne", "ge", "le"]

Unit = Literal["mm", "cm", "m", "in", "ft", "g", "kg", "oz", "lb", "MB", "GB", "TB", "W", "V", "mAh", "Hz",
               "GHz", "count"]

Condition = Literal["new", "refurbished", "used", "unspecified"]


class Constraint(BaseModel):
    field: str = Field(description="snake_case property name without unit, e.g. power, ram, length, connector, compatible_with")
    op: Op = Field(description="eq, ne, ge (at least) or le (at most)")
    value: str = Field(description="The value: a plain number for numeric fields (e.g. '65', '15.6'), else the text value")
    unit: Unit | None = Field(default=None, description="Unit of a numeric value; null for text values")
    required: bool = Field(description="True if the item is useless without it; false if merely preferred")


class Weight(BaseModel):
    criterion: Criterion
    weight: int = Field(description="Relative importance 0-100; weights should add up to 100")


class SpecProposal(BaseModel):
    understood: bool = Field(description="False if the text is not a purchase request or is too vague to search")
    unclear_reason: str | None = Field(default=None, description="Why it could not be understood, if understood is false")
    item: str = Field(description="What to buy, as a short noun phrase")
    category: Category
    quantity: int = Field(description="Number of units requested; 1 if not stated")
    condition: Condition = Field(description="new / refurbished / used if the request says so, else unspecified")
    constraints: list[Constraint]
    weights: list[Weight]
    stated_budget_cents: int | None = Field(default=None, description="Any budget or price ceiling written in the request, in integer cents; null if none")
