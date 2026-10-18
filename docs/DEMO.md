# Local demo

This demo runs real account authentication, proxy authorization, requirement preparation,
listing checks, persistence, and request-status polling. Its opt-in catalog and supplier pages
are fictional. It performs no live web search, formal solver proof, ranking, or purchase.
The finance `/admin` ledger remains a separate fictional historical dataset.

## Current preview

- Employee request demo: http://127.0.0.1:3000
- Finance history demo: http://127.0.0.1:3000/admin
- Account login / agent consent: http://127.0.0.1:8100/account
- Main service: loopback port 8101; never exposed publicly.

The preview uses ignored database directories `proxy/var/ui-preview/` and `main-service/var/ui-preview/`. The provider
credential is read from the ignored root `.env.local`; only the main service receives it.
Claude prepares requirements using the configured model. A parser failure is shown as a failed
request rather than silently switching to simpler rules. AI parsing uses provider credits.

## Try the employee path

Choose an employee who may purchase and submit one of:

- `65W USB-C charger under $40`
- `laptop with at least 32 GB RAM under $1000`

The MS demo catalog supplies a matching listing, a weaker listing with an intentionally false
claim, and a stapler. The shared checker reports each claim and requirement independently.
The weaker item should contradict the power/RAM requirement; an unrelated stapler must not
satisfy a charger or laptop request. Completion means checks finished, not that every listing passed.

The catalog supports chargers and laptops only. Other products produce no matching demo listings.
Unsupported requirements remain unresolved or fail preparation; they must not be reported as met.
Company limits still apply, including tax and freight. Fixture supplier `sup_01` must be approved
by the account policy. No policy is overridden to manufacture a passing result.

## Personal agent path

Use the OAuth account and MCP connection documented in [ACCOUNTS.md](../proxy/ACCOUNTS.md).
`create_request` defaults to agent search. Poll `get_request` until `awaiting_candidates`, then
submit the exact returned `requirements_id` with a new submission ID. Example candidate:

```json
{
  "candidate_id": "charger-65",
  "url": "https://catalog.papr.example/charger-65",
  "sku": "DEMO-CH65",
  "claims": [{"field": "power", "value": 65, "unit": "W"}]
}
```

Other demo paths are `charger-30`, `laptop-32`, `laptop-16`, and `stapler`; SKU values are
`DEMO-CH30`, `DEMO-L32`, `DEMO-L16`, and `DEMO-ST`. The internal `/demo/catalog` endpoint lists
candidate envelopes. These reserved `.example` URLs never resolve over the network: the demo
factory supplies fixed source bytes. Unknown URLs remain unverified. Normal service startup
continues to use the real SSRF-protected listing fetcher.

## Start a fresh demo

After installing dependencies and initializing settings as described in
[CONFIGURATION.md](../CONFIGURATION.md), launch MS with:

```powershell
python scripts/configure.py run --env-file .env.local --service main-service --demo
```

In another terminal launch the proxy normally:

```powershell
python scripts/configure.py run --env-file .env.local --service proxy
```

These commands use the default ports 8001 and 8000, unlike the existing preview's 8101/8100.
For the legacy employee demo, explicitly enable `PROXY_ALLOW_LEGACY_CONFIG=1` in the local
profile, point the demo's endpoint at the proxy `/orders`, and configure its Node server with
the same operator API token. Keep that mode local. Account/MCP requests load server-owned
profiles and do not need legacy mode. `npm --prefix demo start` serves the employee and finance UIs.

The `--demo` switch refuses production settings. Evidence includes `simulated: true`,
`basis: demo_fixture`, a fixture version and source snapshot; it never becomes a formal proof.

## Verified on 18 October 2026

197 Python tests and 27 JavaScript tests pass. The Python suite includes the official MCP SDK
OAuth/refresh/candidate flow against in-process services; an external Muse connection has not been tested.
In the running browser preview, a real Claude-parsed laptop request passed through proxy authorization,
persisted MS processing and automatic UI polling: the 32 GB laptop passed, the 16 GB laptop's RAM claim
was contradicted, and the stapler's truthful price claim passed while product suitability failed.
The completed results remained viewable after a browser reload. No public deployment or purchases occurred.
