"""In-app Outbox: every message the proxy "sends". Nothing leaves the machine."""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Callable


class Outbox:
    def __init__(self, path: Path, clock: Callable[[], datetime]):
        self.path = path
        self.clock = clock
        self.messages: list[dict] = []
        if path.exists():
            self.messages = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def send(self, to: list[str], type: str, run_id: str | None, subject: str, body: str) -> dict:
        msg = {"id": "m_" + secrets.token_hex(4), "sent_at": self.clock().isoformat(timespec="seconds"),
               "to": to, "type": type, "run_id": run_id, "subject": subject, "body": body}
        self.messages.append(msg)
        with self.path.open("a") as f:
            f.write(json.dumps(msg) + "\n")
        return msg

    def for_run(self, run_id: str) -> list[dict]:
        return [m for m in self.messages if m["run_id"] == run_id]
