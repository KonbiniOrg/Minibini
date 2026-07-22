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
  - `TaxCodeRef` per line, read directly from the line's
    `accounting_category.taxable` flag (`'TAX'`/`'NON'`). Every line has a
    category by push time — `_assert_all_lines_categorized` already gates
    `send_invoice`. Konbini decides taxable-or-not (it's what the SPA displays
    per line while composing); QBO owns rates and math.
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

### Dead tax-override removal

`BaseLineItem.taxable_override` and `BaseLineItem.tax_rate_override` are phantom
features: API-writable, no UI ever sets them, and nothing reads
`tax_rate_override` at all. With `InvoiceGroupingService` (the only
`get_effective_taxability` consumer) deleted, they go too:

- Drop both fields from `BaseLineItem` — one migration touching the four
  line-item tables (estimate, invoice, PO, bill).
- Strip them from the line-item serializers (estimates, invoicing, purchasing,
  change_orders) and from the change-order line-copy
  (`apps/estimates/change_order_service.py`).
- Delete `TaxCalculationService` (`apps/core/services.py`) outright.

NOT touched: `Business.tax_exemption_number` and `Business.tax_multiplier`
(`apps/contacts/models.py`) — the real business-level tax fields, currently
display-only. They anchor the future business-level exemption changeset (see
out of scope).

## Out of scope (queued separately)

- Cancel-from-konbini (must check QBO payment status first).
- Setup-time pull of QBO's existing catalog/data into konbini.
- `Bill` removal.
- Catalog rename propagation to QBO Items (LATER).
- Per-send or config choice of email sender.
- Business-level tax exemption: map `Business.tax_exemption_number` /
  `tax_multiplier` onto the QBO Customer's taxable/exempt settings. Note for
  that design: QBO is binary taxable/exempt per customer — the multiplier's
  fractional-rate idea won't map cleanly.

## Sandbox spike (before or during implementation)

Verify in the QBO sandbox, manually:

- `invoiceLink` returns in sandbox and the hosted page renders; with the
  Payments sandbox (mock card data, e.g. the documented test amounts) the pay
  button appears when the Allow\* flags are set.
- `CustomerMemo` renders on the hosted invoice/PDF as expected.
- Duplicate-name mint → adopt flow behaves (create Item, then re-create same
  name).
- Minting Items with a default taxability copied from the category's `taxable`
  flag: confirm how Item-level tax fields interact with Automated Sales Tax
  before committing to setting them (nice-to-have — konbini always sends
  explicit per-line TaxCodeRef regardless; this only helps bookkeepers using
  the Item directly inside QBO).
- DocNumber assignment: confirm QBO auto-numbers when `DocNumber` is omitted.

Sandbox email delivery is known-flaky; verify send mechanics via API fields
(`EmailStatus`, `DeliveryInfo`), not inboxes. Production cutover keeps the
existing checklist plus a real-money smoke test (invoice an internal address,
pay by test card, refund).

## Testing

- Backend: mock at the `QBOService` boundary as always. New/updated tests:
  per-line builder output (Description verbatim, ItemRef resolution order,
  per-line TaxCodeRef from the category flag, CustomerMemo, Allow\* flags,
  BillEmail), tax-override field removal fallout, lazy mint logic
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

## Follow-ups queued on this branch (post-review notes, 2026-07-22)

- **Customer push: adopt-by-name on 6240 — DONE 2026-07-23.** Both customer
  push entry points adopt the existing QBO Customer by DisplayName on a
  duplicate-name error, via shared helpers (`_is_duplicate_name_error` /
  `_adopt_id_by_name`) also used by the Item mint. NOTE: `push_vendor` has
  the identical collision exposure and does NOT adopt yet — decide whether
  to extend (small change, same pattern) or leave until the Bill-removal
  work reshapes the vendor path.
- **Job-statement PDF: dropped from the send (done 2026-07-22).**
  `apps/invoicing/pdf.py` + `templates/invoicing/job_statement.html` (and
  `tests/test_invoice_pdf.py`) are now orphaned — delete outright, or keep
  for a future statement surface? RM to decide.
