"""Wire-compatible HMAC signatures; independent of proxy application code."""
import hashlib
import hmac
import json


def sign_payload(payload: dict, secret: str) -> dict:
    body = {k: v for k, v in payload.items() if k != 'proxy_sig'}
    encoded = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    signature = hmac.new(secret.encode('utf-8'), encoded, hashlib.sha256).hexdigest()
    return {**body, 'proxy_sig': signature}


def verify_payload(payload, secret: str) -> bool:
    if not secret or not isinstance(payload, dict) or not isinstance(payload.get('proxy_sig'), str):
        return False
    try:
        return hmac.compare_digest(payload['proxy_sig'], sign_payload(payload, secret)['proxy_sig'])
    except (TypeError, ValueError):
        return False
