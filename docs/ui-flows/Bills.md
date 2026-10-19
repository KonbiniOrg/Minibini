# Bills — RETIRED (2026-07-23)

The in-app Bill domain (vendor invoices, bill payments, bill↔PO links) was
retired on 2026-07-23: bills live entirely in QuickBooks Online. The
walkthrough that used to be here described surfaces that no longer exist.

- What replaced it and why: `docs/designs/quickbooks-integration.md`
  → "Bill push — retired 2026-07-23", and
  `docs/designs/materials-inventory-and-purchasing.md` §13 "Bills retired → QBO".
- The guard that the old surfaces stay gone (nav, search, PO detail,
  business detail): `e2e/specs/bills-retired.spec.js`.
- The one vendor-invoice email flow that remains (link an email to its PO)
  is covered in `Purchasing.md`.
- The `Bill`/`BillLineItem`/`BillPayment` tables still exist as schema-only
  stubs pending a drop migration — tracked in `docs/designs/LATER.md`.
