# Agent Purchase Verifier core

Source: https://github.com/mtptru/agent-purchase-verifier
Revision: `79ac1403f263c49a655e723d811ba38115ea933e`
Imported: 2026-10-18, from `verified_purchase/core/`.

`types.py`, `compiler.py`, `units.py`, `verify.py`, and `__init__.py` are the
upstream solver core. The original module documentation is retained. This is a
source integration, not a reimplementation or a claim of independent authorship.
The source repository is private and publishes no license metadata; this copy
does not grant redistribution rights beyond the source owner's permissions.

Local changes: add numeric `ne` to the typed operator contract and compiler,
so PAPR's existing not-equal constraints are preserved exactly.

The PAPR adapter is `main_service/formal.py`. It owns requirements/policy binding,
source-value normalization, and conservative treatment of missing evidence.
Upstream intake, accounts, payments, browser automation, and executable startup
scripts are not imported. Updates must preserve the adapter's regression tests.
