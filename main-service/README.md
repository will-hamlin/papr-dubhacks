# Main service (MS)

MS runs beside the authorization proxy. It owns the moved spec parser, typed product models, constraint
compiler, preference weights, and search/verifier client. It stores authorization decisions and processing
results in SQLite (`var/requests.sqlite3` by default).

## Processing

1. `POST /handoffs` validates the proxy signature and envelope, then durably records the handoff.
2. **Rejected:** store the request, supplied context, identity trust state, and rejection reason. No parser or backend calls.
3. **Accepted:** queue the request. The worker parses its product requirements, checks parsed policy/quantity,
   normalizes units, rejects contradictory constraints, and prepares proof-compatible specs and preferences.
4. Invoke the configured search/verification backend with the compiled signed payload. Request budgets can
   lower but never raise the proxy-authorized ceiling.
5. Store compiled requirements and backend output. For the agent-v1 backend, poll outstanding requests and
   persist later approval, verification, failure, and purchase results too.

States include `queued`, `processing`, `rejected`, `submitted`, `completed`, `failed`, `not_searched`, and
`interrupted`. Backend-specific states and reports are retained in `result.engine`. `submitted` is not proof
of verification. A stub run ends as `not_searched`. A crash during processing marks the job `interrupted`
on startup; it requires operator inspection rather than automatically repeating a potentially completed operation.

`GET /requests/{order_id}` returns the persisted handoff, status, and result. It is an internal endpoint,
authenticated with `Authorization: Bearer <PROXY_SHARED_SECRET>`. Do not give this server secret to client agents.
`GET /health` reports the active parser and backend. The demo retains its submission receipt; it does not poll MS results.

## Configuration

| Variable | Meaning |
|---|---|
| `PROXY_SHARED_SECRET` | Required; shared with the proxy and existing verifier backend |
| `MS_DATABASE` | Optional SQLite path |
| `SPEC_PARSER` | `auto`, `rules`, or `claude`; moved from proxy |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` | Credentials for the existing Claude parser |
| `ANTHROPIC_MODEL` | Explicit Claude model ID; defaults to `claude-opus-5-5` in development |
| `SPEC_ALLOW_RULE_FALLBACK` | `1` allows rules after Claude failure; production requires `0` |
| `ENGINE_URL` | Search/verifier backend URL; unset selects the explicit stub |
| `ENGINE_KIND` | `auto`, `agent_v1`, `http`, or `stub` |
| `VP_AGENT_KEY` / `ENGINE_AGENT_KEY` | Required agent-v1 backend bearer credential; no built-in development fallback |
| `ENGINE_API_KEY` | Bearer credential for the legacy HTTP adapter; required in production |
| `VP_PROXY_MODE` | `supervised`, `purchase_only`, or `autonomous` |
| `ENGINE_POLL_S` | Optional initial polling budget for the agent-v1 adapter |
| `MS_SUPPLIER_HOSTS` | JSON mapping of exact listing hostnames to trusted supplier IDs, e.g. `{"supplier.example":"sup_01"}` |

See [CONFIGURATION.md](../CONFIGURATION.md) for private settings generation, provider inputs, redacted preflight,
and startup commands. `PAPR_ENV=production` requires explicit live parsing/backend configuration and disables
silent parser degradation. A passing preflight does not validate remote credentials or formal proofs.

The live web-search and SMT solver implementation is still in the separate
[agent-purchase-verifier](https://github.com/mtptru/agent-purchase-verifier) repository.
This refactor relocates the existing preparation logic and backend integration into MS; it does not copy that
external code or implement a replacement solver. MS now owns the invocation, monitoring, and database output.

See the [root README](../README.md) for PowerShell startup. Use one MS worker on port 8001; the external
backend must use a different port. On Unix, `make dev` runs MS with the offline stub, and `make dev-linked`
connects to a verifier at `http://127.0.0.1:8002` by default.

Run all backend tests with `python -m pytest -q` from the repository root.

## Shared listing verification

`search_mode=agent` stops after requirements preparation in `awaiting_candidates`. MS computes a
`requirements_id` from the order ID, compiled specs, and authorized limits. A signed internal
`POST /requests/{order_id}/candidates` carries `{order_id, submission, proxy_sig}`; clients use the
proxy endpoints described in [proxy/README.md](../proxy/README.md#personal-agent-candidates).

MS validates the immutable requirements binding and batch ID, stores the original candidates in SQLite,
and moves to `candidates_queued`. The worker independently retrieves each URL, checks evidence,
and stores per-candidate results before moving to `verification_complete`.
Interrupted checks use the existing `interrupted` state on restart rather than claiming verification completed.

The shared `ListingVerifier` also runs on candidates returned by managed search, including candidates
obtained through later backend polling. A backend `proved` or `verified` flag is never evidence for this checker.
Managed backends should return `candidates` or `top` entries containing `url` (or `product_url`), optional `sku`,
and typed `claims` in the same format as agent submissions. For simple existing responses, `name`, `sku`,
`price_cents`, and `currency` become claims automatically. Unsupported response shapes remain unverified.
At most 10 managed candidates are checked per response; any additional count is explicitly reported.

The first evidence adapter supports [Schema.org Product](https://schema.org/Product) JSON-LD on supplier
pages or JSON responses, including a single unambiguous Offer and typed `additionalProperty` measurements.
It does not run page JavaScript or use client-generated summaries. Multiple products require a matching SKU;
multiple offers, conflicting properties, unknown units, inaccessible pages, and missing data remain unverified.

Results distinguish:

- `claims_status`: whether the submitted assertions match current supplier-published evidence.
- `requirements_status`: whether that evidence meets the compiled numeric/text conditions, requested
  condition, currency, known category restrictions, approved-supplier mapping, and configured total cost.
- `claim_checks` / `requirement_checks`: observed values and supported/contradicted/unverified outcomes.
- `evidence`: final source URL, retrieval timestamp, and SHA-256 content hash.

Supplier identity comes only from `MS_SUPPLIER_HOSTS`, never an agent's supplier claim. Unknown suppliers
cannot satisfy the approved-supplier or freight checks. Totals use quantity, policy tax, and policy freight;
they are not live checkout quotes. Evidence checks establish what a supplier publishes, not independent
manufacturer certification, semantic suitability of every product, or real-world truth. The persisted external
solver report remains separate; this evidence checker does not implement a replacement SMT solver.
Use `result.verification` for these claim checks rather than a backend's status label. `verification_complete`
means checks finished, not that every claim passed. Every report sets `purchase_authorized: false`.

The fetcher accepts only public HTTPS addresses, resolves and pins the connection to a checked IP while
preserving TLS hostname validation, revalidates redirects, omits credentials/cookies, and limits response
size and time. Local addresses and cloud metadata endpoints cannot be fetched via submitted URLs.

MS adds no ranking, best-product selection or purchasing action. Account login, OAuth and the MCP endpoint
belong to the [proxy](../proxy/ACCOUNTS.md); MS receives resolved profiles in signed handoffs and does not handle credentials.
