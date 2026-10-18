# Decisions (proxy / "Acme Corp Purchasing")

One line each. Lines marked **[contract]** affect the demo website or the engine team.

## Architecture (from the 2026-10-17 redesign)
- The proxy is a standalone API: caller → proxy (authorize + policy + spec) → engine → response to caller. The portal UI, fake agent, Outbox, cart approval and manager queue were removed.
- The proxy forwards synchronously and returns the engine's response as-is under `engine`; it doesn't inspect or re-check the engine's result.
- Claude proposes the spec and deterministic code decides everything (authorization, policy, limits, unit conversion, weight normalization).
- Spec parser: `claude-opus-5-5` via `client.beta.messages.parse` with a Pydantic schema, adaptive thinking, effort `medium`, and `fallbacks: "default"` (server-side refusal fallback).
- If Claude is unavailable, declines, or returns nothing usable, the rule-based parser is used and a note says so; the deterministic gates still run either way.
- `SPEC_PARSER=auto` uses Claude only when `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN` is set, so `make dev` and tests run offline.

## Auth  **[contract]**
- The caller sends `auth = {user_id, issued_at, expires_at, sig}`; `sig` is hex HMAC-SHA256 over canonical JSON of the other three fields (sorted keys, no whitespace, UTF-8, `ensure_ascii=False`).
- Role, limits and policy come only from the proxy's `data/*.json`; the caller can't send them.
- Auth fails if the signature is wrong, any extra field is present, `issued_at` is more than 60 s in the future, or now ≥ `expires_at`. `make_auth` defaults to 30 min.
- Without `PROXY_SHARED_SECRET` the proxy refuses to start; `make dev` sets a local-only default.

## Authorization vs policy
- `not_authorized`: bad auth or unknown user (401); purchasing disabled, $0 limit, or daily/job cap already reached (403).
- `violates_company_policy` (403): blocked category from the parser, OR a blocked keyword (per category in `blocked_keywords`) in the raw text, item or constraints, OR quantity outside 1–100.
- Keyword matching is a backstop for a parser that mislabels a category (or is prompt-injected); it can over-block (e.g. "gun" in "glue gun"). Tune the lists in `data/company_policy.json`.
- Authorization runs before the parser, so a disabled user's text is never sent to Claude.
- Policy runs before the "unclear" check, so a vague but blocked request is reported as a policy violation.

## Specs, weights, limits  **[contract]**
- The engine payload has `specs`, `weights`, `priority` and `limits`, and is signed as `proxy_sig` (HMAC over canonical JSON of everything else); the engine verifies it with `verify_payload`.
- Constraints are typed: `{field, op ∈ eq|ne|ge|le, value, unit, required}`. The LLM never writes solver code (per the "wrong encoding" risk in the planning doc).
- Numeric values are converted to integers in base units with `Decimal` (no floats): mm, g, MB (decimal GB/TB), W, mV, mAh, Hz, count.
- Rounding is toward the user's side: `ge` rounds up, `le` rounds down, `eq`/`ne` round half up (with a note).
- Required numeric bounds that contradict each other are rejected as `unclear_request` before the engine sees them (the "vacuous truth" risk).
- An unreadable required value is `unclear_request`; an unreadable optional one is dropped, with a note.
- Fields the request didn't mention are left out: the engine must treat them as unknown, not false or zero.
- `condition` is `new|refurbished|used|unspecified`; `unspecified` means the user didn't say.
- `specs.english` renders each constraint in plain English for the caller to show the user.
- Weights are integers that sum to exactly 100 (largest-remainder rounding); unknown or zero weights fall back to defaults.
- `priority` is the lexicographic order (weight descending, then name), so the engine can rank lexicographically instead of trusting arbitrary weighted sums.
- `limits.max_total_cents` = min(user spend limit, daily cap − spent today, job cap − spent on job), covering items + tax + freight.
- A budget in the request can only lower `max_total_cents`, never raise it; a higher one is capped and noted ("my manager said $5,000").
- Approved suppliers with no freight rate on file are left out of `limits.approved_suppliers` (fail closed).
- The auto-buy threshold and manager approval were dropped with the approval flow; reintroduce them if the engine or demo site needs a human-approval step.

## State and audit
- Policy is always read from `data/company_policy.json`; only spend counters live in `var/spend.json` (seeded from the policy file, daily reset at local midnight in America/Los_Angeles).
- The proxy doesn't learn about completed purchases yet, so spend counters don't move. A signed "purchase completed" hook is a follow-up.
- Every `POST /orders` writes exactly one audit entry: `kind=order` if accepted, `attempt` otherwise, with `decision` and `reason`.
- The audit log is append-only JSONL; each entry carries `seq`, `prev_hash` and `hash` = SHA-256 of its canonical JSON. `GET /audit` reports `chain_valid`.
- `GET /audit` is unauthenticated; run the proxy on an internal network or put it behind the demo site.
- Users, suppliers, addresses and emails are fictional (`@acme-demo.example`).
