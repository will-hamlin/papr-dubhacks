"""Loads users + company policy, and tracks company spend (committed + reserved)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from .models import Policy, User


def load_users(data_dir: Path) -> dict[str, User]:
    raw = json.loads((data_dir / "users.json").read_text())
    users = [User.model_validate(u) for u in raw]
    return {u.id: u for u in users}


class PolicyStore:
    """The live policy is var/company_policy.json, seeded from data/company_policy.json.

    Spend is written back on every purchase. Reservations hold money for carts that were
    approved but not yet confirmed purchased, so two approvals can't both slip under a cap.
    """

    def __init__(self, data_dir: Path, var_dir: Path, clock: Callable[[], datetime]):
        self.clock = clock
        self.path = var_dir / "company_policy.json"
        if not self.path.exists():
            seed = json.loads((data_dir / "company_policy.json").read_text())
            policy = Policy.model_validate(seed)
            if policy.spent_date is None:
                policy.spent_date = self._today(policy)
            self._write(policy)
        self.policy = Policy.model_validate(json.loads(self.path.read_text()))
        self.reservations: dict[str, tuple[str | None, int]] = {}

    def _today(self, policy: Policy) -> str:
        return self.clock().astimezone(ZoneInfo(policy.timezone)).date().isoformat()

    def _write(self, policy: Policy) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(policy.model_dump(), indent=2) + "\n")
        os.replace(tmp, self.path)

    def _roll_day(self) -> None:
        today = self._today(self.policy)
        if self.policy.spent_date != today:
            self.policy.spent_today_cents = 0
            self.policy.spent_date = today
            self._write(self.policy)

    def spend(self, job: str | None) -> tuple[int, int]:
        """(spent_today_cents, spent_on_job_cents), both including open reservations."""
        self._roll_day()
        reserved_today = sum(c for _, c in self.reservations.values())
        reserved_job = sum(c for j, c in self.reservations.values() if j == job)
        on_job = self.policy.spent_by_job.get(job, 0) if job else 0
        return self.policy.spent_today_cents + reserved_today, on_job + reserved_job

    def reserve(self, run_id: str, job: str | None, cents: int) -> None:
        self.reservations[run_id] = (job, cents)

    def release(self, run_id: str) -> None:
        self.reservations.pop(run_id, None)

    def commit(self, run_id: str, job: str | None, cents: int) -> None:
        self.release(run_id)
        self._roll_day()
        self.policy.spent_today_cents += cents
        if job:
            self.policy.spent_by_job[job] = self.policy.spent_by_job.get(job, 0) + cents
        self._write(self.policy)
