"""Append-only JSONL audit log with a SHA-256 hash chain. Entries are never edited or deleted."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from .session_sig import canonical_json

GENESIS = "0" * 64


def entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(canonical_json(body)).hexdigest()


def verify_chain(entries: list[dict]) -> tuple[bool, int | None]:
    """(ok, index of first bad entry)."""
    prev = GENESIS
    for i, e in enumerate(entries):
        if e.get("prev_hash") != prev or e.get("hash") != entry_hash(e) or e.get("seq") != i:
            return False, i
        prev = e["hash"]
    return True, None


class AuditLog:
    def __init__(self, path: Path, on_append: Callable[[dict], None] | None = None):
        self.path = path
        self.on_append = on_append
        self.path.touch(exist_ok=True)
        entries = self.entries()
        self._seq = len(entries)
        self._prev = entries[-1]["hash"] if entries else GENESIS

    def entries(self) -> list[dict]:
        out = []
        for line in self.path.read_text().splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    out.append({"corrupt_line": line})
        return out

    def append(self, record: dict) -> dict:
        entry = {"seq": self._seq, **record, "prev_hash": self._prev}
        entry["hash"] = entry_hash(entry)
        with self.path.open("a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
        self._seq += 1
        self._prev = entry["hash"]
        if self.on_append:
            self.on_append(entry)
        return entry

    def verify(self) -> tuple[bool, int | None]:
        return verify_chain(self.entries())
