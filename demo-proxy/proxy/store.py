"""Loads users + company policy and reports company spend so far."""

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
    """Policy always comes from data/company_policy.json. Only spend state lives in var/spend.json,
    seeded from the policy file's spent_* fields the first time the proxy starts and moved by
    record_purchase when the engine reports a completed purchase."""

    def __init__(self, data_dir: Path, var_dir: Path, clock: Callable[[], datetime]):
        self.clock = clock
        self.policy = Policy.model_validate(json.loads((data_dir / "company_policy.json").read_text()))
        self.path = var_dir / "spend.json"
        if self.path.exists():
            state = json.loads(self.path.read_text())
            self.policy.spent_today_cents = state["spent_today_cents"]
            self.policy.spent_by_job = state["spent_by_job"]
            self.policy.spent_date = state["spent_date"]
        elif self.policy.spent_date is None:
            self.policy.spent_date = self._today()
        self._write()

    def _today(self) -> str:
        return self.clock().astimezone(ZoneInfo(self.policy.timezone)).date().isoformat()

    def _write(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        p = self.policy
        tmp.write_text(json.dumps({"spent_today_cents": p.spent_today_cents, "spent_by_job": p.spent_by_job,
                                   "spent_date": p.spent_date}, indent=2) + "\n")
        os.replace(tmp, self.path)

    def spend(self, job: str | None) -> tuple[int, int]:
        """(spent_today_cents, spent_on_job_cents). Today's spend resets at local midnight."""
        today = self._today()
        if self.policy.spent_date != today:
            self.policy.spent_today_cents = 0
            self.policy.spent_date = today
            self._write()
        on_job = self.policy.spent_by_job.get(job, 0) if job else 0
        return self.policy.spent_today_cents, on_job

    def record_purchase(self, job: str | None, cents: int) -> None:
        """Add a completed purchase to today's spend and its job's spend, then persist."""
        self.spend(job)  # roll the daily counter over first if the date changed
        self.policy.spent_today_cents += cents
        if job:
            self.policy.spent_by_job[job] = self.policy.spent_by_job.get(job, 0) + cents
        self._write()
