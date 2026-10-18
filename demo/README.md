# Generic enterprise dashboard

See [DASHBOARD.md](DASHBOARD.md) for setup, profiles, and the request contract. Run `npm start` from this folder and open http://127.0.0.1:3000.

The purchasing authorization proxy lives in [../proxy](../proxy/README.md), including its Python package, data, tests, and setup files.

The dashboard sends its request/configuration envelope through the Node relay to the proxy's `/orders` endpoint, using bearer authentication. Connection settings can override the default `http://127.0.0.1:8000/orders` URL.

Set `PROXY_ALLOW_LEGACY_CONFIG=1` on the proxy to enable this editable-profile test connector. It is disabled by default.
Personal agents instead use [account login and OAuth/MCP](../proxy/ACCOUNTS.md), where the server owns their profiles.

## Employee request progress

For the complete integrated stack, run `python scripts/run_demo.py` from the repository root
and open http://127.0.0.1:3100. The two example buttons fill charger/laptop requests without
submitting them. Results show the compiled requirements, real Z3 proof outcomes, source and
proof hashes, and a downloadable JSON proof receipt. The fictional catalog remains clearly
labeled. See [the demo guide](../docs/DEMO.md).

After submitting, the employee demo opens the request details and follows the actual proxy/MS lifecycle. **Request order → Your requests → View** reopens saved records. Accepted requests update every five seconds until processing finishes; **Refresh status** checks again manually. Details show listing claim checks and required conditions separately, including contradictory or missing evidence. A completed workflow or supported evidence does not authorize or place a purchase. If the MS marks a run as a demo, the view explicitly labels simulated supplier evidence. Proxy denials are saved with their reason, without polling access.

For the legacy demo connector, the proxy issues a per-request `request_token`. The Node relay retains that token in memory and returns an opaque tracking handle to the browser. `/api/request-status` accepts only a previously issued handle; its destination and token come from that recorded submission, never a polling URL supplied by the browser. Redirects and cross-origin browser requests are rejected, and responses are bounded. No operator signing secret is needed or exposed. The browser saves at most 25 request records and their latest results locally; it does not store the upstream request access token.

Tracking expires after 24 hours, when the proxy access expires, or when the Node demo server restarts (at most 1,000 handles are retained). The last saved status/evidence stays visible when tracking expires or the service is temporarily unavailable. Older receipts or upstream services without a request capability remain receipt-only. This is an explicitly local demo connector, not a production account, history, or authentication implementation; keep `PROXY_ALLOW_LEGACY_CONFIG=1` limited to demo runs.

## Finance review demo

Open **http://127.0.0.1:3000/admin** on the same Node server for a read-only finance workspace. It includes 18 fictional historical requests across two companies, with fulfilled, denied, pending, awaiting-purchase-review, and verification-failed outcomes. Search by request, employee, department, supplier, or channel; combine company, outcome, and evidence filters; sort by date or amount. Summary cards follow the active filters, and fulfilled spend excludes every unpurchased request.

Select a request to review its policy snapshot, authorization decision, claim/condition checks, source reference, and activity trail. Evidence support and fulfillment are separate states. Every source uses a reserved `.example` domain, and no evidence was fetched. The fictional evidence reports are **not formal solver proofs or cryptographic certificates**; fulfillment is a separate simulated procurement event. No approval, payment, account administration, or live database operation is available here.

The fixture database lives in `fixtures/finance-requests.json` and is exposed by the read-only `/api/admin/demo-requests` endpoint. **Export filtered records** downloads the visible records, including evidence and events, as JSON with their fictional-data notice. This is a local public demo, not an authenticated finance/admin application. Do not put real account or purchase records in its fixtures or expose it as a production administration service.

Run `npm ci`, `npm test`, and `npm run check` to install development test dependencies and verify both the employee and finance demos. The server itself has no third-party runtime dependencies.
