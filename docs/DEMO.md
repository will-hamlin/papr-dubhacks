# Integrated verification demo

The demo runs real proxy authorization, requirement preparation, independent listing
checks, Z3 proofs, persistence and UI polling. Supplier listings are fictional and
visibly labeled. No live search or purchases occur. The finance `/admin` history
remains a separate fictional dataset.

## Start the full stack

```powershell
python -m pip install -r proxy/requirements.txt -r main-service/requirements.txt
python scripts/run_demo.py
```

Open http://127.0.0.1:3100. The launcher starts the proxy on 8200 and MS on 8201,
checks readiness, and prints the URL only when all three services are ready.
Ctrl+C stops its processes. Existing previews are not stopped or reconfigured.
If a port is occupied, use `--web-port`, `--proxy-port`, and `--service-port`.

The default rules parser is deterministic and needs no provider credentials.
For AI parsing, explicitly use:

```powershell
python scripts/run_demo.py --parser claude --env-file .env.local
```

That mode uses the configured Anthropic credential/model and provider credits.
Parser failures are shown as failures; it does not silently switch to rules.

Private demo secrets are generated once in ignored `secrets/verifier-demo.env`.
Data lives in `proxy/var/verifier-demo/8200-8201/` and `main-service/var/verifier-demo/8200-8201/`;
service logs live in the latter directory's `logs/` folder. Custom port pairs use
separate data subdirectories. The employee UI uses
local legacy demo profiles. Account/OAuth tests exercise the separate account path.
Do not expose the legacy demo stack publicly.

## Present the employee flow

### Recording checkpoint (2026-10-18)

The merged demo, including Muse OAuth compatibility, passed 222 Python tests,
30 frontend tests, and the three HTTP smoke workflows. The ThinkPad deployment
also passed 222 tests and a public OAuth/MCP run with Claude parsing, candidate
submission, real Z3 proofs, refresh, duplicate handling and policy denial.

The recording stack on the Windows development machine is available at
<http://127.0.0.1:13100>. To start that same isolated stack again when it is stopped:

```powershell
python scripts/run_demo.py --web-port 13100 --proxy-port 18200 --service-port 18201
```

Use the charger or laptop example below. The local stack uses deterministic rules;
the hosted ThinkPad stack uses Claude. Both use fictional supplier listings and
the same real Z3 verifier. No purchase is executed. The finance ledger is separate
fictional history, not a live mirror of these requests.

For a Muse recording, complete a fresh PAPR connection in Muse first. A passing
SDK integration test does not confirm Muse's own connection. Use the documented
fixture candidates in the personal-agent section, rather than asking Muse to
find live retailer URLs; the hosted demo only accepts the fictional catalog.
The temporary Cloudflare hostname can change if its tunnel restarts.

On NixOS, the pip Z3 wheel also needs the C++ runtime. The ThinkPad service uses
a rooted GCC library output at `~/papr/z3-runtime` and
`LD_LIBRARY_PATH=/home/will/papr/z3-runtime/lib` in its private main-service
environment. Keep this setting when restarting or updating that service.

### Walkthrough

1. Select an employee who may purchase and click **Request order**.
2. Choose **65W USB-C charger · $40 limit** or **32 GB laptop · $1,000 limit**.
3. Send the request. The receipt updates automatically.
4. Review the compiled conditions and authorized total limit.
5. Each example should show **1 Proven**, **2 Not satisfied**, **0 Unresolved**.
6. Open a product's condition details to see the exact observations. The weaker
   charger/laptop fails its power/RAM requirement. The stapler fails product identity
   even though its own price claim is supported.
7. Expand **Proof & source record** for hashes and assumptions, or choose
   **Save proof receipt** for the full JSON record, including replayable solver queries.

The catalog supports chargers and laptops only. Other requests return no matching
fixtures. Unsupported requirements remain unresolved or fail preparation. Tax,
freight, company limits and approved suppliers still apply; none are bypassed to
manufacture a passing proof. A proof establishes implications from source facts
and declared assumptions, not that the seller's claims are physically true.

## Personal-agent flow

Account setup and OAuth/MCP connection are documented in
[ACCOUNTS.md](../proxy/ACCOUNTS.md). Provision accounts against the isolated demo
proxy data directory when using this stack. `create_request` defaults to agent
search. Wait for `awaiting_candidates`, then submit the returned `requirements_id`
with a fresh submission ID and a candidate such as:

```json
{
  "candidate_id": "charger-65",
  "url": "https://catalog.papr.example/charger-65",
  "sku": "DEMO-CH65",
  "claims": [{"field": "power", "value": 65, "unit": "W"}]
}
```

Other fixture paths are `charger-30`, `laptop-32`, `laptop-16`, and `stapler`; SKUs
are `DEMO-CH30`, `DEMO-L32`, `DEMO-L16`, and `DEMO-ST`. Reserved `.example` URLs
are resolved to fixed source bytes only by the explicit demo factory. The normal
service retains its public HTTPS fetcher and private-network blocking.

Both paths use the same evidence checker and local solver. Each persisted proof
is bound to the original requirements ID and source snapshot.

## Verify before presenting

With the default demo ports free:

```powershell
python scripts/run_demo.py --smoke
python -m pytest -q
npm --prefix demo run check
npm --prefix demo test
```

The smoke command starts all three services, submits two managed requests and one
legacy personal-agent request over HTTP, verifies exact proof outcomes and then
stops the stack. Account/OAuth/MCP coverage is provided by the Python integration
suite. It does not claim that a live external agent or retailer was exercised.

The optional external search application's identity, approval and payment gaps
are documented in [VERIFIER_INTEGRATION.md](VERIFIER_INTEGRATION.md). This demo
uses its actual solver core locally and does not need the external app running.
