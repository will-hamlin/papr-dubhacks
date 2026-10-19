"""Authorization inputs: users, organization policy, and client requests. Money is integer cents."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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
    search_mode: Literal['managed', 'agent'] = 'managed'


class AccountOrder(BaseModel):
    model_config = {'extra': 'forbid', 'strict': True}
    request_id: str = Field(min_length=1, max_length=200)
    request_text: str = Field(min_length=1, max_length=2000)
    search_mode: Literal['managed', 'agent'] = 'agent'


# ---------------------------------------------------------------- the employee dashboard's envelope
# demo/DASHBOARD.md "Outgoing contract". Extra fields are allowed and ignored.

def dollars_to_cents(value: Any) -> int:
    """Whole or 2-decimal dollar amount -> integer cents. Floats go through str(), never float math."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("must be a number")
    try:
        d = Decimal(str(value).strip())
    except InvalidOperation as e:
        raise ValueError("must be a number") from e
    if not d.is_finite() or d < 0:
        raise ValueError("must be a non-negative number")
    cents = d * 100
    if cents != cents.to_integral_value():
        raise ValueError("must have at most 2 decimal places")
    return int(cents)


class DashboardRequest(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    createdAt: str
    text: str = Field(min_length=1, max_length=2000)
    search_mode: Literal['managed', 'agent'] = 'managed'


class DashboardUser(BaseModel):
    employeeId: str = Field(min_length=1, max_length=100)
    companyId: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    email: str = ""
    role: str = ""
    costCenter: str | None = None
    approvalLimit: int = Field(description="Whole dollars in the dashboard; stored here as cents")
    currency: str = "USD"
    purchasingEnabled: bool = Field(default=True, strict=True)

    @field_validator("approvalLimit", mode="before")
    @classmethod
    def _cents(cls, v):
        return dollars_to_cents(v)


class DashboardPurchasePolicy(BaseModel):
    approvalRequiredAbove: int | None = None
    preferredVendors: list[str] = []
    blockedCategories: list[str] | None = None
    blockedKeywords: dict[str, list[str]] | None = None

    @field_validator("approvalRequiredAbove", mode="before")
    @classmethod
    def _cents(cls, v):
        return None if v is None else dollars_to_cents(v)


class DashboardCompany(BaseModel):
    companyId: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    currency: str = "USD"
    billingAddress: str = ""
    purchasePolicy: DashboardPurchasePolicy = DashboardPurchasePolicy()


class DashboardOrder(BaseModel):
    request: DashboardRequest
    userConfig: DashboardUser
    companyConfig: DashboardCompany
