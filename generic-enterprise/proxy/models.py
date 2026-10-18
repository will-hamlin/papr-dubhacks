"""Typed data for users, company policy, carts and agent events. All money is integer cents."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Cents = Field(strict=True, ge=0)


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
    auto_buy_threshold_cents: int = Field(strict=True, ge=0)
    daily_cap_cents: int = Field(strict=True, ge=0)
    per_job_cap_cents: int = Field(strict=True, ge=0)
    tax_rate_bp: int = Field(strict=True, ge=0, le=10000)
    freight_cents_by_supplier: dict[str, int]
    spent_today_cents: int = Field(strict=True, ge=0)
    spent_by_job: dict[str, int]
    spent_date: str | None = None


class CartItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    sku: str
    name: str
    supplier_id: str
    category: str
    unit_price_cents: int = Field(strict=True, ge=0)
    qty: int = Field(strict=True, ge=1, le=1000)


class Cart(BaseModel):
    model_config = ConfigDict(extra="allow")
    items: list[CartItem] = Field(min_length=1)


EventType = Literal["spec_ready", "cart_ready", "needs_manager", "purchased", "flagged", "error"]


class AgentEvent(BaseModel):
    run_id: str
    type: EventType
    payload: dict[str, Any] = {}
    reason: str | None = None


class LoginBody(BaseModel):
    user_id: str


class RequestBody(BaseModel):
    request_text: str = Field(min_length=1, max_length=2000)


class ApproveCartBody(BaseModel):
    cart_hash: str


class RejectBody(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
