"""Signed session parameters shared between the Acme proxy and the agent.

Standard library only, so the agent team can import this module or copy the file as-is.

    from proxy.session_sig import verify_session
    if not verify_session(body["session"], body["session_sig"]):   # reads PROXY_SHARED_SECRET
        reject()

Signature = hex HMAC-SHA256 over canonical_json(session) with PROXY_SHARED_SECRET.
Canonical JSON = sorted keys, no whitespace, UTF-8, non-ASCII left unescaped.
A session is valid only if the signature matches AND now is within [issued_at, expires_at].
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

# Tolerated clock skew between proxy and agent when checking issued_at.
CLOCK_SKEW = timedelta(seconds=60)


class SessionError(ValueError):
    """Raised by check_session with a human-readable reason."""


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _key(secret: str | bytes | None) -> bytes:
    if secret is None:
        secret = os.environ.get("PROXY_SHARED_SECRET", "")
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    if not secret:
        raise SessionError("no shared secret configured")
    return secret


def sign_session(session: dict, secret: str | bytes | None = None) -> str:
    return hmac.new(_key(secret), canonical_json(session), hashlib.sha256).hexdigest()


def _parse_ts(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise SessionError(f"{field} missing")
    try:
        ts = datetime.fromisoformat(value)
    except ValueError as e:
        raise SessionError(f"{field} is not ISO-8601") from e
    if ts.tzinfo is None:
        raise SessionError(f"{field} has no UTC offset")
    return ts


def check_session(session: Any, sig: Any, secret: str | bytes | None = None,
                  now: datetime | None = None) -> None:
    """Raise SessionError if the session is tampered with, malformed, or outside its validity window."""
    if not isinstance(session, dict):
        raise SessionError("session is not an object")
    if not isinstance(sig, str) or not sig:
        raise SessionError("signature missing")
    expected = sign_session(session, secret)
    if not hmac.compare_digest(expected, sig):
        raise SessionError("bad signature")
    now = now or datetime.now(timezone.utc)
    issued = _parse_ts(session.get("issued_at"), "issued_at")
    expires = _parse_ts(session.get("expires_at"), "expires_at")
    if issued - CLOCK_SKEW > now:
        raise SessionError("issued in the future")
    if now >= expires:
        raise SessionError("expired")


def verify_session(session: Any, sig: Any, secret: str | bytes | None = None,
                   now: datetime | None = None) -> bool:
    """True only if the signature matches and the session has not expired. Never raises."""
    try:
        check_session(session, sig, secret, now)
    except SessionError:
        return False
    return True


def cart_hash(cart: Any) -> str:
    """SHA-256 hex of the canonical cart JSON. The proxy approves exactly this hash."""
    return hashlib.sha256(canonical_json(cart)).hexdigest()
