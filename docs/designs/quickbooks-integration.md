# QuickBooks Online Integration

QBO is Minibini's accounting system of record. Minibini pushes invoices and expense purchases into QBO; QBO calculates tax, owns the customer-facing payment experience, and is polled for payment status. Estimates are not pushed. Vendor invoices (bills) are entered, tracked, and paid **entirely in QBO** — the konbini Bill domain was retired 2026-07-23 (see materials-inventory-and-purchasing.md §13).

This doc owns the QBO push mechanics, OAuth lifecycle, sync log, and polling. Domain models on the Minibini side live with their owning docs:

- `Invoice`, `Expense`, `Reimbursement` — [invoicing-and-expenses.md](invoicing-and-expenses.md)
- `PurchaseOrder` — [materials-inventory-and-purchasing.md](materials-inventory-and-purchasing.md)
- `Estimate` (not pushed) — [estimates-and-prices.md](estimates-and-prices.md)

Developer setup (env file, redirect URI registration, dependencies, first-connect walkthrough) and the production cutover checklist (real QBO company instead of a sandbox) are in the Appendices at the end of this doc.

## Models

### `QBOConnection` — `apps/qbo/models.py`

Singleton per Minibini instance. Stores OAuth tokens and connection metadata.

| Field | Notes |
|---|---|
| `realm_id` | QBO company ID |
| `access_token` | Refreshed automatically by `QBOService.get_client` when expired |
| `refresh_token` | 100-day rolling lifetime |
| `access_token_expires_at` | One hour after issue |
| `refresh_token_expires_at` | 100 days after issue; reset on every refresh |
| `is_active` | Only one row may be active at a time; `qbo_callback` deactivates any existing rows in the same transaction. Inactive rows are kept (not deleted) so the historical record of which `realm_id` Minibini was connected to and when remains queryable — useful for diagnosing past pushes whose `qbo_id` belongs to a now-disconnected company. The dead tokens cost nothing. |
| `connected_at`, `last_sync_at` | Metadata |

Properties:

- `is_access_token_expired` — used by `get_client` to decide whether to refresh.
- `is_refresh_token_expiring_soon` — true if within 7 days of refresh-token expiry; surfaced to the settings UI as a warning.

`db_table = 'qbo_connection'`.

### `QBOSyncLog` — `apps/qbo/models.py`

Append-only audit trail. Every push attempt writes a row, success or failure.

| Field | Notes |
|---|---|
| `entity_type` | `'invoice'`, `'expense'`, `'reimbursement'`, `'customer'`, `'contact_customer'`. Historical rows with `'bill'` / `'bill_payment'` / `'vendor'` remain in the log (append-only) — those types stopped occurring with the 2026-07-23 bill retirement |
| `entity_id` | Minibini PK |
| `qbo_entity_type` | `'Invoice'`, `'Purchase'`, `'Customer'` (historical rows: `'Bill'`, `'BillPayment'`, `'Vendor'`) |
| `qbo_entity_id` | QBO ID on success; empty string on failure |
| `action` | `'create'`, `'update'`, `'delete'` |
| `status` | `'success'` or `'failed'` |
| `error_message` | Exception string on failure; blank otherwise |
| `triggered_by` | User FK (SET_NULL, nullable) — **who initiated this QBO call.** Auto-set by `log_sync` from the active request context (`current_request_user()`): the acting user for an API-triggered push/retry/void, `None` for a cron/poller sync. No threading — `log_sync` reads the same `HistoryContext` the `@history` decorator uses. Pass an explicit `triggered_by=` only to override. |
| `synced_at` | `auto_now_add` |

Default ordering is `-synced_at`. No retention policy — log grows forever.

`db_table = 'qbo_sync_log'`.

## OAuth lifecycle

| Step | Endpoint | Caller | Notes |
|---|---|---|---|
| Initiate | `GET /api/qbo/connect/` | Browser redirect from settings page | Generates state token, stores in session, redirects to Intuit |
| Callback | `GET /api/qbo/callback/` | Intuit redirects back here | Validates state token, exchanges code for tokens, deactivates any existing connection, creates new `QBOConnection`, redirects to `{SPA_BASE_URL}/#/settings` |
| Status | `GET /api/qbo/status/` | SPA on settings page mount | Returns connection state + `refresh_token_expiring_soon` |
| Disconnect | `POST /api/qbo/disconnect/` | SPA settings page | Sets `is_active=False` on the active connection |

`qbo_connect` and `qbo_callback` are plain Django views (not DRF) because they involve browser redirects, not XHR. Both require `core.can_manage_config`.

### Token refresh

`QBOService.get_client()` is the only sanctioned way to obtain a python-quickbooks client. It:

1. Looks up the active `QBOConnection`.
2. If `is_access_token_expired`, calls `AuthClient.refresh()`, then writes `access_token`, `refresh_token`, `access_token_expires_at` (now + 1h), and `refresh_token_expires_at` (now + 100 days) back to the connection.
3. Returns a `QuickBooks` client bound to that connection.

Because each refresh resets the 100-day refresh-token clock, any QBO API call within the 100-day window keeps the connection alive indefinitely. Idle longer than 100 days requires reconnecting via the OAuth flow.

## Configuration

Environment variables — see `minibini/settings.py`:

| Variable | Purpose | Dev default |
|---|---|---|
| `QBO_CLIENT_ID` | Intuit app client ID | (empty) |
| `QBO_CLIENT_SECRET` | Intuit app secret | (empty) |
| `QBO_REDIRECT_URI` | Must match what's registered in the Intuit developer dashboard | `http://localhost:8000/api/qbo/callback/` |
| `QBO_ENVIRONMENT` | `sandbox` or `production` | `sandbox` |
| `SPA_BASE_URL` | Where `qbo_callback` redirects after OAuth | `http://localhost:9000` (dev); leave empty for same-origin prod |

Setup details (`.env` file format, redirect URI registration in Intuit dashboard, dependencies, first-connect walkthrough) are in the Appendix at the end of this doc.

### `Configuration['qbo_payment_accounts']`

