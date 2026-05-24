# QuickBooks Online Integration

QBO is Minibini's accounting system of record. Minibini pushes invoices, bills, and expense purchases into QBO; QBO calculates tax, owns the customer-facing payment experience, and is polled for payment status. Estimates are not pushed.

This doc owns the QBO push mechanics, OAuth lifecycle, sync log, and polling. Domain models on the Minibini side live with their owning docs:

- `Invoice`, `Expense`, `Reimbursement` — [invoicing-and-expenses.md](invoicing-and-expenses.md)
- `Bill`, `PurchaseOrder` — [materials-inventory-and-purchasing.md](materials-inventory-and-purchasing.md)
- `Estimate` (not pushed) — [estimates-and-prices.md](estimates-and-prices.md)

Developer setup (env file, redirect URI registration, dependencies, first-connect walkthrough) is in the Appendix at the end of this doc.

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
| `entity_type` | `'invoice'`, `'bill'`, `'expense'`, `'reimbursement'`, `'customer'`, `'vendor'`, `'contact_customer'` |
| `entity_id` | Minibini PK |
| `qbo_entity_type` | `'Invoice'`, `'Bill'`, `'Purchase'`, `'Customer'`, `'Vendor'` |
| `qbo_entity_id` | QBO ID on success; empty string on failure |
| `action` | `'create'`, `'update'`, `'delete'` |
| `status` | `'success'` or `'failed'` |
| `error_message` | Exception string on failure; blank otherwise |
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

Read via `QBOExpenseSyncService._load_payment_accounts()`; individual lookup via `_lookup_account(payment_account_id)` (raises `ValueError` if not configured).

## The `QBOService` mock boundary

`QBOService` — `apps/qbo/services.py` — is a thin wrapper around the python-quickbooks SDK and is the only sanctioned mock point for tests. Production code obtains its QBO client via `QBOService.get_client()` and logs sync attempts via `QBOService.log_sync(...)`.

Test code mocks at this layer rather than at the python-quickbooks SDK level. Mocking deeper (`quickbooks.objects.invoice.Invoice.save`, etc.) is fragile against SDK upgrades; mocking shallower (the requests library) leaks unrelated HTTP traffic.

## Customer sync — `QBOCustomerSyncService`

Customers are pushed lazily. `QBOInvoiceSyncService.push_invoice` resolves the QBO customer ID from `invoice.job.contact.business` (preferred) or `invoice.job.contact` (individual customer), and pushes the missing record if needed.

Two push entry points:

- `push_customer(business)` — pushes a `Business`, stores `qbo_customer_id` on it.
- `push_contact_as_customer(contact)` — pushes an individual `Contact` with no business, stores `qbo_customer_id` on the contact.

Both are no-ops if the target already has a `qbo_customer_id`.

### DisplayName collision logic — `QBODisplayNameService`

QBO requires unique `DisplayName` per entity type. The same Minibini `Business` may be both a customer (the company issues them invoices) and a vendor (the company also buys from them). Rules:

- First push for a business uses the plain `business_name`.
- If the business already has the *other* role's QBO ID (e.g. pushing as customer and `qbo_vendor_id` is set), the display name gets a ` (Customer)` or ` (Vendor)` suffix.
- `QBO_DISPLAY_NAME_MAX = 500`; long names are truncated before the suffix is appended.

The current logic only inspects Minibini's own QBO IDs. It does not handle the case where the user's QBO file already contains a customer named "Acme Inc." that was created outside Minibini. That collision surfaces as an SDK error and the sync log records a failure.

### What gets pushed

| Field | Source |
|---|---|
| `CompanyName` (business) | `business.business_name` |
| `DisplayName` | per the rules above |
| `GivenName` / `FamilyName` (contact) | `contact.first_name`, `contact.last_name` |
| `PrimaryPhone` | `business.business_phone` or `contact.phone()` |
| `PrimaryEmailAddr` | `default_contact.email` (business) or `contact.email` |

Billing address, shipping address, payment terms, tax exemption, and notes are not pushed.

## Vendor sync — `QBOVendorSyncService`

Parallel to customer sync. `push_vendor(business)` is called lazily by `QBOBillSyncService.push_bill` and (transitively) by anything else that needs a vendor ID. Same DisplayName collision logic. Stores `qbo_vendor_id` on the `Business`.

## Invoice push — `QBOInvoiceSyncService.push_invoice`

