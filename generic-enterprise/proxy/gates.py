"""Deterministic policy gates. Pure functions: same inputs, same decision. Fail closed."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .models import Cart, Policy, User

Decision = Literal["approve", "needs_manager", "flagged"]


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def normalize_category(category: str) -> str:
    return category.strip().lower().replace("-", "_").replace(" ", "_")


def preflight(user: User | None, login_expires_at: datetime | None, now: datetime,
              policy: Policy, spent_today: int, spent_on_job: int) -> list[str]:
    """User-level checks before anything reaches the agent. Empty list = pass."""
    if user is None:
        return ["unknown user"]
    reasons = []
    if not user.purchasing_enabled:
        reasons.append(f"purchasing is disabled for {user.name} ({user.role})")
    if login_expires_at is None or now >= login_expires_at:
        reasons.append("session expired; sign in again")
    if user.spend_limit_cents <= 0:
        reasons.append("user spend limit is $0.00")
    if spent_today >= policy.daily_cap_cents:
        reasons.append(f"company daily cap {money(policy.daily_cap_cents)} already reached")
    if user.job_number and spent_on_job >= policy.per_job_cap_cents:
        reasons.append(f"job {user.job_number} cap {money(policy.per_job_cap_cents)} already reached")
    return reasons


@dataclass
class Breakdown:
    lines: list[dict]
    subtotal_cents: int
    tax_cents: int
    freight: dict[str, int]
    freight_cents: int
    total_cents: int

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def compute_breakdown(cart: Cart, policy: Policy) -> tuple[Breakdown, list[str]]:
    """Proxy's own total: items + tax + freight. Returns problems that make the total untrustworthy."""
    problems = []
    lines = []
    for it in cart.items:
        lines.append({"sku": it.sku, "name": it.name, "supplier_id": it.supplier_id,
                      "supplier_name": policy.suppliers.get(it.supplier_id, "unknown supplier"),
                      "category": it.category, "qty": it.qty,
                      "unit_price_cents": it.unit_price_cents,
                      "line_cents": it.unit_price_cents * it.qty})
    subtotal = sum(line["line_cents"] for line in lines)
    # Round half up, integer only.
    tax = (subtotal * policy.tax_rate_bp + 5000) // 10000
    freight = {}
    for sup in dict.fromkeys(it.supplier_id for it in cart.items):
        rate = policy.freight_cents_by_supplier.get(sup)
        if rate is None:
            problems.append(f"no freight rate on file for supplier {sup}")
            rate = 0
        freight[sup] = rate
    freight_total = sum(freight.values())
    return Breakdown(lines, subtotal, tax, freight, freight_total, subtotal + tax + freight_total), problems


@dataclass
class GateResult:
    decision: Decision
    reasons: list[str] = field(default_factory=list)
    breakdown: Breakdown | None = None
    effective_total_cents: int = 0

    def as_dict(self) -> dict:
        return {"decision": self.decision, "reasons": self.reasons,
                "breakdown": self.breakdown.as_dict() if self.breakdown else None,
                "effective_total_cents": self.effective_total_cents}


def evaluate_cart(cart: Cart, user: User, policy: Policy, spent_today: int, spent_on_job: int,
                  agent_total_cents: int | None = None, agent_needs_manager: str | None = None) -> GateResult:
    """Cart-approval gate. Hard violations are flagged and can never be approved."""
    breakdown, problems = compute_breakdown(cart, policy)
    blocked = {normalize_category(c) for c in policy.blocked_categories}
    hard = list(problems)
    for it in cart.items:
        if it.supplier_id not in policy.approved_suppliers:
            hard.append(f"supplier {it.supplier_id} ({policy.suppliers.get(it.supplier_id, 'unknown')}) "
                        f"is not on the approved supplier list")
        if normalize_category(it.category) in blocked:
            hard.append(f"category '{it.category}' is blocked by company policy")
    # Gate on the higher of our total and the agent's claimed total.
    total = max(breakdown.total_cents, agent_total_cents or 0)
    if hard:
        return GateResult("flagged", list(dict.fromkeys(hard)), breakdown, total)

    soft = []
    if agent_total_cents is not None and agent_total_cents != breakdown.total_cents:
        soft.append(f"agent total {money(agent_total_cents)} differs from proxy total "
                    f"{money(breakdown.total_cents)}; using the higher")
    if total >= policy.auto_buy_threshold_cents:
        soft.append(f"total {money(total)} is at or over the auto-buy threshold "
                    f"{money(policy.auto_buy_threshold_cents)}")
    if total > user.spend_limit_cents:
        soft.append(f"total {money(total)} exceeds {user.name}'s limit {money(user.spend_limit_cents)}")
    if spent_today + total > policy.daily_cap_cents:
        soft.append(f"would bring company spend today to {money(spent_today + total)}, over the daily cap "
                    f"{money(policy.daily_cap_cents)}")
    if user.job_number and spent_on_job + total > policy.per_job_cap_cents:
        soft.append(f"would bring job {user.job_number} to {money(spent_on_job + total)}, over the job cap "
                    f"{money(policy.per_job_cap_cents)}")
    if agent_needs_manager:
        soft.append(f"agent requires manager approval: {agent_needs_manager}")
    # Any soft reason (including a total mismatch) means a manager must look.
    return GateResult("needs_manager" if soft else "approve", soft, breakdown, total)