JSON list of payment accounts (Bank, Credit Card, Other Current Asset) used by the expense sync. Populated from the settings UI via `/api/qbo/payment-accounts/`. Each entry:

```json
{ "qbo_account_id": "35", "display_name": "Business Checking", "account_type": "Bank" }
```

Read via `QBOExpenseSyncService._load_payment_accounts()`; individual lookup via `_lookup_account(payment_account_id)` (raises `ValueError` if not configured). Used by the expense/reimbursement pushes only (the bill-payment push that also read it was retired 2026-07-23).

## Setup-time data import (snapshot + suggestion panels)

Spec: `docs/plans/qbo-setup-import-spec.md`. Code: `apps/qbo/import_services.py`,
endpoints in `apps/api/qbo_import/views.py`.

- **Snapshot**: `QBOSnapshotService.pull(client)` fetches sellable Items
  (Service/NonInventory/Inventory; Category rows excluded), income and
  expense/COGS accounts, Customers, Vendors, Terms — paginated
  (`start_position`/`max_results`) — into one JSON blob
  (`Configuration['qbo_import_snapshot']`, `fetched_at` inside).
- **Endpoints** (area ∈ categories/schemes/inventory/services/contacts/
  terms; permission per area: config/config/financials/financials/jobs/
  config):
  `POST /api/qbo/import/pull/` (refreshes the shared snapshot, clears ONLY
  the pulling area's dismissal, returns a diff summary),
  `POST /api/qbo/import/dismiss/`,
  `GET /api/qbo/import/suggestions/<area>/`,
  `POST /api/qbo/import/commit/{categories,schemes,catalog,contacts,terms}/`
  (one `catalog` commit endpoint serves both the inventory and services
  areas — rows carry `kind`; `commit/contacts` still accepts a bundled
  `terms` list for API-compat but the SPA commits terms via
  `commit/terms`).
- **Dismissal** (`Configuration['qbo_import_dismissed']`, `{area: true}`):
  sticky across pulls made elsewhere; total for the area (panel gone; the
  area's pull button remains); auto-set when a commit leaves the area's
  diff empty. The suggestions endpoint short-circuits on the flag before
  any snapshot parse.
- **Suggestions** (`QBOSuggestionService`): live snapshot-vs-DB diffs. Row
  states: `new` / `imported` (shown inert, no editable bindings) /
  `changed` → "update" action. **`changed` means QBO drifted since import**
  — the diff compares the snapshot against the import-time fingerprint
  (`Configuration['qbo_import_catalog_fingerprints']`, written at catalog
  commit), never against live konbini values, which legitimately diverge
  (own codes, own scheme rates). Existing objects with no fingerprint
  (pre-fingerprint imports) read as `imported`. Scheme rows are
  `imported` when their item is in `qbo_import_scheme_map` and the scheme
  still exists (ServiceItems only appear at the later catalog commit).
  Categories cluster items by `IncomeAccountRef` (+ itemless income
  accounts); item→category resolution runs item → income account → the
  committed kAC whose fallback Item shares that account.
- **Commits** (`QBOImportCommitService`): categories (atomic, unique-code
  guarded); schemes — **an upsert**: rows resolve through
  `qbo_import_scheme_map` (following the supersession chain); mapped rows
  update the existing scheme (in place while unreferenced, mirroring
  `update_rate_scheme`; supersede + repoint ServiceItems once referenced;
  no-op when unchanged) and only unmapped rows insert (`collapse_group`
  rows share one scheme; missing category and name collisions raise
  contract 400s, never 500s); catalog (inventory = field overwrites;
  **service price changes go through RateScheme supersession** and repoint
  the ServiceItem — but only when QBO's own price moved vs the
  fingerprint, so a deliberate konbini rate divergence survives QBO-side
  renames); terms (create/update PaymentTerms mirrors — own panel since
  2026-07-23); contacts (customers → vendors; a vendor whose name
  matches an existing Business adopts `qbo_vendor_id` onto it — one
  Business, both roles; customers resolve `term_qbo_id` against EXISTING
  PaymentTerms — unresolved refs are left unset, and the contacts
  suggestions carry `missing_term_refs` so the panel warns to import
  terms first). **Skip-and-report (2026-07-23):** QBO rows konbini can't
  hold — blank contact email, duplicate email (vs konbini or within the
  batch — QBO "locations" share emails), duplicate business name — are
  skipped, never 500/rollback; `counts[kind]['skipped']` carries
  `{'name', 'reason'}` and the panel renders "N contacts couldn't be
  imported:" with per-row reasons. Skipped rows stay importable after
  the user resolves the conflict. Blank QBO emails never overwrite a
  konbini email on update. A dedupe/merge flow for skipped rows is
  LATER.
- **SPA**: shared `SuggestionPanel.svelte` + per-kind wrappers embedded in
  Settings → Accounting (categories), Settings → pricing/RateSchemeManager
  (schemes), Catalog → Inventory tab (`InventoryImportPanel`), Catalog →
  Service items tab (`ServiceItemsImportPanel`), Contacts
  (customers/vendors), Settings → Business (`TermsImportPanel`, above
  the payment-terms manager); each surface keeps a permanently-visible
  `QboPullButton` with the shared last-pull timestamp (also in
  `GET /api/setup/status/`). Required bindings are enforced before the
  POST: blank category/scheme pulldowns on checked rows get a red
  `.missing` highlight, panels show amber dependency notices when their
  prerequisite is absent (schemes + inventory need ≥1 kAC; services need
  ≥1 scheme), and commit functions refuse with a row-naming error.
  Editable binding pulldowns render only on `new` rows.

## Gotcha: QBO's raw JSON field capitalization is inconsistent

When reading QBO's raw JSON directly (bypassing the SDK's object mapping —
e.g. `client.get(...)` as `_fetch_invoice_link` does), do not trust the
documented field casing. Observed live (sandbox, 2026-07-22): the payment
link returns as **`InvoiceLink`** (capital I) while Intuit's docs, community
answers, and the python-quickbooks SDK all say `invoiceLink`; most other
fields are PascalCase (`DocNumber`, `AllowOnlineACHPayment`), but not
reliably so. **If a field you're reading from a raw response comes back
`None`/missing while clearly present in the payload, check capitalization
first** — dump the full response (`manage.py probe_invoice_link` does this
for invoices) and read the actual key. Where casing has burned us, accept
both spellings (see `_fetch_invoice_link`).

## The `QBOService` mock boundary

`QBOService` — `apps/qbo/services.py` — is a thin wrapper around the python-quickbooks SDK and is the only sanctioned mock point for tests. Production code obtains its QBO client via `QBOService.get_client()` and logs sync attempts via `QBOService.log_sync(...)`.

Test code mocks at this layer rather than at the python-quickbooks SDK level. Mocking deeper (`quickbooks.objects.invoice.Invoice.save`, etc.) is fragile against SDK upgrades; mocking shallower (the requests library) leaks unrelated HTTP traffic.

## Shared sync scaffolding

The per-entity sync services (`QBOCustomerSyncService`, `QBOInvoiceSyncService`, `QBOExpenseSyncService`) are organized by QBO entity — each owns the *builder* for its QBO object, which genuinely differs (a `Customer`, an `Invoice`, a `Purchase`…). What they used to duplicate has been factored into four shared pieces:

- **`QBOSyncable`** (`apps/core/models.py`) — abstract model base carrying the sync-state fields `qbo_id`, `qbo_sync_status` (`pending` / `synced` / `sync_failed`), `qbo_sync_error`, **`qbo_pending_op`** (`''` / `create` / `update` / `delete` — the operation a `sync_failed` record still owes QBO), plus `mark_synced(qbo_id)` (clears the op) / `mark_failed(error, op)` (records the op). Adopted by `Expense` and `Reimbursement` (formerly also `BillPayment`, retired 2026-07-23). (`Expense.status` is business-only — `submitted`/`reimbursed`/`rejected`; its QBO sync state lives in the inherited `qbo_sync_status`. `Reimbursement`'s sole status *is* its `qbo_sync_status`.)
- **`QBOSyncService`** (`apps/qbo/services.py`) — the push orchestrators, one per verb: `run_create(record, push_callable)`, `run_update(record, update_callable)`, `run_delete(record, delete_callable)`. Each runs its callable and on failure calls `record.mark_failed(e, record.OP_<verb>)` — so a `sync_failed` row is **self-describing** about which operation to retry. `run_create`/`run_update` **swallow** (a QBO failure never blocks the local write that already committed); `run_delete` **re-raises** so a refused delete aborts the local removal and retains the row. (`run_update` was formerly named `run_resync` — "resync" now means *retry a failure*, not "an edit happened, push the update.")
- **`QBOService.save_and_log(qbo_obj, client, *, entity_type, qbo_entity_type, entity_id, action='create')`** — saves a QBO SDK object, writes the success/failure `QBOSyncLog` row, returns `str(qbo_obj.Id)`, re-raises on error. Every create/update push method calls it, so the save-and-log boilerplate lives in one place. (The `void_*` deletes and the invoice send — whose log lands after `_mark_as_sent` — keep their own shape.)
- **`QBOPaymentAccountService`** (`apps/qbo/services.py`) — owns the `Configuration['qbo_payment_accounts']` lookup (`load_accounts()` / `lookup(id)`), used by the expense/reimbursement `Purchase` push.

A typical push method is now: short-circuit on existing id → get client (raise if none) → build the QBO object → `save_and_log(...)` → persist the id on the record; wrapped by `run_create`/`run_update` where the record is a `QBOSyncable`.

### Audit & attribution

Two separate audit trails, with a clean seam between them — and **attribution flows from the request context, never threaded**:

- **QBO-mechanics audit → `QBOSyncLog`** (the swap-the-backend seam): every push/update/void writes a row; `triggered_by` records who initiated it (auto from the request context; `None` for cron). QBO-coupled facts (qbo ids, sync status, error text) live only here.
- **Domain audit → the history partitions** (`docs/designs/architecture-and-conventions.md`): `Expense` is `@history`-decorated into a new **`ExpensesHistory`** partition (`object_type='expense'`/`'reimbursement'`), with `exclude=[…, qbo_id, qbo_sync_status, qbo_sync_error, qbo_pending_op]` so QBO sync churn never enters the domain timeline. The **adjunct** records its lifecycle imperatively on its **primary's** timeline via `record_action(object_type, object_id, action)`: `Reimbursement` → each member **Expense** (`'expense'`: reimbursed-in-batch / unwound). (`BillPayment` → Bill was the other adjunct until the 2026-07-23 bill retirement.) `record_action` and `log_sync` both default their author to `current_request_user()`, so no service threads an actor.

### Retry & sync failures

Each domain service exposes the same small sync-dispatch surface so a failure can be retried as the *operation it actually owes*:

- `_push_create(record)` / `_push_update(record)` — the create and update push wrappers (the update one carries any domain routing, e.g. a personal `Expense`'s edit resyncs its reimbursement **batch**, not the expense).
- `retry(record, …)` — guards `qbo_sync_status == sync_failed`, then **dispatches on `qbo_pending_op`**: `delete` → re-run the full delete (re-void + local removal); `update` → `_push_update`; `create`/blank → `_push_create`. This fixes the old bug where a blind retry always create-pushed — which **short-circuited on `qbo_id` and silently marked a failed *update* as synced without re-applying the edit**, and abandoned a failed *delete*.
- `ExpenseService.retry`, `ReimbursementService.retry` (each backed by a per-entity `POST …/retry-sync/` endpoint).

**Cross-entity failures view.** `QBOSyncFailureService.list_failures()` aggregates every `sync_failed` company `Expense` (personal expenses never carry their own failure — their batch does) and `Reimbursement` into one list (`entity_type`, `id`, `label`, `amount`, `qbo_pending_op`, `qbo_sync_error`, `retry_url`). Exposed at:

| Method | Path | Permission | Purpose |
|---|---|---|---|
| `GET` | `/api/qbo/sync-failures/` | `can_manage_financials` | List all QBO sync failures across the money pushes |
| `POST` | `/api/qbo/sync-failures/retry-all/` | `can_manage_financials` | Retry each (isolated per-record); returns `{retried, still_failing}` |

The SPA surfaces this as `QBOSyncFailures.svelte` (per-row Retry + Retry all) on the Settings page; the failures view covers **only** the two `QBOSyncable` money pushes (Customers/Invoices use ad-hoc sync state and are out of scope; the `BillPayment` slice was retired 2026-07-23).

## Customer sync — `QBOCustomerSyncService`

Customers are pushed lazily. `QBOInvoiceSyncService.push_invoice` resolves the QBO customer ID from `invoice.job.contact.business` (preferred) or `invoice.job.contact` (individual customer), and pushes the missing record if needed.

Two push entry points:

- `push_customer(business)` — pushes a `Business`, stores `qbo_customer_id` on it.
- `push_contact_as_customer(contact)` — pushes an individual `Contact` with no business, stores `qbo_customer_id` on the contact.

Both are no-ops if the target already has a `qbo_customer_id`.

Both **adopt on duplicate name** (2026-07-23): when the create fails with
QBO's 6240 Duplicate Name error, the push queries the existing Customer by
`DisplayName` and adopts its Id — same pattern and helpers as the Item mint
(`_is_duplicate_name_error` / `_adopt_id_by_name`, shared module-level in
`apps/qbo/services.py`). The failed create attempt keeps its `QBOSyncLog`
row (accurate history); the adopt then proceeds. If the name query finds
nothing (e.g. the collision is with an inactive record), the original error
re-raises. Accepted trade-off: a same-named-but-genuinely-different customer
binds silently. (Vendors never gained the adopt path — the vendor push was
retired with bills, 2026-07-23.)

### DisplayName collision logic — `QBODisplayNameService`

QBO requires unique `DisplayName` per entity type. The same Minibini `Business` may be both a customer (the company issues them invoices) and a vendor (the company also buys from them). Rules:

- First push for a business uses the plain `business_name`.
- If the business already has the *other* role's QBO ID (e.g. pushing as customer and `qbo_vendor_id` is set), the display name gets a ` (Customer)` or ` (Vendor)` suffix.
- `QBO_DISPLAY_NAME_MAX = 500`; long names are truncated before the suffix is appended.

The current logic only inspects Minibini's own QBO IDs. A pre-existing QBO customer named "Acme Inc." created outside Minibini is handled by the adopt-on-duplicate path above.

### What gets pushed

| Field | Source |
|---|---|
| `CompanyName` (business) | `business.business_name` |
| `DisplayName` | per the rules above |
| `GivenName` / `FamilyName` (contact) | `contact.first_name`, `contact.last_name` |
| `PrimaryPhone` | `business.business_phone` or `contact.phone()` |
| `PrimaryEmailAddr` | `default_contact.email` (business) or `contact.email` |

Billing address, shipping address, payment terms, tax exemption, and notes are not pushed.

## Vendor sync — retired 2026-07-23

`QBOVendorSyncService` (`push_vendor`) was deleted with the bill retirement — its only caller was the bill push. `Business.qbo_vendor_id` is **kept**: `QBODisplayNameService` still reads it for the suffix rule, and a future setup-time QBO pull may repopulate it. `QBOSyncLog` rows with `entity_type='vendor'` remain as history.

## Invoice push — `InvoiceEmailService.send_invoice`

The invoice QBO push is **fused into the invoice's Send action** — there is no separate `send-to-qbo` endpoint. Entry point: `POST /api/invoices/{id}/send` (the `send` action on `InvoiceViewSet`, `apps/api/invoicing/views.py`). Requires `can_manage_financials`. Body:

```json
{ "to": "customer@example.com", "subject": "...", "body": "...", "cc": "...", "bcc": "..." }
```

The action delegates to `InvoiceEmailService.send_invoice` (`apps/invoicing/services.py`), which performs the QBO push (only when `invoice.qbo_id` is unset) and then emails the customer — push and send are one operation, not two buttons. It uses the `QBOInvoiceSyncService` *helpers* (`_build_qbo_invoice`, `_mark_as_sent`, `_download_qbo_pdf`); there is no `QBOInvoiceSyncService.push_invoice` method.

Service flow (`InvoiceEmailService.send_invoice`, `apps/invoicing/services.py`):

1. **Gate** — `_assert_all_lines_categorized` raises before any external call if any line lacks an accounting category.
2. **Short-circuit** — if `invoice.qbo_id` is set, skip the push (retry path).
3. **Resolve QBO customer** — push `business` (or `contact`) as customer if not yet synced.
4. **Build QBO Invoice, per-line** — `_build_qbo_invoice(invoice, qbo_customer_id, client)`. One `SalesItemLine` per `InvoiceLineItem`, in `line_number` order — the QBO invoice mirrors the konbini invoice exactly (no more per-category bundling; `InvoiceGroupingService` was deleted 2026-07-21). Per line: `Amount` = `total_amount`, `Description` = the line's text **verbatim** (wizard edits ride along), `ItemRef` from `_resolve_item_ref` (below), `TaxCodeRef` = `'TAX'`/`'NON'` straight from the line's `accounting_category.taxable` flag (the per-line `taxable_override` phantom was removed along with `TaxCalculationService`). Invoice-level: `CustomerMemo` = `"Job {job_number} — {job name}"`, `BillEmail` from the job contact's email, and `AllowOnlineCreditCardPayment` / `AllowOnlineACHPayment` both true (the hosted invoice carries the Pay button when QBO Payments is active).
5. **Save** — `qbo_invoice.save(qb=client)`. **Immediately persist `qbo_id` AND `invoice_number` (from QBO's `DocNumber`)** on the Minibini invoice — QBO owns invoice numbering (see invoicing-and-expenses.md). A retry send whose invoice predates the writeback backfills `DocNumber` via `Invoice.get`.
6. **Fetch the payment link** — `_fetch_invoice_link(client, qbo_id)` reads the invoice back with `include=invoiceLink` (built directly on the client — the installed python-quickbooks `get()` can't pass query params) and substitutes the URL into the email subject/body wherever the `{payment_link}` placeholder appears.
7. **Mark as sent** — `_mark_as_sent` re-fetches the invoice, sets `EmailStatus = 'EmailSent'`, and re-saves. This prevents QBO from showing the invoice as "needs to be sent" in its own UI, and suppresses QBO's own email.
8. **Download QBO PDF** — `_download_qbo_pdf` retrieves QBO's rendered invoice PDF: the **only** auto-attachment (the konbini job-statement PDF was dropped 2026-07-22 and its generator/template deleted 2026-07-23).
9. **Send email via Minibini** — `OutboundEmailService.send_tracked` with the QBO PDF attached, Configuration-driven subject/body templates, To/CC/BCC from the send dialog, and a job-linked `EmailRecord`.
10. **Log success** to `QBOSyncLog`.

On any exception, `QBOSyncLog` records `status='failed'` with the error message, and the exception re-raises. There is no compensating action — if step 7 succeeds but step 9 fails, the invoice exists in QBO with `qbo_id` set on Minibini but is in an inconsistent "marked sent, not emailed" state. Manual cleanup is required.

### Defensive null-AC guards (Phase 3, 2026-08)

Step 1's `_assert_all_lines_categorized` gate (`invoicing-and-expenses.md`
§"Fallback accounting category stamping") is the primary block — it fires
before any external call, and given invoice-line authoring now stamps the
configured fallback onto every atom-derived null-AC line, the gate is only
realistically reachable via an uncorrected manual hand line. QBO push
itself carries a second, independent line of defense in case that primary
gate is ever bypassed or refactored around:

- `QBOInvoiceSyncService._require_line_category(line_item)` (shared static
  helper) raises `ValidationError` naming the line number, description, and
  the `fallback_accounting_category` Configuration key when
  `line_item.accounting_category_id` is `None`. Wired at the **top of
  `_build_qbo_invoice`'s per-line loop** (fails fast, before
  `_resolve_item_ref` or any QBO API call — no wasted work, no
  side-effecting lazy Item mint before the failure), and again inside
  `_resolve_item_ref`'s fallback branch (self-contained coverage for
  direct/test callers that invoke it independently of the per-line loop).
- `QBOItemMintService.ensure_item`'s two category reads
  (`InventoryItem.accounting_category`, `ServiceItem.effective_accounting_category`
  → `RateScheme.accounting_category`) are **not guarded** — both source
  FKs are non-nullable at the model level, so a null category is
  unreachable there regardless of the invoice-line's own AC state; the
  existing `if not category or not category.qbo_item_id: return ''` on
  the line right after already covers the (only realistically reachable)
  "category has no `qbo_item_id` mapped" case.

Do not confuse this Configuration key with "The category's generic
fallback Item" below (`AccountingCategory.qbo_item_id`) — that's a
per-category QBO **Item** mapping used when a line has no catalog entity
of its own; `fallback_accounting_category` is a Minibini-side
**AccountingCategory** substituted onto a line that would otherwise have
no category at all. The two "fallback" concepts are unrelated and can
both apply to the same line (a hand line with no catalog entity *and* a
null AC gets the AC fallback stamped at authoring, then resolves its
ItemRef via the category's own Item mapping at push time).

### ItemRef resolution — `QBOInvoiceSyncService._resolve_item_ref`

Each pushed line's `ItemRef` resolves in order:

1. **The line's catalog entity's mirrored QBO Item** — `_catalog_entity_for_line` finds the single `InventoryItem` or `ServiceItem` the line sells: the line's direct `inventory_item` FK, else its source atoms (all task sources sharing one `Task.service_item`, or all material sources sharing one `Material.inventory_item`). Adjustment lines, expense sources, provisional materials, mixed bundles, and hand lines have no catalog identity → fall through.
2. **The category's generic fallback Item** — `AccountingCategory.qbo_item_id` (the pre-existing per-category mapping, now demoted to fallback).
3. **No ItemRef** — QBO applies its default item.

### Lazy Item minting — `QBOItemMintService.ensure_item(entity, client)`

When step 1 finds a catalog entity with no `qbo_id`, the QBO Item is created mid-push: `InventoryItem` → Type `NonInventory` (never QBO's `Inventory` type — stock stays konbini-side), Name = `code`; `ServiceItem` → Type `Service`, Name = `template_name`. `IncomeAccountRef` is **copied from the category's generic fallback Item** fetched live from QBO — the bookkeeper configures income accounts exactly once, in QBO, on the per-category Items; konbini never stores income accounts. On QBO's duplicate-name error (`6240`), the existing Item is adopted by name (also how pre-existing QBO catalogs converge). If the entity's category has no `qbo_item_id` mapped, nothing is minted and the resolution falls through. The minted/adopted id persists on `entity.qbo_id` (plain CharField — not `QBOSyncable`; a failed mint fails the invoice push, whose retry path covers it). Catalog renames do NOT propagate to QBO Items (LATER).

## Bill push — retired 2026-07-23

`QBOBillSyncService` (bill push, bill-payment push/update/void) was deleted with the bill retirement — vendor invoices and their payments are entered directly in QBO, so there is nothing to push. The `/api/bills/{id}/send-to-qbo/` and bill-payment endpoints are gone. `Bill`/`BillLineItem`/`BillPayment` survive only as schema-only stubs (materials-inventory-and-purchasing.md §13); `QBOSyncLog` rows with `entity_type` `'bill'` / `'bill_payment'` remain as history.

## Expense push — `QBOExpenseSyncService`

The Minibini-side workflow (entering expenses, batching reimbursements, voiding) is described in `invoicing-and-expenses.md`. This section covers the QBO mechanics.

### Push targets

| Minibini entity | QBO entity | Trigger |
|---|---|---|
| `Expense` (company-paid) | `Purchase` | `push_expense(expense)` on save |
| `Reimbursement` batch (personal expenses) | `Purchase` with one line per included `Expense` | `push_reimbursement(batch)` when batch is finalized |

Both produce QBO `Purchase` records — the difference is whether the line items come from a single expense or a batch.

### Payment account resolution

Every `Purchase` needs an `AccountRef` (which Minibini bank/CC/cash account it was paid from). The mapping comes from `Configuration['qbo_payment_accounts']`. The user picks `payment_account_id` on the expense or batch; `_lookup_account` resolves that ID to the QBO account dict, and `_derive_payment_type` decides the QBO `PaymentType`:

| Minibini `account_type` | `reference_number` set? | QBO `PaymentType` |
|---|---|---|
| `Credit Card` | (any) | `CreditCard` |
| `Bank` | yes | `Check` |
| `Bank` | no | (unset — defaults to Cash in QBO) |
| `Other Current Asset` | (any) | (unset) |

`reference_number` also becomes the QBO `DocNumber` when set.

### Line items

`_build_expense_line(expense)` is shared between single-expense pushes and reimbursement-batch pushes. It produces one `AccountBasedExpenseLine` with:

- `Amount = float(expense.amount)`
- `Description = expense.description or f"Expense #{expense.pk}"`
- `AccountRef = expense.accounting_category.qbo_expense_account_id` (if both are set)

Personal reimbursement batches do **not** set `EntityRef` on the Purchase. That would point to a QBO Employee record, and Employee-as-Vendor sync is not yet implemented (see Unfinished work, and the matching pointer in `invoicing-and-expenses.md`).

### Update and void

| Method | Behavior |
|---|---|
| `push_expense` / `push_reimbursement` | Create-only; short-circuits if `qbo_id` already set |
| `update_expense` / `update_reimbursement` | Re-fetch the QBO `Purchase`, rebuild fields, save. Raises if `qbo_id` not set |
| `void_expense` / `void_reimbursement` | Delete the QBO `Purchase`. **Logs but does not raise** on failure — the caller is mid-delete and the local row must still be removed |

## Inventory write-offs are not pushed (by design)

`InventoryService.write_off` zeroes a lot's on-hand and books the remainder to `qty_wasted`, recording an `InventoryHistory` entry — it pushes **nothing** to QBO, deliberately. Inventory cost is *expensed at purchase time*: vendor bills are entered directly in QBO, and company-paid Expenses push as a QBO `Purchase` with `AccountBasedExpenseLine`s posting to an **expense / COGS account** (`AccountingCategory.qbo_expense_account_id`), never to a capitalized inventory asset. So the cost already hit QBO's P&L when the bill/expense was recorded; a write-off is a pure quantity event in Minibini with no QBO consequence, and pushing one would **double-count** the cost. This only changes if QBO is ever switched to true inventory-asset tracking (Items with quantities, COGS on sale) — then write-offs would need to relieve the asset; that is a much larger change and is not planned.

## Accounting categories — `QBOAccountsService`

Two endpoints feed the settings UI mapping page:

| Method | Pulls | Used for |
|---|---|---|
| `get_income_items()` | QBO `Item` records with `Type` in `('Service', 'NonInventory')`, `Active=True` | Mapping `AccountingCategory.qbo_item_id` — invoice lines reference QBO Items, not accounts |
| `get_expense_accounts()` | QBO `Account` records with `AccountType` in `('Expense', 'Cost of Goods Sold')`, `Active=True` (dedupe by ID) | Mapping `AccountingCategory.qbo_expense_account_id` — purchase lines reference accounts directly |

Both fields live on `apps.core.models.AccountingCategory`. Both are `CharField(max_length=50, blank=True, default='')`. A category used only for invoicing needs only `qbo_item_id`; one used only for expenses needs only `qbo_expense_account_id`; categories that flow both directions need both.

Both methods are live fetches against QBO — there is no caching layer and no "refresh accounts" endpoint, just `GET /api/qbo/accounts/`.

## Payment polling

Polling is the *only* mechanism for learning about payments — there are no webhooks.

### Invoice polling — `QBOPaymentPollingService.poll_all()`

Walks every `Invoice` where `qbo_id` is set and the Minibini status is still `open` or `partly-paid`. For each, fetches the QBO invoice and derives, from QBO's `Balance` / `TotalAmt`, both a **raw cache** value and a target Minibini status:

| Condition | `qbo_payment_status` (cache) | `Invoice.status` |
|---|---|---|
| `Balance == 0` | `'Paid'` | → `paid` |
| `0 < amount_paid` | `'Partial'` | → `partly-paid` |
| `amount_paid == 0` | `'Unpaid'` | (unchanged) |

`qbo_payment_status` and `qbo_amount_paid` (`= TotalAmt - Balance`) remain the raw cache of what QBO last reported. The service now also **drives `Invoice.status`**: on a status change it does a full `invoice.save()` (which stamps `closed_date` and, on `paid`, fires `_maybe_complete_job` to auto-complete the job once all its invoices are resolved) and writes a `system`-attributed `action` HistoryEntry. If there is no active QBO connection, `poll_all` returns an `error` key and the command records a `skipped` run rather than failing.

**First-run healing:** an invoice left at `open` with a stale cached `qbo_payment_status='Paid'` (from the old cache-only polling) will transition to `paid` — and complete its job — on the first run under the status-driving code. See `invoicing-and-expenses.md` for the full status-machine view.

### Unified inbound orchestrator — `QBOInboundPollingService`

`QBOInboundPollingService.poll_all()` is the single entry point for all QBO → Minibini polling (future: Job-P&L actuals, CDC):

```python
{
    'invoices': QBOPaymentPollingService.poll_all(),
}
```

(The bill-clearance sub-poller, `QBOBillPaymentPollingService`, was deleted with the 2026-07-23 bill retirement; the command's stats no longer report `bills_*` keys.)

### Management command

`python manage.py poll_qbo_payments` (`apps/invoicing/management/commands/poll_qbo_payments.py`) drives `QBOInboundPollingService.poll_all()`. It is a `ScheduledProcessCommand` (`architecture-and-conventions.md` §9), so each run records a `ScheduledProcessRun` row (`ok` / `failed` / `skipped`). The scheduler **is** wired: the docker-compose `cron` service runs it every 15 minutes.

**Operational note — credentials and timezone.** The cron service runs in its own container; the committed `docker-compose.yml` mirrors only the `DATABASE_*` env onto it. QBO OAuth credentials and the email/IMAP credentials are injected at deploy time and **must reach the cron container too** — otherwise `poll_qbo_payments` records `skipped` runs (no QBO connection) and the email-related jobs `failed` runs. The cron schedules are evaluated in the **container timezone (UTC by default)**; set `TZ` on the cron service to schedule in local time.

## UI

Settings page — `frontend/src/routes/SettingsPage.svelte`:

- `QBOConnectionCard.svelte` — calls `/api/qbo/status/`, shows realm ID, connected date, last sync, refresh-token-expiring-soon warning. "Connect to QuickBooks" / "Reconnect" link to `/api/qbo/connect/`. "Disconnect" button.
- Category mapping panel (lives elsewhere on the settings page) — uses `/api/qbo/accounts/` to populate `qbo_item_id` and `qbo_expense_account_id` dropdowns for each `AccountingCategory`.
- Payment-account selection — uses `/api/qbo/payment-accounts/` to populate the `Configuration['qbo_payment_accounts']` list.

Invoice detail — `frontend/src/routes/invoices/InvoiceDetailPage.svelte`:

- A "Send Invoice" link (relabelled "Resend Invoice" once `invoice.qbo_id` is set) navigates to the invoice send page (`#/invoices/{id}/send`). That page posts to `POST /api/invoices/{id}/send`, which performs the QBO push (first send only) and the customer email together. There is no separate "Send to QuickBooks" button or `SendToQBODialog`. Once `qbo_id` is set, the detail page also shows read-only QBO ID / payment-status / amount-paid rows.

The send flow on the Minibini side is documented in `invoicing-and-expenses.md`.

## API endpoints

All endpoints are mounted under `/api/qbo/` via `apps/qbo/urls.py`.

| Method | Path | Permission | Purpose |
|---|---|---|---|
| `GET` | `/api/qbo/connect/` | `can_manage_config` | Browser redirect to Intuit OAuth |
| `GET` | `/api/qbo/callback/` | `can_manage_config` | OAuth callback; redirects to SPA settings page |
| `GET` | `/api/qbo/status/` | `can_manage_config` | Connection state for settings card |
| `POST` | `/api/qbo/disconnect/` | `can_manage_config` | Deactivate active connection |
| `GET` | `/api/qbo/accounts/` | `can_manage_config` | Live fetch of QBO Items + expense accounts for category mapping |
| `GET` | `/api/qbo/payment-accounts/` | `can_manage_config` | Live fetch of Bank / Credit Card / Other Current Asset accounts for payment-account config |

Push endpoints live on the owning resource's viewset:

| Method | Path | Permission | Service |
|---|---|---|---|
| `POST` | `/api/invoices/{id}/send` | `can_manage_financials` | `InvoiceEmailService.send_invoice` — QBO push fused into the send-email action; **no** separate invoice send-to-qbo endpoint |

Expense and reimbursement pushes are triggered server-side from their respective save / finalize flows in `apps/expenses` and `apps/reimbursements` — not via dedicated REST actions.

There is no `GET /api/qbo/sync-log/` endpoint yet; `QBOSyncLog` is currently inspected via the Django admin.

## Unfinished work

- **Sync log UI.** No `/api/qbo/sync-log/` endpoint or settings panel showing recent push attempts; failures are visible only via the Django admin.
- **Employee-as-Vendor sync for personal reimbursements** — tracked in `invoicing-and-expenses.md`.
- **Job P&L view.** Phase 5 of the original plan — pull QBO-reported actuals back into Minibini for a per-job profit & loss view. Tracked in `invoicing-and-expenses.md`.
- **Estimate push.** Not currently supported. Minibini-direct estimate send is also unimplemented; see `estimates-and-prices.md`.
- **Webhooks.** Polling was chosen for simplicity. QBO does support a webhook channel for invoice payment notifications; revisit if polling latency or load becomes a problem.
- **Chart-of-accounts drift detection.** If a mapped QBO Item or expense Account is renamed or deleted in QBO, Minibini won't notice until the next push fails. No proactive drift check.
- **Richer customer field push.** Only display name, phone, and email currently push. Billing/shipping address, payment terms, tax exemption, notes do not.
- **Cross-source DisplayName collisions.** `QBODisplayNameService` only checks Minibini's own QBO IDs. A name collision with a customer/vendor created outside Minibini surfaces as a save failure from QBO, not a graceful suffix.
- **Custom invoice email templates.** Subject and body for the invoice send-email step are hard-coded strings; there's no per-user or per-customer template system.
- **Partial-failure handling.** If any step after `qbo_id` is persisted fails, Minibini has a `qbo_id` but the QBO record may be in an inconsistent state (e.g. marked-sent but no email actually sent). There is no resume / retry tool; recovery is manual.
- **"Resend to QBO" action.** Once `qbo_id` is set, the send-to-qbo path short-circuits. If the original push partially failed, there's no UI for retrying just the failed steps.
- **"View in QBO" deep link.** No button in the invoice detail UI to jump to the QBO invoice URL.
- **Connection health beyond `is_refresh_token_expiring_soon`.** No proactive token refresh well before the 100-day window closes, no email alert, no dashboard pulse.
- **CDC reverse-sync for QBO-first Purchases.** Research notes preserved as an appendix in `invoicing-and-expenses.md`.

---

## Appendix: Production cutover

What changes when a deployment points at a real QBO company instead of a sandbox. **No code changes are required** — `QBO_ENVIRONMENT` flows all the way through: `intuitlib`'s `AuthClient` picks its OAuth endpoints from it, and python-quickbooks infers its API base URL from the auth client's environment (sandbox vs production). Everything below is portal work, deployment config, and in-app reconfiguration.

### 1. Intuit developer portal (one-time)

- An Intuit app has two separate credential sets: **Development keys** (sandbox-only, what dev uses today) and **Production keys**, which don't exist until the app completes Intuit's "go to production" checklist — app details, EULA and privacy-policy URLs, and a short questionnaire for the Accounting scope. Straightforward for a private internal app, but it is a gate; do it ahead of the deployment date.
- Register the production redirect URI (`https://<prod-host>/api/qbo/callback/`) under the **production** keys tab. Intuit **requires HTTPS** for production redirect URIs; plain http is only tolerated for localhost dev.

### 2. Deployment environment values

The production instance's env:

| Variable | Production value |
|---|---|
| `QBO_CLIENT_ID` / `QBO_CLIENT_SECRET` | The **production** keyset — different values from the dev keys |
| `QBO_REDIRECT_URI` | `https://<prod-host>/api/qbo/callback/` (must exactly match the portal registration) |
| `QBO_ENVIRONMENT` | `production` |
| `SPA_BASE_URL` | empty (same-origin) |

The keyset and environment must pair correctly: production keys only work with `QBO_ENVIRONMENT=production`, dev keys only with `sandbox`.

Per the operational note in [Management command](#management-command): these vars must reach the **cron container** too, not just the web container — otherwise `poll_qbo_payments` silently records `skipped` runs.

Staging/test instances need none of this — they keep the dev keyset with `QBO_ENVIRONMENT=sandbox`. One Intuit app serves every environment: the sandbox *company* is chosen during the OAuth connect (stored as `realm_id` on `QBOConnection`), not by the credentials, and one app can register multiple redirect URIs. Separate sandbox companies per instance therefore need no per-instance credential changes.

### 3. In-app reconfiguration after connecting

Every QBO ID stored in Minibini is scoped to one specific QBO company. After connecting the production instance to the real company (settings page → Connect to QuickBooks), redo in the production instance's settings UI:

- **Category mappings** — `AccountingCategory.qbo_item_id` and `qbo_expense_account_id`. The real company's items and chart of accounts have completely different IDs than any sandbox.
- **Payment accounts** — the `Configuration['qbo_payment_accounts']` list.

**Start production from a fresh database.** A database that has already pushed to a sandbox must never be pointed at production: every stored `qbo_id`, `qbo_customer_id`, and `qbo_vendor_id` would be a stale sandbox ID, and the push short-circuits ("already has `qbo_id` → skip") would silently skip pushes that never happened in the real company.

### Repointing a dataset at a different company — `purge_qbo_data`

For the non-production version of the same problem — prepping a sample dataset for a staging instance that connects to a *different sandbox company* — `python manage.py purge_qbo_data <input.json> <output.json>` reads a `dumpdata` JSON dump and writes a copy with every QBO-company-scoped value stripped. It operates on the file only — **it never touches a database** (output path may equal input for in-place):

- `core.accountingcategory`: `qbo_item_id` / `qbo_expense_account_id` → `''`
- `core.configuration` rows with key `qbo_payment_accounts` → dropped (other keys untouched)
- `invoicing.invoice`: `qbo_id` → null, plus its poll caches `qbo_payment_status` → `''` and `qbo_amount_paid` → null
- `contacts.business` `qbo_customer_id` / `qbo_vendor_id` and `contacts.contact` `qbo_customer_id` → null
- The `QBOSyncable` pair (`expenses.expense`, `expenses.reimbursement`): `qbo_id` → `''`, `qbo_sync_status` → `pending`, `qbo_sync_error` / `qbo_pending_op` cleared
- All `qbo.qboconnection` and `qbo.qbosynclog` records → dropped

(The retired bill models are no longer reset — 2026-07-23; legacy `purchasing.bill` / `purchasing.billpayment` rows in a dump pass through untouched.)

It prints per-model scrubbed/dropped counts. Only fields actually present in a record are overwritten, so a dump from an older schema stays loadable. The flip side: models with no data in the dump (e.g. QBO features unfinished at dump time) exercise nothing — **when new QBO-coupled models or fields land, extend the command's tables and recheck against a fresh dump.** **What it does not touch:** domain state derived from the old company stays as-is — invoices remain `paid`/`partly-paid` with no QBO record behind them (accepted follow-on effect), and `payment_account_id` values on expenses/reimbursements/payments are kept even though they now dangle (the which-account information stays readable). After loading the purged dump, the new instance must connect to its new sandbox account and regenerate the category mappings and payment-account list per §3 above.  The existing domain state will remain inconsistent with the new sandbox, acceptable in a staging environment.

## Appendix: Developer setup

QBO integration requires OAuth credentials and a `.env` file. One-time setup per developer.

### Connect to QBO

1. **Get credentials.** Ask the project owner for the Intuit developer account, or create your own at https://developer.intuit.com/. You need a sandbox app with a client ID and client secret.

2. **Create `.env`** in the project root (gitignored):

   ```
   QBO_CLIENT_ID=your_client_id_here
   QBO_CLIENT_SECRET=your_client_secret_here
   QBO_REDIRECT_URI=http://localhost:8000/api/qbo/callback/
   QBO_ENVIRONMENT=sandbox
   SPA_BASE_URL=http://localhost:9000
   ```

   Variable meanings are documented in the Configuration section above.

3. **Register the redirect URI** — in the Intuit developer dashboard, open your app's **Keys & credentials** and add `http://localhost:8000/api/qbo/callback/` as a Redirect URI. Must match exactly.

4. **Install dependencies** — `pip install -r requirements.txt` (adds `python-quickbooks` and `python-dotenv`).

5. **Run migrations** — `python manage.py migrate` (creates `qbo_connection` and `qbo_sync_log` tables, and adds QBO fields to `businesses` and `accounting_categories`).

6. **Connect** — start both servers with `./dev.sh`, go to `http://localhost:9000/#/settings`, click "Connect to QuickBooks". Log in with the Intuit sandbox credentials and authorize.

The user connecting must have `can_manage_config`.

### Accessing the sandbox company

The sandbox company login is not directly linked from the main developer-portal app page. To reach it:

1. In the developer portal (developer.intuit.com), open your app and click the **API Explorer** tab.
2. Near the top of the API Explorer there's a pulldown menu (showing a company identifier). Open it.
3. At the bottom of that pulldown, click **Manage Sandbox**.
4. That takes you to `developer.intuit.com/sandbox-companies`, which lists all your sandbox companies.
5. Click the company you want. The portal runs through several automatic redirects and logs you into that company's QBO environment.

The direct URL `qbo.sandbox.intuit.com` does not work reliably — use the Manage Sandbox route.
