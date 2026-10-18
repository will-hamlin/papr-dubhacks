# Generic enterprise dashboard

See [DASHBOARD.md](DASHBOARD.md) for setup, profiles, and the request contract. Run `npm start` from this folder and open http://127.0.0.1:3000.

The purchasing authorization proxy lives in [../demo-proxy](../demo-proxy/README.md), including its Python package, data, tests, and setup files.

The dashboard currently sends its own request/configuration envelope to an editable service URL. It is not yet wired to the proxy's signed-auth `/orders` contract.
