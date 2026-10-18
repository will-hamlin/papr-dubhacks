# pbapo-uw

Proof Based Agentic Purchase Orders.

## Components

| Folder | Responsibility |
|---|---|
| [demo/](demo/README.md) | Generic employee webpages and local Node relay; fictional finance request ledger at `/admin` |
| [proxy/](proxy/README.md) | Authenticate clients, authorize or deny requests, compile signed handoffs, and deliver every decision to MS |
| [main-service/](main-service/README.md) | Persist decisions, prepare product specs and proof conditions, invoke search/verification, and store output |

```text
Client / connector --POST /orders--> Proxy (:8000)
                                       |
                     signed authorization decision + context
                                       |
                                  MS (:8001) ---> SQLite
                                       |
                      accepted only: spec / proof preparation
                                       |
                         search + verification backend
                                       |
                              results ---> SQLite
```

A rejection is sent to MS for documentation and returned to the client with its reason.
An acceptance queues processing in MS; it does not assert that a product was found or verified.
The proxy and MS run as separate processes on the same server. MS binds to loopback.
Both HTTP API and authenticated Streamable HTTP MCP (`/mcp`) connectors are implemented.
Personal agents use browser account login and OAuth/PKCE; the proxy loads their user and company configuration
from its account database. See [account setup and agent connection](proxy/ACCOUNTS.md).

Personal agents submit `request_id`, `request_text`, and `search_mode: "agent"` through the API or `create_request`
MCP tool. MS prepares requirements and waits for product listings instead of starting managed search.
The client reads `GET /orders/{order_id}`, then sends a requirements-bound batch to
`POST /orders/{order_id}/candidates`. Both endpoints use the agent's OAuth access token and enforce account ownership.
See the [proxy client contract](proxy/README.md#personal-agent-candidates) for an example.

Agent submissions and usable managed-search candidates pass through the same MS listing-evidence checker.
MS independently fetches supplier-published structured product data and records supported, contradicted,
or unverified claims and compiled requirements. There is no candidate ranking or optimality check.
This is evidence checking, not a guarantee that a seller's statements are physically true or permission to purchase.

MS also runs the pinned `agent-purchase-verifier` Z3 core against those fetched facts and PAPR's
compiled requirements. Each proof is bound to the requirements ID, policy contract and source snapshot.
The employee demo distinguishes proven, rejected and unresolved results and exports proof receipts.
The solver reasons from published evidence and explicit identity/policy assumptions; it does not certify a seller.

### Integrated demo

```powershell
python -m pip install -r proxy/requirements.txt -r main-service/requirements.txt
python scripts/run_demo.py
```

Open http://127.0.0.1:3100. The launcher uses isolated data, proxy port 8200 and MS port 8201.
It runs deterministic parsing and fictional listings with real Z3 proofs; no provider credentials are needed.
`python scripts/run_demo.py --smoke` checks charger, laptop and personal-agent workflows and stops the stack.
See [DEMO.md](docs/DEMO.md) and [integration details](docs/VERIFIER_INTEGRATION.md).

## Run locally (PowerShell, from this repository root)

For a complete local walkthrough with real checks and explicitly fictional supplier evidence,
see the [demo guide](docs/DEMO.md). No external search backend is needed in this opt-in mode.

For generated private secrets and validated service startup, follow
[configuration and credentials](CONFIGURATION.md). The commands below are the explicit offline demo setup.
See the [project readiness review](docs/PROJECT_READINESS.md) for remaining release requirements.

Install dependencies in a virtual environment:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r proxy/requirements.txt -r main-service/requirements.txt
```

Start MS in one terminal:

```powershell
$env:PROXY_SHARED_SECRET = 'dev-only-secret'
$env:SPEC_PARSER = 'rules'
.venv/Scripts/python -m uvicorn --app-dir main-service --factory main_service.app:create_app --host 127.0.0.1 --port 8001 --workers 1
```

Start the proxy in another terminal:

```powershell
$env:PROXY_SHARED_SECRET = 'dev-only-secret'
$env:PROXY_API_TOKEN = 'dev-only-token'
$env:MAIN_SERVICE_URL = 'http://127.0.0.1:8001'
# Only for the existing editable-profile demo below; keep unset for account-only deployments.
$env:PROXY_ALLOW_LEGACY_CONFIG = '1'
.venv/Scripts/python -m uvicorn --app-dir proxy --factory proxy.app:create_app --host 127.0.0.1 --port 8000 --workers 1
```

Start the example client in a third terminal:

```powershell
npm --prefix demo start
```

Open http://127.0.0.1:3000. On Unix, use `.venv/bin/python` and `export NAME=value` instead.
Component Makefiles also provide `make dev` and `make test` on Unix.

Without `ENGINE_URL`, MS runs the existing stub and records `not_searched` after preparing requirements.
For optional live product search through the external app, configure **MS**, not the proxy, with `ENGINE_URL`,
`ENGINE_KIND=agent_v1`, `VP_AGENT_KEY`, and `VP_PROXY_MODE` for the existing
[agent-purchase-verifier](https://github.com/mtptru/agent-purchase-verifier) backend.
That backend's full application remains in its separate repository; its solver core is pinned locally in MS. Run the external app on a distinct port
(e.g. 8002); 8001 now belongs to MS. Its shared secret must match MS.

## Verify

```powershell
.venv/Scripts/python -m pytest -q
npm --prefix demo run check
npm --prefix demo test
```

Python tests cover authorization, denied-request documentation, proxy/MS HTTP integration,
durable retry and duplicate handling, proof/spec conversion, and database output using mocked search.
They do not call a live LLM, web search, payment service, or solver backend.
Candidate tests use deterministic supplier-page fixtures and exercise independent fetching, variant ambiguity,
price/quantity/tax/freight checks, private-network blocking, request ownership, and repeat submissions.
Account tests cover OAuth discovery/PKCE, login consent/CSRF, token rotation/revocation, current server policy,
cross-account isolation, and MCP protocol tools. No live Muse account or enterprise identity provider is required.
