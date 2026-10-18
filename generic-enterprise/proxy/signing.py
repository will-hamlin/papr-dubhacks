"""HMAC signing shared by the proxy, the demo website and the engine.

Standard library only, so other teams can import this module or copy the file as-is.

Caller (demo website / agent) -> proxy:
    auth = make_auth("u_jordan", secret)            # {user_id, issued_at, expires_at, sig}
    POST /orders {"auth": auth, "request_text": "..."}

Proxy -> engine:
    the search payload carries "proxy_sig"; the engine checks it with verify_payload(payload, secret).

Signature = lowercase hex HMAC-SHA256 over canonical JSON (sorted keys, no whitespace, UTF-8,
non-ASCII unescaped), keyed with PROXY_SHARED_SECRET.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

CLOCK_SKEW = timedelta(seconds=60)
AUTH_FIELDS = {"user_id", "issued_at", "expires_at"}


class AuthError(ValueError):
    """Raised by check_auth with a human-readable reason."""


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _key(secret: str | bytes | None) -> bytes:
    if secret is None:
        secret = os.environ.get("PROXY_SHARED_SECRET", "")
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    if not secret:
        raise AuthError("no shared secret configured")
    return secret


def sign(obj: dict, secret: str | bytes | None = None) -> str:
    return hmac.new(_key(secret), canonical_json(obj), hashlib.sha256).hexdigest()


def _matches(obj: dict, sig: Any, secret: str | bytes | None) -> bool:
    return isinstance(sig, str) and hmac.compare_digest(sign(obj, secret), sig)


# ---------------------------------------------------------------- caller auth

def make_auth(user_id: str, secret: str | bytes | None = None, ttl: timedelta = timedelta(minutes=30),
              now: datetime | None = None) -> dict:
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    body = {"user_id": user_id, "issued_at": now.isoformat(), "expires_at": (now + ttl).isoformat()}
    return {**body, "sig": sign(body, secret)}


def _parse_ts(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise AuthError(f"{field} missing")
    try:
        ts = datetime.fromisoformat(value)
    except ValueError as e:
        raise AuthError(f"{field} is not ISO-8601") from e
    if ts.tzinfo is None:
        raise AuthError(f"{field} has no UTC offset")
    return ts


def check_auth(auth: Any, secret: str | bytes | None = None, now: datetime | None = None) -> str:
    """Return the authenticated user_id, or raise AuthError."""
    if not isinstance(auth, dict):
        raise AuthError("auth is not an object")
    body = {k: v for k, v in auth.items() if k != "sig"}
    if set(body) != AUTH_FIELDS:
        raise AuthError("auth must contain exactly user_id, issued_at, expires_at, sig")
    if not _matches(body, auth.get("sig"), secret):
        raise AuthError("bad signature")
    now = now or datetime.now(timezone.utc)
    if _parse_ts(body["issued_at"], "issued_at") - CLOCK_SKEW > now:
        raise AuthError("issued in the future")
    if now >= _parse_ts(body["expires_at"], "expires_at"):
        raise AuthError("expired")
    if not isinstance(body["user_id"], str) or not body["user_id"]:
        raise AuthError("user_id missing")
    return body["user_id"]


# ---------------------------------------------------------------- proxy -> engine

def sign_payload(payload: dict, secret: str | bytes | None = None) -> dict:
    body = {k: v for k, v in payload.items() if k != "proxy_sig"}
    return {**body, "proxy_sig": sign(body, secret)}


def verify_payload(payload: Any, secret: str | bytes | None = None) -> bool:
    """True if the engine payload is exactly what the proxy signed. Never raises."""
    if not isinstance(payload, dict):
        return False
    body = {k: v for k, v in payload.items() if k != "proxy_sig"}
    try:
        return _matches(body, payload.get("proxy_sig"), secret)
    except AuthError:
        return False


if __name__ == "__main__":
    # Dev helper: python -m proxy.signing u_jordan  -> prints an auth object (uses PROXY_SHARED_SECRET)
    print(json.dumps(make_auth(sys.argv[1] if len(sys.argv) > 1 else "u_jordan")))