Entry point: `POST /api/invoices/{id}/send-to-qbo/` (defined in `apps/api/invoicing/views.py`). Requires `can_manage_financials`. Body:

```json
{ "send_to": "customer@example.com", "cc": "...", "bcc": "..." }
```

Service flow (`apps/qbo/services.py`):

1. **Short-circuit** — if `invoice.qbo_id` is set, return it. No re-pushing.
2. **Resolve QBO customer** — push `business` (or `contact`) as customer if not yet synced.
3. **Group lines** — `InvoiceGroupingService.group_for_qbo(invoice)` collapses `InvoiceLineItem` rows into one QBO line per `(AccountingCategory, taxable)` tuple. Description: `"Job {job_number}: {category_name} (taxable|non-taxable)"`. Items with no category bucket under `"Uncategorized"`.
4. **Build QBO Invoice** — `_build_qbo_invoice`. Each line gets `Amount`, `Description`, `SalesItemLineDetail.ItemRef` (from `AccountingCategory.qbo_item_id`), and `SalesItemLineDetail.TaxCodeRef = 'TAX'` or `'NON'` based on the group's taxability.
5. **Save** — `qbo_invoice.save(qb=client)`. **Immediately persist `qbo_id` on the Minibini invoice** before doing anything else, so a downstream failure can't cause a duplicate push on retry.
6. **Generate the Minibini job-statement PDF** — `generate_job_statement_pdf(invoice)` (in `apps/invoicing/pdf.py`). The PDF is attached to the customer email only; it is **not** uploaded to QBO. The bookkeeper sees the statement via Minibini, not via the QBO invoice record.
7. **Mark as sent** — `_mark_as_sent` re-fetches the invoice, sets `EmailStatus = 'EmailSent'`, and re-saves. This prevents QBO from showing the invoice as "needs to be sent" in its own UI.
8. **Download QBO PDF** — `_download_qbo_pdf` retrieves QBO's rendered invoice PDF (which carries the Pay Now link and tax calculations).
9. **Send email via Minibini** — `_send_email` calls `OutboundEmailService.send_email` with both PDFs attached. Subject: `"Invoice {invoice_number} — {job_number}"`. Body is a fixed default — no template system.
10. **Log success** to `QBOSyncLog`.

On any exception, `QBOSyncLog` records `status='failed'` with the error message, and the exception re-raises. There is no compensating action — if step 7 succeeds but step 8 fails, the invoice exists in QBO with `qbo_id` set on Minibini but is in an inconsistent "marked sent, not emailed" state. Manual cleanup is required.

### Line grouping — `InvoiceGroupingService.group_for_qbo`

Lives in `apps/invoicing/services.py`. Returns a list of dicts sorted by category name:

```python
{
    'amount': Decimal,
    'category_name': str,        # or 'Uncategorized'
    'qbo_item_id': str,          # from AccountingCategory.qbo_item_id; '' if uncategorized
    'taxable': bool,             # effective taxability via TaxCalculationService
    'description': str,          # "Job JOB-2026-0001: Service (taxable)"
}
```

Effective taxability per line is computed by `TaxCalculationService.get_effective_taxability(item)`, which honors `taxable_override` on the line item with fallback to the category default.

## Bill push — `QBOBillSyncService.push_bill`

Entry point: `POST /api/bills/{id}/send-to-qbo/` (defined in `apps/api/purchasing/views.py`). Requires `can_manage_financials`.

Flow:

1. Short-circuit on `bill.qbo_id`.
2. Require `bill.business` (vendor). Raise `ValueError` if missing.
3. Lazy-push vendor via `QBOVendorSyncService.push_vendor` if `qbo_vendor_id` is not set.
4. Build a QBO `Bill` with `VendorRef`, optional `DocNumber` from `bill.vendor_invoice_number`, and one `AccountBasedExpenseLine` per `BillLineItem`. Each line's `AccountRef` comes from `AccountingCategory.qbo_expense_account_id`. Lines without a category, or with a category that has no expense account mapped, will fail at the QBO end.
5. Save, store `qbo_id`, log.

Bills do not push attachments, do not mark-as-sent, and do not send emails. The push is one-way and silent.

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

## Accounting categories — `QBOAccountsService`

Two endpoints feed the settings UI mapping page:

