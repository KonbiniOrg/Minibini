# Spec: QBO invoice as primary document

Branch: `feature/qbo`. First of three QBO-deepening changes (later, separately: remove
`Bill` in favor of QBO-native bills; setup-time pull of existing QBO data into konbini).

## Goal

The QBO invoice becomes the primary invoice document. Konbini still composes the
invoice (wizard over the job's billable atoms) and still sends the email, but the
document the customer receives — number, PDF, tax, payment experience — is QBO's.
Line items push individually instead of being bundled per accounting category.

## Decisions

### Per-line push

- `InvoiceGroupingService` (`apps/invoicing/services.py`) is deleted.
- The QBO invoice builder walks `invoicelineitem_set` in line order. Each konbini
  line becomes one `SalesItemLine`:
  - `Amount` = line total.
  - `Description` = the line's own text, verbatim (wizard edits ride along).
  - `ItemRef` resolved in order: the line's linked catalog entity's `qbo_id`
    (InventoryItem or ServiceItem, minting the QBO Item lazily if absent — see
    below) → else the line's AccountingCategory's `qbo_item_id` (the generic
    fallback Item) → else omitted (QBO applies its default).
  - `TaxCodeRef` per line from `TaxCalculationService.get_effective_taxability`,
    same as today.
- `CustomerMemo` on the QBO invoice carries the job reference:
  `Job {job_number} — {job name}`. (Per-invoice custom messaging lives in
  konbini's email body, not on the QBO document.)
- `BillEmail` set from the invoice contact's email so the QBO record is complete.
- `AllowOnlineCreditCardPayment` and `AllowOnlineACHPayment` set true on push.
  Requires the company to have QBO Payments activated (one-time setup in QBO).

### Lazy catalog mirroring (konbini → QBO)

- `InventoryItem` and `ServiceItem` each gain a plain `qbo_id` CharField
  (max_length=50, blank, default `''`). Not the `QBOSyncable` base — a failed
  Item mint fails the invoice push, whose existing failure path covers retry;
  catalog entries need no independent sync lifecycle.
- Minting happens mid-push, only when a line references a catalog entity with no
  `qbo_id`:
  - ServiceItem → QBO Item type `Service`. InventoryItem → type `NonInventory`
    (never QBO's `Inventory` type — quantity tracking stays in konbini).
  - `Name` = the konbini entity's name (`template_name` / InventoryItem name).
  - `IncomeAccountRef` copied from the category's generic fallback Item, fetched
    from QBO at mint time. The bookkeeper configures income accounts exactly
    once, in QBO, on the per-category Items; konbini never stores income
    accounts.
  - On QBO's duplicate-name error: query the existing Item by name and adopt its
    Id. This also converges with catalogs that already exist in QBO. Accepted
    consequence: two same-named konbini entities bind to the same QBO Item.
- Category prerequisites already hold: `InventoryItem.accounting_category` is a
  required PROTECT FK; ServiceItem reaches a required category via its required
  `rate_scheme`.
- Post-mirror renames in konbini do NOT propagate to the QBO Item (Description
  carries the real text on every line). Rename sync → LATER.

### Numbering

- QBO assigns the invoice number. Konbini stops generating invoice numbers: the
  `'invoice'` NumberGenerationService pattern is retired and `Invoice.save()` no
  longer auto-fills `invoice_number`.
- After push, QBO's `DocNumber` is written back into `invoice_number`.
- Drafts display a placeholder identity — `Draft — {job_number}` — everywhere an
  invoice number would show. Single-draft-per-job is already enforced
  (`apps/invoicing/models.py`), so the placeholder is unambiguous.
- Rationale: future tenants arrive with QBO already numbering their invoices;
  konbini attaches to that scheme rather than competing with it.

### Send flow (fused, konbini sends)

One action, as today, in `InvoiceEmailService.send_invoice`:

1. Push the per-line invoice to QBO (minting catalog Items as needed).
2. Read the invoice back with `include=invoiceLink` (minorversion ≥ 36) to get
   the hosted-invoice payment URL.
3. Download QBO's PDF.
4. Mark the QBO invoice `EmailStatus = 'EmailSent'` (suppresses QBO's own email,
   records it as sent in QBO), as today.
5. Send via `OutboundEmailService.send_tracked` — konbini's Configuration-stored
   subject/body templates, To/CC/BCC from the send dialog, QBO PDF attached,
   job-linked `EmailRecord` audit trail. The invoice email body template gains a
   `{payment_link}` placeholder rendering the `invoiceLink` URL.
6. Status draft → open; `DocNumber` writeback per above.

There is NO alternative QBO-sends path. If wanted later it will be added from
scratch.

Payment polling (`poll_qbo_payments`) is unchanged.

### AccountingCategory

Both existing QBO fields stay, roles clarified:

- `qbo_item_id` — demoted from "the ItemRef for every bundled line" to
  (a) fallback ItemRef for lines with no catalog link, and (b) the source of
  `IncomeAccountRef` when minting catalog Items in that category.
- `qbo_expense_account_id` — untouched; still used by expenses (and bills until
  the Bill removal lands).

## Out of scope (queued separately)

- Cancel-from-konbini (must check QBO payment status first).
- Setup-time pull of QBO's existing catalog/data into konbini.
- `Bill` removal.
- Catalog rename propagation to QBO Items (LATER).
- Per-send or config choice of email sender.

## Sandbox spike (before or during implementation)

Verify in the QBO sandbox, manually:

- `invoiceLink` returns in sandbox and the hosted page renders; with the
  Payments sandbox (mock card data, e.g. the documented test amounts) the pay
  button appears when the Allow\* flags are set.
- `CustomerMemo` renders on the hosted invoice/PDF as expected.
- Duplicate-name mint → adopt flow behaves (create Item, then re-create same
  name).
- DocNumber assignment: confirm QBO auto-numbers when `DocNumber` is omitted.

Sandbox email delivery is known-flaky; verify send mechanics via API fields
(`EmailStatus`, `DeliveryInfo`), not inboxes. Production cutover keeps the
existing checklist plus a real-money smoke test (invoice an internal address,
pay by test card, refund).

## Testing

- Backend: mock at the `QBOService` boundary as always. New/updated tests:
  per-line builder output (Description verbatim, ItemRef resolution order,
  per-line TaxCodeRef, CustomerMemo, Allow\* flags, BillEmail), lazy mint logic
  (type mapping, income-account copy, duplicate-name adopt, missing-`qbo_item_id`
  fallback), DocNumber writeback, retired number generation (draft has no
  number), send flow ordering incl. `invoiceLink` fetch.
- Vitest: draft placeholder display, send dialog changes, payment-link
  placeholder in settings' email-template editing if surfaced.
- E2E: wizard → draft placeholder display path (no QBO connection exists in the
  e2e environment, so push/send itself is sandbox-manual, not e2e).

## Follow-on doc updates (same session as implementation)

`docs/designs/quickbooks-integration.md` (push mechanics, Item minting,
invoiceLink), `docs/designs/invoicing-and-expenses.md` (numbering, send flow,
statuses), `docs/designs/estimates-and-prices.md` /
`materials-inventory-and-purchasing.md` (catalog `qbo_id` fields),
`docs/designs/data-constraints.md` (config keys, invoice_number semantics).
