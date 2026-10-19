"""Authorization and raw-request policy checks; no product parsing or proof construction."""
from __future__ import annotations
import re
from .models import Policy, User

def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def normalize_category(category: str) -> str:
    return category.strip().lower().replace("-", "_").replace(" ", "_")


def ceiling_cents(user: User, policy: Policy, spent_today: int, spent_on_job: int, company_caps: bool = True) -> int:
    """Most the user may spend on one order right now, tax and freight included.
    company_caps=False: only the user's own limit applies (dashboard profiles carry no daily/job caps)."""
    if not company_caps:
        return max(0, user.spend_limit_cents)
    caps = [user.spend_limit_cents, policy.daily_cap_cents - spent_today]
    if user.job_number:
        caps.append(policy.per_job_cap_cents - spent_on_job)
    return max(0, min(caps))


def authorize(user: User | None, policy: Policy, spent_today: int, spent_on_job: int,
              company_caps: bool = True) -> list[str]:
    """User-level checks. Empty list = authorized."""
    if user is None:
        return ["unknown user"]
    reasons = []
    if not user.purchasing_enabled:
        reasons.append(f"purchasing is disabled for {user.name} ({user.role})")
    if user.spend_limit_cents <= 0:
        reasons.append(f"{user.name} has a $0.00 spend limit")
    if not company_caps:
        return reasons
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


def check_request_policy(request_text: str, policy: Policy) -> list[str]:
    blocked = {normalize_category(c) for c in policy.blocked_categories}
    return list(dict.fromkeys(
        f"'{word}' falls under blocked category '{category}'"
        for category, word in _keyword_hits(request_text, policy)
        if normalize_category(category) in blocked
    ))


def compile_limits(user: User, policy: Policy, spent_today: int, spent_on_job: int,
                   company_caps: bool = True) -> dict:
    suppliers = [s for s in policy.approved_suppliers if s in policy.freight_cents_by_supplier]
    return {
        "currency": "USD",
        "max_total_cents": ceiling_cents(user, policy, spent_today, spent_on_job, company_caps),
        "tax_rate_bp": policy.tax_rate_bp,
        "freight_cents_by_supplier": {s: policy.freight_cents_by_supplier[s] for s in suppliers},
        "approved_suppliers": suppliers,
        "blocked_categories": [normalize_category(c) for c in policy.blocked_categories],
        "blocked_keywords": policy.blocked_keywords,
    }
