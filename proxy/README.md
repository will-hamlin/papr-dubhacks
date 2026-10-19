# Authorization proxy

The proxy receives requests through HTTP API or MCP. Personal agents authenticate with account login and OAuth;
the proxy loads organization configuration and user information from its own account database.
See [ACCOUNTS.md](ACCOUNTS.md) for provisioning, browser login and agent connection setup.
It authenticates the connector, checks user permissions, budget ceilings, and raw-text policy restrictions,
then sends a signed authorization decision to the co-located main service. Product parsing, proof conditions,
ranking weights, search, and verification live in [main-service](../main-service/README.md).

## Client API

Account clients send `{ "request_id": "...", "request_text": "...", "search_mode": "agent" }` with their OAuth
access token. Configuration/identity fields are forbidden. The MCP tools use the same account-bound operations.

With explicit `PROXY_ALLOW_LEGACY_CONFIG=1`, `POST /orders` also accepts the existing demo connector/dashboard envelope:

```json
{
  "request": {"id": "client-generated-uuid", "createdAt": "2026-10-18T00:00:00Z", "text": "65W USB-C charger under $40"},
  "userConfig": {"employeeId": "EMP-1042", "companyId": "CO-001", "name": "Alex", "approvalLimit": 5000, "purchasingEnabled": true},
  "companyConfig": {"companyId": "CO-001", "name": "Northstar", "purchasePolicy": {"approvalRequiredAbove": 1000}}
}
```

Send `Authorization: Bearer <PROXY_API_TOKEN>`. The authenticated connector is trusted to supply the profiles;
this demo token is not individual employee authentication. Full profile objects are preserved in the MS handoff.
`approvalLimit` and `approvalRequiredAbove` are dollar values converted to integer cents.
Optional `purchasePolicy.blockedCategories` and `blockedKeywords` override the demo policy for this request.
Tax, freight, suppliers, and unspecified restrictions retain the defaults in `data/company_policy.json`.

The signed-user contract `{ "auth": { "user_id", "issued_at", "expires_at", "sig" }, "request_text": "..." }`
also remains supported. It loads user permissions and company policy from server-side `data/` files.

| HTTP | Decision | Meaning |
|---|---|---|
| 200 | `accepted` | Authorized and queued for MS; no product has been approved by this response |
| 400 | `bad_request` | Invalid input or mismatched profiles |
| 401 | `not_authorized` | Invalid/expired credentials or unknown user |
| 403 | `not_authorized` / `violates_company_policy` | Disabled purchasing, exhausted limit, or blocked request |
| 409 | `conflict` | Request ID reused with different context, or still in flight |

Responses contain `ok`, `order_id`, `decision`, an optional `reason`, and `main_service` delivery status.
New authorized or denied purchase requests are sent to MS for documentation. OAuth protocol/authentication errors
are handled at the authentication boundary before purchase processing.
Credentials are not included in the handoff. Unverified identity claims are marked `identity_verified: false`.
Retries of an already decided request reuse its original decision rather than starting another MS job.

## Handoff and reliability

The HMAC-signed version-1 envelope contains:

- `authorization`: accepted flag, decision, rejection reason, HTTP status, and authentication state.
- `request`, `organization`, `user`: original request and profile context.
- `company`, `requester`: normalized identities for downstream integrations.
- `limits`: authorized budget ceiling and applicable policy for accepted requests; empty on denial.
- `order_id`, `issued_at`, `proxy_sig`: identity, timestamp, and signature.

The proxy does not extract product constraints, interpret a requested budget, or generate solver conditions.
MS may tighten the authorized ceiling from the request; it cannot raise it.

Every handoff is persisted in `var/outbox.sqlite3` before delivery. If MS is unavailable, the client still gets
the authorization decision with `main_service.status=delivery_pending`; delivery retries every five seconds
and resumes after restart. A denial remains a denial during an outage. MS deduplicates by `order_id`.

