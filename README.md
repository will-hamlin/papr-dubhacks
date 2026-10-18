# papr

dubhacks '26 · Proof Based Agentic Purchase Orders

Employee dashboard + company purchasing proxy. Product search and SMT proofs run in
[agent-purchase-verifier](https://github.com/mtptru/agent-purchase-verifier).

## Local stack

| Service | Port | Start |
|---------|------|--------|
| Dashboard (`generic-enterprise`) | `:3000` | `cd generic-enterprise && npm start` |
| Acme proxy (`demo-proxy`) | `:8000` | `cd demo-proxy && make dev-linked` |
| Verifier + mockstore | `:8001` / `:8765` | `cd ../agent-purchase-verifier && .venv/bin/python scripts/run_pbapo.py` |

Flow: dashboard → `POST /orders` (proxy, policy + Claude/rules parse) → `POST /v1/proxy/search` (verifier) → open `approval_url` for H1/H2.

### One-time setup

```bash
# Verifier (Claude CLI web search when `claude` is on PATH)
cd /Users/maxprince/Documents/GitHub/agent-purchase-verifier
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/run_pbapo.py

# Proxy → verifier
cd /Users/maxprince/Documents/GitHub/pbapo-uw/demo-proxy
make dev-linked

# Dashboard (defaults: http://127.0.0.1:8000/orders + token dev-only-token)
cd ../generic-enterprise && npm start
```

Shared defaults: `PROXY_SHARED_SECRET=dev-only-secret`, `VP_AGENT_KEY=vpk_pbapo_dev_only`,
`VP_PROXY_MODE=supervised` (human H1+H2). Change approval mode in the verifier Settings, or set
`VP_PROXY_MODE=purchase_only|autonomous` on both proxy and verifier.

Claude search on the verifier: `VP_LLM=cli VP_CLI=claude VP_SOURCE=web` (set automatically by
`run_pbapo.py` when the Claude CLI is available). OpenRouter works with `OPENROUTER_API_KEY` + `VP_SOURCE=web`.
