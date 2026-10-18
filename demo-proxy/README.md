# Acme Corp Purchasing proxy (DEMO COMPANY)

A standalone service between the caller (demo website / agent) and the pbapo engine.
For each order it decides:

1. **Is the user authorized?** Signed auth, user exists, purchasing enabled, limits and caps not used up.
2. **Does the order break company policy?** Blocked categories (weapons, medicine, age-restricted, gift cards), checked
   on both the parsed spec and the raw text; sane quantity.

Orders that fail get a failure notice with the reason. Orders that pass become **typed specs + integer weights +
a priority order + spending limits**. These are signed and POSTed to the engine, and the engine's answer is returned
to the caller. When the engine reports a completed
purchase (`POST /purchases`), the spend counters move. Every call writes one entry to a hash-chained audit log.

The proxy never holds payment credentials, never picks a product, and never lets request text raise a limit.

Run these commands from `demo-proxy/` (Makefile requires a Unix-like shell):

```bash
cd demo-proxy
make dev                      # http://localhost:8000, stub engine, rule parser (no API key needed)
make test                     # offline pytest suite
make token USER_ID=u_jordan   # print a signed auth object for curl testing
make reset                    # wipe var/ (spend counters, audit log)
```

| Env var | Meaning |
|---|---|
| `PROXY_SHARED_SECRET` | HMAC key shared with the caller and the engine (`make dev` defaults to `dev-only-secret`) |
| `ENGINE_URL`, `ENGINE_PATH` | Where to POST accepted orders (default path `/search`). Unset = stub engine |
| `SPEC_PARSER` | `auto` (default: Claude if `ANTHROPIC_API_KEY` is set, else rules), `claude`, or `rules` |
| `ANTHROPIC_API_KEY` | Enables the Claude spec parser (`claude-opus-5-5`) |

## API

`POST /orders`
```json
{"auth": {"user_id": "u_jordan", "issued_at": "...", "expires_at": "...", "sig": "<hex>"},
 "request_text": "65W USB-C charger for my XPS 13"}
```
Build `auth` with `proxy/signing.py` → `make_auth(user_id, secret)` (stdlib only; copy it into the demo site).

| HTTP | `decision` | When |
|---|---|---|
| 200 | `accepted` | Passed; body has `specs`, `weights`, `priority`, `limits`, `notes`, `engine` |
| 401 | `not_authorized` | Bad/expired auth signature, unknown user |
| 403 | `not_authorized` | Purchasing disabled, $0 limit, daily/job cap already reached |
| 403 | `violates_company_policy` | Blocked category or keyword, quantity out of range |
| 422 | `unclear_request` | Not a purchase request, unreadable required value, contradictory constraints |
| 400 | `bad_request` | Malformed body |
| 502 / 503 | `engine_error` / `parser_error` | Engine or parser failed (fail closed) |

Every response has `ok`, `order_id`, `decision`, and `reason` when it failed.

`POST /purchases`: the engine / payment gate reports a completed purchase so the spend counters move.
```json
{"order_id": "o_…", "total_cents": 40000, "proxy_sig": "<hex>"}
```
Sign it with `sign_payload({"order_id": …, "total_cents": …}, secret)` from `proxy/signing.py`. `total_cents` is the
final integer total (items + tax + freight). It's added to today's company spend and to the order's job, so later
orders get a smaller `limits.max_total_cents`.

| HTTP | `decision` | When |
|---|---|---|
| 200 | `recorded` | Spend updated |
| 200 | `duplicate` | Same `order_id` and total already recorded; nothing changes |
| 400 | `bad_request` | Body isn't exactly `order_id`, `total_cents`, `proxy_sig` |
| 401 | `not_authorized` | Bad `proxy_sig` |
| 404 | `unknown_order` | No accepted order with that `order_id` |
| 409 | `over_limit` / `invalid_total` / `conflict` | Total above the order's `max_total_cents`, not a non-negative integer, or a different total for an already recorded order (flagged in the audit log) |

`GET /audit`: all entries, plus `chain_valid`. `GET /health`: shows which parser and engine are active.

## What the engine receives

```json
{"order_id": "o_…", "issued_at": "…", "requester": {"user_id", "name", "job_number", "cost_code", "ship_to"},
 "request_text": "…",
 "specs": {"item": "laptop charger", "category": "computer_accessories", "quantity": 1, "condition": "unspecified",
           "constraints": [{"field": "power", "op": "ge", "value": 65, "unit": "W", "required": true},
                           {"field": "connector", "op": "eq", "value": "USB-C", "unit": null, "required": true}],
           "english": ["power ≥ 65 W (required)", "connector = USB-C (required)"]},
 "weights": {"compatibility": 40, "price": 30, "quality": 20, "delivery_speed": 10},
 "priority": ["compatibility", "price", "quality", "delivery_speed"],
 "limits": {"currency": "USD", "max_total_cents": 50000, "tax_rate_bp": 1025,
            "freight_cents_by_supplier": {"sup_01": 0, "sup_03": 2500},
            "approved_suppliers": ["sup_01", "sup_03"], "blocked_categories": ["weapons", "…"],
            "total_formula": "…"},
 "proxy_sig": "<hex>"}
```
The engine verifies the payload with `verify_payload(payload, secret)` from `proxy/signing.py`. Numeric constraint
values are integers in base units (mm, g, MB, W, mV, mAh, Hz, count). `op` is one of `eq ne ge le`. A field the
request didn't mention is absent, which means **unknown**, not false or zero. `max_total_cents` covers items, tax
and freight.

## Layout
`proxy/signing.py` HMAC auth + payload signing · `spec.py` Claude / rule spec parsers · `gates.py` authorization,
policy, constraint compiler, weights · `service.py` pipeline · `engine.py` HTTP + stub engine ·
`audit.py` hash chain · `store.py` users, policy, spend · `app.py` routes.