| Method | Pulls | Used for |
|---|---|---|
| `get_income_items()` | QBO `Item` records with `Type` in `('Service', 'NonInventory')`, `Active=True` | Mapping `AccountingCategory.qbo_item_id` — invoice lines reference QBO Items, not accounts |
| `get_expense_accounts()` | QBO `Account` records with `AccountType` in `('Expense', 'Cost of Goods Sold')`, `Active=True` (dedupe by ID) | Mapping `AccountingCategory.qbo_expense_account_id` — bill and purchase lines reference accounts directly |

Both fields live on `apps.core.models.AccountingCategory`. Both are `CharField(max_length=50, blank=True, default='')`. A category used only for invoicing needs only `qbo_item_id`; one used only for bills/expenses needs only `qbo_expense_account_id`; categories that flow both directions need both.

Both methods are live fetches against QBO — there is no caching layer and no "refresh accounts" endpoint, just `GET /api/qbo/accounts/`.

## Payment polling

Polling is the *only* mechanism for learning about payments — there are no webhooks.

### Invoice polling — `QBOPaymentPollingService.poll_all()`

Walks every `Invoice` where `qbo_id` is set and `qbo_payment_status != 'Paid'`. For each, fetches the QBO invoice and writes:

| Condition | `qbo_payment_status` |
|---|---|
| `Balance == 0` | `'Paid'` |
| `Balance < TotalAmt` | `'Partial'` |
| `Balance == TotalAmt` | `'Unpaid'` |

Also updates `qbo_amount_paid = TotalAmt - Balance` on the `Invoice`.

The polling service writes payment status to the invoice but does **not** advance the parent `Job` to a terminal status when an invoice is fully paid. That status-promotion gap is tracked in `invoicing-and-expenses.md`.

### Bill polling — `QBOBillPaymentPollingService.poll_all()`

Same shape, against `Bill` where `qbo_id` is set and `qbo_payment_status != 'Paid'`. Only writes `qbo_payment_status` (`'Paid'` if balance is zero, else `'Unpaid'` — no `'Partial'` because the bill model doesn't currently track partial-paid amounts).

### Management command

`python manage.py poll_qbo_payments` (`apps/invoicing/management/commands/poll_qbo_payments.py`) wraps both polling services with stdout/stderr output. Intended for a scheduled cron-style trigger. **The scheduler is not yet wired** — see Unfinished work and the matching gap noted in `invoicing-and-expenses.md`.

## UI

Settings page — `frontend/src/routes/SettingsPage.svelte`:

- `QBOConnectionCard.svelte` — calls `/api/qbo/status/`, shows realm ID, connected date, last sync, refresh-token-expiring-soon warning. "Connect to QuickBooks" / "Reconnect" link to `/api/qbo/connect/`. "Disconnect" button.
- Category mapping panel (lives elsewhere on the settings page) — uses `/api/qbo/accounts/` to populate `qbo_item_id` and `qbo_expense_account_id` dropdowns for each `AccountingCategory`.
- Payment-account selection — uses `/api/qbo/payment-accounts/` to populate the `Configuration['qbo_payment_accounts']` list.

Invoice detail — `frontend/src/routes/invoices/InvoiceDetailPage.svelte`:

- "Send to QuickBooks" button (visible when `!invoice.qbo_id` and the user has invoice edit permission) opens `SendToQBODialog.svelte`. Dialog collects `send_to` / `cc` / `bcc` and posts to `/api/invoices/{id}/send-to-qbo/`. Once `qbo_id` is set, the button is replaced by a read-only QBO ID row.

The dialog flow on the Minibini side is documented in `invoicing-and-expenses.md`.

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
| `POST` | `/api/invoices/{id}/send-to-qbo/` | `can_manage_financials` | `QBOInvoiceSyncService.push_invoice` |
| `POST` | `/api/bills/{id}/send-to-qbo/` | `can_manage_financials` | `QBOBillSyncService.push_bill` |

Expense and reimbursement pushes are triggered server-side from their respective save / finalize flows in `apps/expenses` and `apps/reimbursements` — not via dedicated REST actions.

There is no `GET /api/qbo/sync-log/` endpoint yet; `QBOSyncLog` is currently inspected via the Django admin.

## Unfinished work

- **No scheduler for `poll_qbo_payments`.** The command runs cleanly by hand but is not yet wired into a cron / scheduler in any deployed environment. Tracked in `invoicing-and-expenses.md`.
- **No `Job` status promotion when its invoices are fully paid.** Polling updates `Invoice.qbo_payment_status` but doesn't roll up to the job. Tracked in `invoicing-and-expenses.md`.
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
