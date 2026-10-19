# Generic enterprise demo

A fictional employee workspace with role-specific example projects, tasks, meetings, working documents, and company updates. The main dashboard has no purchasing panels or demo labels; **Request order** is the only entry point to the order flow. Everything for this demo lives in this folder. It uses plain HTML, CSS, browser JavaScript, and a dependency-free Node server.

## Run

Requires Node.js 22 or newer. No dependency installation is needed.

```powershell
cd demo
npm start
```

Open **http://127.0.0.1:3000**. Use `npm run dev` to restart the server automatically after server edits. Refresh the browser after frontend edits. Set `PORT` to change the local port.

For a side-by-side presentation, open the address in two browser windows and snap one to each half of the laptop screen. Select Northstar in one window and Meridian in the other through **Account settings**. The responsive layout targets roughly 640–720 CSS pixels per window: navigation moves above the dashboard, the welcome panel is shorter, and the three metrics stay together. Below 620 pixels, priorities and the agenda stack into full-width cards. Account selection is saved in shared browser storage, so after reloading both windows, select their separate accounts again if needed.

## Demo flow

1. Click your avatar/name in the upper-right corner (or **Account settings** in the sidebar), choose a company and employee, and click **Save account**.
2. Click **Request order** and describe the purchase.
3. Expand **Preview outgoing JSON** to inspect the exact request and selected configurations.
4. Click **Send request**. The app sends an HTTP POST to `http://127.0.0.1:8000/orders` by default.
5. A successful HTTP response saves a receipt. Open **Request order → Your requests → View** to inspect the payload and service response.

**Connection settings** lets you change the full URL and bearer token. You can also set `ORDER_SERVICE_URL` and `ORDER_SERVICE_TOKEN` before startup to change the initial defaults (`http://127.0.0.1:8000/orders` and `dev-only-token`). A previously saved browser endpoint takes precedence. “Configured” means a URL is saved; it is not a live health check.

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
- Each employee's `companyId` links them to their company. Account settings is the only place to switch company or employee; cancelling leaves the saved account unchanged. The request form uses that saved account automatically.
- Northstar uses a navy-and-brass workspace with compass artwork. Meridian uses a red-and-rose research workspace with orbital artwork, softer panels, and its own branding. The selected company controls the appearance and the visible request history.
- The employee configuration list shows only the saved account's company. Editing a profile does not switch the signed-in account.
- Profile revision 2 replaces the original demo profiles on the next reload while preserving the saved service URL and request history. Later edits to the new profiles persist normally.
- **Account settings → Manage account profiles** supports editing, creating, duplicating, and downloading employee or company JSON objects.
- The CEO sees strategy and company initiatives; the intern sees onboarding and learning; the researcher sees studies and datasets; the operations specialist sees facilities, schedules, and service tickets. All these figures and activities are illustrative fixtures, not live company information.
- Task checkboxes persist separately for each employee/company account. Project progress, meetings, working-document listings, and announcements are static example content.
- Browser changes are saved to localStorage, together with selected profiles, the service URL, a total sent count, and the latest 25 successful requests. They do not overwrite the seed files.
- The bearer token stays in this tab's memory and is cleared on reload. Do not put secrets in the demo profiles or request text, which are stored locally.
- To restore seed profiles, clear the `generic-enterprise-v1` localStorage key and reload. Seed file edits appear in new browser state.
- The interface uses local system fonts and does not require an external font service.

## Verify

```powershell
npm ci
npm run check
npm test
```

Development dependencies are needed only for tests; running the dashboard still requires no installation. DOM tests verify account selection, cancellation, persistence, company-specific history, outgoing profile objects, role-specific dashboard content, per-account task completion, and the absence of purchasing/demo labels outside the order flow. These tests emulate the DOM and do not verify visual rendering. Server tests use a temporary local receiving service, never `pbapo.me`, and verify complete JSON forwarding, optional authentication, successful receipts, upstream rejections, input validation, origin checks, and unreachable-service errors. The live service's route and schema still need to match the outgoing contract before an end-to-end live demo.