`GET /health` includes the pending-delivery count. `GET /audit` retains the local hash-chained operational audit
and requires the operator's `PROXY_API_TOKEN`.
`POST /purchases` retains the signed completed-purchase callback and updates authorization spend counters;
those counters are not the MS results database. The existing single-process spend/cap behavior is preserved.

## Configuration

| Variable | Default / use |
|---|---|
| `PROXY_SHARED_SECRET` | Required; same secret in MS |
| `PROXY_API_TOKEN` | Operator audit access; also required for the opt-in legacy connector envelope |
| `PROXY_PUBLIC_URL` | `http://127.0.0.1:8000`; canonical HTTPS public origin for remote agents |
| `PROXY_ALLOW_LEGACY_CONFIG` | Disabled; `1` enables the editable-profile demo connector |
| `PROXY_DYNAMIC_REGISTRATION` | Disabled; `1` permits rate-limited public OAuth client registration |
| `MAIN_SERVICE_URL` | `http://127.0.0.1:8001` |
| `PROXY_VAR_DIR` | `proxy/var` |

Run from the repository root as shown in [README](../README.md), or `make dev` from this folder on Unix.
Use one proxy worker. The proxy has no Anthropic dependency and no search-engine configuration.

## Personal-agent candidates

Account API requests and MCP default to `agent` mode. Use OAuth access tokens for status and candidate submission.
Account orders enforce ownership on every call and do not issue request capability tokens.

For legacy integrations, set `request.search_mode` to `agent` in the connector envelope, or set top-level `search_mode` to `agent`
for the signed-user API. Omission defaults to `managed`, preserving enterprise/demo behavior.
The proxy includes the mode in its signed handoff and idempotency check; it still does no product parsing.

An accepted **legacy** `POST /orders` response includes `request_token`, a 24-hour bearer capability scoped to that
one order. It permits reading that order and submitting its candidates; it does not grant account access,
change company policy, approve a purchase, or reveal the proxy/MS shared secret. Store it as a credential.
It is issued only to an authenticated, authorized caller, and is not written to the proxy audit response.
This legacy capability is separate from the implemented account/OAuth connection and cannot access account-owned orders.

1. Call `GET /orders/{order_id}` with `Authorization: Bearer <access_token>` (or the legacy `request_token`) until status is
   `awaiting_candidates`. Inspect `result.specs`, `result.limits`, and `result.requirements_id`.
2. Search for products using the caller's own agent.
3. Submit the batch below to `POST /orders/{order_id}/candidates` with the same authentication.
4. Poll `GET /orders/{order_id}` until `verification_complete`; read `result.verification`.

Example payload (the supplier URL is illustrative):

```json
{
  "submission_id": "agent-batch-1",
  "requirements_id": "<64-character hash returned by MS>",
  "candidates": [{
    "candidate_id": "charger-1",
    "url": "https://supplier.example/products/charger-65",
    "sku": "CH-65",
    "claims": [
      {"field": "power", "value": 65, "unit": "W"},
      {"field": "price_cents", "value": 2500},
      {"field": "currency", "value": "USD"}
    ]
  }]
}
```

`202` means the batch is durably queued. Use the same submission ID and contents after uncertain delivery:
an exact repeat is idempotent; changing the contents under that ID returns `409`. Different requirements,
denied requests, managed-search requests, and requests that are not ready also reject candidate submissions.
After a completed batch, another submission ID can be used for additional candidates; SQLite retains prior batches.
Malformed candidate schemas return `400`, unknown orders `404`, invalid/expired request tokens `401`,
and an unreachable MS returns `503` without claiming successful delivery. On token expiry, repeat the original
authenticated connector request with its original request ID to obtain a fresh token for the same order.
The older signed-user creation contract has no client request ID, so its callers must finish within token lifetime.

Batches contain at most 10 candidates and each candidate at most 30 typed claims. URLs must use HTTPS.
Client-provided verification flags, screenshots, extracted page text, and policy/requirements overrides are not
accepted as evidence. The proxy forwards candidates; MS fetches and checks the source itself.
