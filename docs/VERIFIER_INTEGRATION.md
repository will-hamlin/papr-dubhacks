# Verifier integration

## Architecture

```text
Employee UI / personal agent
           |
       PAPR proxy      account ownership, policy authorization, durable outbox
           |
       Main service    immutable compiled requirements and company limits
           |
   Candidate discovery (demo catalog, personal agent, or optional external engine)
           |
   Independent listing fetch and evidence checks
           |
   Pinned Agent Purchase Verifier compiler + Z3
           |
   SQLite result -> proof summary, condition details, downloadable receipt
```

The imported core is pinned to `mtptru/agent-purchase-verifier` commit
`79ac1403f263c49a655e723d811ba38115ea933e`. See the source attribution and local
patch inventory in `main-service/main_service/vendor/purchase_verifier/UPSTREAM.md`.
The numeric not-equal operator is the only change to the imported core.

## Exact contract

The local adapter receives only the MS-compiled `specs`, authorized `limits`, and
facts extracted from independently fetched supplier bytes. Candidate claims and
remote `verified` / `proven` flags cannot supply proof evidence.

Every required product constraint is encoded. Numeric properties use exact
rational conversion into integers at one trillionth of PAPR's compiled base unit;
values not exactly representable remain unknown. Text comparisons preserve the
existing trimmed, case-insensitive semantics. Unknown enum values have an explicit
other-value slot so a one-value vocabulary cannot fabricate evidence.

The model includes currency, requested condition, configured quantity/tax/freight
total, and explicit product-identity, supplier-approval and category predicates.
Those last three predicates are assumptions computed by the existing checker,
not claims that Z3 independently understands products or authenticates suppliers.
Optional preferences are not hard constraints and the integration adds no ranking.

The solver first checks consistency, then checks whether the facts and rules can
coexist with a violation of the requirements. A satisfiable counterexample rejects
the candidate; an unsatisfiable violation establishes entailment. Missing inputs,
unsupported requirements and timeouts cannot establish a complete proof.

Each receipt binds the order's `requirements_id`, the full specs/policy contract,
source snapshot, solver spec and solver facts. It stores replayable SMT-LIB queries.
The receipt digest detects changes when compared with a trusted copy; it is not a
digital signature. Evidence support, formal proof and purchase permission remain
separate. No local workflow authorizes or executes payment.

## Optional external discovery

The existing `AgentV1Engine` still posts signed requests to `/v1/proxy/search` and
polls `/v1/requests/{id}`. Returned usable candidates go through the same local
evidence and proof path. The UI shows questions and links to a separate verifier
review when requested; escalated requests remain pollable after human review.

This is not an end-to-end integration of the external purchasing application:

- The upstream bridge stores PAPR specs/limits as context but reparses the request
  using its own policy and demo identity. Only the local proof establishes the
  PAPR contract; do not treat external approval as PAPR purchase permission.
- External employee identity mapping, approval delegation and payment execution
  require a separate contract before a live company pilot.
- The upstream launcher hardcodes port 8001. Run its app separately on an unused
  port such as 8002 and set its application URL accordingly.
- Upstream bridge idempotency is process-local. PAPR preserves its existing
  refusal to automatically replay uncertain backend submissions.
- Retailer synthetic URLs and inaccessible listings remain unresolved by PAPR's
  public HTTPS evidence checker. No SSRF exception was added for the other app.

The integrated demo uses the local solver and fixtures, so it does not depend on
those external lifecycle gaps, a second login, live retailer APIs or provider uptime.

## Verification

Run `python -m pytest -q`, `npm --prefix demo run check`, and `npm --prefix demo test`.
Run `python scripts/run_demo.py --smoke` while its three ports are free for a real
HTTP test of managed charger/laptop requests and personal-agent submissions.
The smoke test checks exact outcomes and that no purchase was authorized.
