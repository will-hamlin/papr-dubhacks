# Generic enterprise demo

A small, fictional employee purchasing dashboard. Everything for this demo lives in this folder. It uses plain HTML, CSS, browser JavaScript, and a dependency-free Node server.

## Run

Requires Node.js 22 or newer. No dependency installation is needed.

```powershell
cd generic-enterprise
npm start
```

Open **http://127.0.0.1:3000**. Use `npm run dev` to restart the server automatically after server edits. Refresh the browser after frontend edits. Set `PORT` to change the local port.

## Demo flow

1. Choose an employee and company in **Request details**.
2. Click **Request order** and describe the purchase.
3. Expand **Preview outgoing JSON** to inspect the exact request and selected configurations.
4. Click **Send request**. The app sends an HTTP POST to `https://pbapo.me` by default.
5. A successful HTTP response adds a receipt to **Recent requests**. Click **View** to inspect the payload and service response.

The hostname was provided without an API path or service schema. **Connection settings** lets you change the full URL (for example, to an eventual `/orders` route) and enter an optional bearer token. You can also set `ORDER_SERVICE_URL` before startup to change the initial default. A previously saved browser endpoint takes precedence. “Configured” means a URL is saved; it is not a live health check.

The local server relays the request so the remote service does not need browser CORS configuration. It binds only to `127.0.0.1`. The relay is intended for a local demo, not deployment as a publicly accessible proxy.

## Outgoing contract

`Content-Type: application/json`, with `Authorization: Bearer <token>` only when supplied:

```json
{
  "request": {
    "id": "generated-uuid",
    "createdAt": "2026-10-18T00:00:00.000Z",
    "text": "We need 6 adjustable monitor arms, with a $900 budget."
  },
  "userConfig": {
    "employeeId": "EMP-1042",
    "name": "Alex Morgan"
  },
  "companyConfig": {
    "companyId": "CO-001",
    "name": "Northstar Industries"
  }
}
```

The complete configuration objects are sent unchanged, including all custom fields. The example above abbreviates them. The endpoint and token are not included in the outgoing body. A retry keeps the same request ID while the form remains open; the receiver can use it for deduplication. The relay does not automatically retry. Any 2xx response counts as delivery; order approval remains the receiving service's responsibility. Errors leave the form intact. A timeout can mean delivery is uncertain, so check the receiver before retrying.

## Configurations and persistence

- Two company JSON files and four employee JSON files live under `configs/companies/` and `configs/users/`.
- Northstar Industries has Alex Morgan (CEO) and Jamie Chen (intern). Meridian Labs has Sam Rivera (researcher) and Taylor Brooks (operations specialist).
- Each employee's `companyId` links them to their company. Employee menus and the configuration list show only the selected company's employees.
- Profile revision 2 replaces the original demo profiles on the next reload while preserving the saved service URL and request history. Later edits to the new profiles persist normally.
- **Configurations** supports editing, creating, duplicating, and downloading employee or company JSON objects.
- Browser changes are saved to localStorage, together with selected profiles, the service URL, a total sent count, and the latest 25 successful requests. They do not overwrite the seed files.
- The bearer token stays in this tab's memory and is cleared on reload. Do not put secrets in the demo profiles or request text, which are stored locally.
- To restore seed profiles, clear the `generic-enterprise-v1` localStorage key and reload. Seed file edits appear in new browser state.
- The interface uses local system fonts and does not require an external font service.

## Verify

```powershell
npm run check
npm test
```

Tests use a temporary local receiving service, never `pbapo.me`. They verify complete JSON forwarding, optional authentication, successful receipts, upstream rejections, input validation, origin checks, and unreachable-service errors. The live service's route and schema still need to match the outgoing contract before an end-to-end live demo.
