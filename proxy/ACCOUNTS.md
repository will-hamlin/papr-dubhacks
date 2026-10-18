# Accounts and personal-agent connections

The proxy hosts browser login, an OAuth authorization server, and a Streamable HTTP MCP server at `/mcp`.
Personal agents authenticate with OAuth authorization code + S256 PKCE. The browser collects the password;
the agent receives tokens, never the password. Each account belongs to one operator-managed company and user profile.
Every new request reloads those profiles from `proxy/var/accounts.sqlite3`; agents cannot supply or change them.

This is a PAPR account login. Federation with an enterprise identity provider (Entra, Okta, etc.) is not implemented.
There are no preset passwords or public signup that allows choosing a company. Provision accounts locally below.

## Provision accounts

From the repository root, after installing requirements:

```powershell
$env:PYTHONPATH = 'proxy'
# Import an operator-approved company Policy. All monetary fields here are integer cents.
.venv/Scripts/python -m proxy.manage_accounts company proxy/data/company_policy.json
# Create one login from an existing User profile; choose a password at the hidden prompts.
.venv/Scripts/python -m proxy.manage_accounts create-user --company acme --file proxy/data/users.json --user-id u_jordan
.venv/Scripts/python -m proxy.manage_accounts list
```

The example signs in as `jordan.lee@acme-demo.example`. Use your own Policy/User JSON files for real accounts.
Company configuration includes approved supplier IDs, blocked categories/keywords, tax/freight, daily/job caps,
and initial spend. User configuration includes purchasing permission, per-request ceiling, job and ship-to address.
Importing a company again replaces its policy; keep initial spend consistent with any recorded purchases.
Runtime purchases are tracked separately and idempotently by company and job. Outstanding requests do not reserve budget.

`PROXY_VAR_DIR` selects runtime storage; the CLI and server must use the same directory. Alternatively give the CLI
`--database <absolute-path-to-accounts.sqlite3>` before its subcommand. The database, audit and outbox contain private
account/policy information: keep them out of source control and back them up together. Passwords use Argon2id;
opaque access/refresh/session tokens and codes are stored as SHA-256 digests.

Management commands:

```powershell
.venv/Scripts/python -m proxy.manage_accounts update-user <account-id> path/to/user.json
.venv/Scripts/python -m proxy.manage_accounts reset-password <account-id>
.venv/Scripts/python -m proxy.manage_accounts revoke <account-id>
.venv/Scripts/python -m proxy.manage_accounts disable <account-id>
```

Updating the user changes permissions, not the login email or company membership. Resetting a password or disabling
an account revokes its sessions and tokens. Users can also disconnect all agents from `/account`.

## Connect an agent

Set the canonical, externally reachable origin before starting the proxy:

```powershell
$env:PROXY_PUBLIC_URL = 'https://purchasing.example.com'
```

Serve that origin over HTTPS through your reverse proxy to the local proxy process; keep MS on loopback.
Preserve the public `Host` header. HTTP is permitted only on loopback for local development, defaulting to
`http://127.0.0.1:8000`. A remotely hosted agent cannot reach your computer's loopback address.

Register the agent using the exact callback URL supplied by its connector settings:

```powershell
.venv/Scripts/python -m proxy.manage_accounts client --name 'My personal agent' --redirect-uri 'https://agent.example/oauth/callback'
```

Enter the returned public client ID and `https://purchasing.example.com/mcp` in the agent's MCP connection settings.
Use OAuth, with no client secret. Multiple `--redirect-uri` flags are supported. If the client only supports automatic
dynamic registration, set `PROXY_DYNAMIC_REGISTRATION=1` before starting the proxy. Registration is disabled by default;
when enabled, it is rate limited and capped at 1,000 clients. Registered client names are unverified; the consent screen
shows the callback URL and client ID so the user can identify the connection.

The agent discovers authorization metadata, opens PAPR login/consent in a browser, and exchanges the returned code
with its PKCE verifier. It should securely save its refresh token and use it to refresh the 15-minute access token.
Refresh tokens last 30 days and rotate on use; reuse invalidates the token family. Browser sessions last eight hours.
The browser account session is not an API token. Signing out ends the browser session; disconnecting also revokes agents.

The implementation follows the [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
and uses the [official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk) for the protocol transport.
Client-specific Muse setup still requires its actual callback URL and a reachable deployment; no live Muse connection
is provisioned by the repository.

## MCP tools and API

| Tool | Purpose |
|---|---|
| `create_request(request_id, request_text, search_mode="agent")` | Authorize with current account policy and queue MS preparation |
| `get_request(order_id)` | Poll proof requirements and verification results for your order |
| `submit_candidates(order_id, submission)` | Queue URLs and claims bound to MS's `requirements_id` |

The agent creates a request, polls until `awaiting_candidates`, searches, submits listings, and polls until
`verification_complete`. Submission shape and evidence limits are documented in [README](README.md#personal-agent-candidates).
Use a stable request ID on retries; IDs are namespaced per account. Replays return the original decision and compiled
policy snapshot. New requests use current permissions. Candidate submission remains bound to the original requirements.
Revoked/disabled accounts cannot create requests, read orders, or submit candidates. Existing MS work is not cancelled.
The tools do not approve purchases or rank optimal products.

The same access token works with the HTTP API (same resource server):

```http
POST /orders
Authorization: Bearer <OAuth access token>
Content-Type: application/json

{"request_id":"agent-request-1","request_text":"65W USB-C charger under $40","search_mode":"agent"}
```

Use that token for `GET /orders/{order_id}` and `POST /orders/{order_id}/candidates` too. Account orders never issue
the older request capability token. Other accounts' orders return 404. Client-supplied config/identity fields return 400.
MS handoffs contain the resolved company/user profiles and decision, with no OAuth credentials or password hashes.

OAuth endpoints: `/.well-known/oauth-authorization-server`, `/.well-known/oauth-protected-resource/mcp`, `/authorize`,
`/token`, `/revoke`, and opt-in `/register`. Requests to `/authorize` and `/token` must specify
`resource=<public-origin>/mcp`; the only scope is `purchasing`. Callback matching is exact. Codes are one-use and expire
in two minutes. PKCE, audience binding, CSRF, owner checks and revocation are enforced server-side.

## Existing enterprise demo

The shared-token dashboard that sends editable company/user configuration is disabled by default.
To run those existing generic demo webpages locally, explicitly set `PROXY_ALLOW_LEGACY_CONFIG=1` and `PROXY_API_TOKEN`.
That is a trusted test connector, not employee authentication; do not give its shared token to personal agents.
Its older request tokens cannot access account-owned orders. The signed enterprise-user API remains available and
loads profiles from `data/`; its signing secret must stay in trusted server integrations.

`GET /audit` now requires the operator's `PROXY_API_TOKEN`. Account/OAuth tokens cannot read the global audit.
