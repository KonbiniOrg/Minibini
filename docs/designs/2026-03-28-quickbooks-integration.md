# QuickBooks Online Integration

**Date:** 2026-03-28
**Status:** Draft
**Scope:** QBO API integration for invoicing, billing, expenses, and job costing

---

## Overview

Integrate Minibini with QuickBooks Online so that:

- **Minibini** remains the operational system of record — jobs, work orders, estimates, POs, inventory, time tracking, expenses, and job costing all live here.
- **QBO** handles accounting — AR, AP, general ledger, bank reconciliation, tax prep.
- The bridge between them is **one-way pushes** of financial documents to QBO, with **payment status pulled back** for display in Minibini.

Shop employees work exclusively in Minibini. The bookkeeper/accountant works in QBO. Neither needs access to the other system.

---

## Architecture Principle: Job Statement + Summary Invoice

Minibini does not push every individual line item to QBO. Instead:

1. **Job Statement** (PDF) — Minibini generates a detailed cost breakdown for the customer: labor, materials, expenses, line items. This is what the customer reviews to verify the work. The current Invoice model stays named "Invoice" internally; the customer-facing label is a UI concern to be decided later.

2. **QBO Invoice** — Line items grouped by accounting category and taxability. Example:
   ```
   Job JOB-2026-0042: CNC Machining (taxable)       — $2,000.00  [TAX]
   Job JOB-2026-0042: Design Services (non-taxable)  — $1,250.00  [NON]
   Job JOB-2026-0042: Material Storage (taxable)     — $300.00    [TAX]
   ```
   Each line maps to the appropriate QBO income account via the accounting category. QBO auto-calculates tax on taxable lines using Automated Sales Tax (AST) based on customer location — Minibini only needs to know taxable vs. not, never the rate.

3. **Delivery** — The job statement PDF is attached to the QBO invoice. Minibini downloads the QBO invoice PDF, marks the QBO invoice as sent (`EmailStatus = "EmailSent"`), then sends both PDFs to the customer via Minibini's own email system with full control over recipients, CC/BCC, from address, and body text. QBO's email delivery is not used (its CC/BCC API support is unreliable).

4. **Progress billing** — A job can have multiple invoices. Each pushes to QBO independently: `"Job JOB-2026-0042 Progress Billing #2: CNC Machining — $6,000.00"`. Each gets its own job statement PDF. No multi-job invoices — every invoice is for exactly one job.

**Why this approach:**
- Summarized lines (grouped by category), not every individual line item
- QBO gets proper income account categorization for the P&L
- Taxable/non-taxable handling is correct per line
- QBO handles tax rate calculation automatically (AST)
- The detailed document stays in Minibini connected to job context
- Common pattern in construction, legal, and job shop billing

---

## Integration Surface

### Entities Pushed to QBO

| Entity | Minibini Source | QBO Target | Trigger |
|---|---|---|---|
| Customers | Contact/Business | Customer | Before first invoice for this customer |
| Vendors | Contact/Business | Vendor | Before first bill for this vendor |
| Invoices | Job invoice finalized | Invoice (grouped by category) + PDF attachment | User action: "Send to QBO" |
| Bills | Bill linked to PO | Bill (lines mapped to expense accounts) | On bill approval/finalization |
| Expenses | Approved expense | Expense (company-paid) or Bill (reimbursement) | On expense approval |

### Data Pulled from QBO

| Data | Purpose | Method |
|---|---|---|
| Invoice payment status | Display in Minibini job view | Polling or webhooks |
| Bill payment status | Display in Minibini PO/bill view | Polling or webhooks |
| Employee reimbursement status | Display in Minibini expense view | Polling or webhooks |

### Data Pulled from QBO (Setup)

| Data | Purpose | When |
|---|---|---|
| QBO Items (Service, NonInventory) | Populate income-side category mappings | On QBO connect and on-demand refresh |
| Chart of accounts (expense types) | Populate expense-side category mappings | On QBO connect and on-demand refresh |

### Not Synced

- **Purchase orders** — operational, stay in Minibini only
- **Inventory** — managed in Minibini
- **Time tracking / bleps** — Minibini only (labor costs calculated locally)
- **Jobs / work orders / estimates** — no QBO equivalent
- **Reports** — job P&L is calculated in Minibini from local data; QBO reports stay in QBO
- **Rent income** — tenant rent is QBO-only, not customer-facing
- **Interest income** — bank interest is QBO-only

---

## Customer/Vendor Sync

Contacts and Businesses in Minibini map to Customers and Vendors in QBO. These are **separate record types** in QBO — there is no unified contact entity. A business that is both a customer and a vendor has two QBO records.

- Sync is **Minibini → QBO only**. Minibini is the source of truth for contact data.
- **Lazy creation** — records are pushed to QBO only when needed:
  - Customer record created when the first invoice is pushed for that business
  - Vendor record created when the first bill is pushed from that business
- Store `qbo_customer_id` and `qbo_vendor_id` on the Business model. A business can have one, both, or neither.

### DisplayName Uniqueness

QBO requires unique `DisplayName` across all Customers, Vendors, and Employees. A business that serves both roles cannot have the same name for both records.

**Convention:**
- The **first** QBO record created for a business uses the plain name: `"Acme Corp"`
- If a **second** record is needed later (the other role), it gets a suffix: `"Acme Corp (Customer)"` or `"Acme Corp (Vendor)"`
- `CompanyName` field is set identically on both records (no uniqueness constraint on CompanyName)
- The sync logic checks whether `qbo_customer_id` or `qbo_vendor_id` already exists on the Business. If the other role's record is already in QBO, the new record gets the suffix. No renaming of existing records.

This is handled automatically by the sync logic — the user never sees or manages QBO DisplayNames.

---

## Accounting Categories (LineItemType → AccountingCategory Rename)

### Current State

`LineItemType` already has:
- `code`, `name`, `taxable`, `default_description`, `is_active`
- Used on `BaseLineItem` via `line_item_type` FK (with `taxable_override` and `tax_rate_override` per line)
- Examples: Service, Material, Product, Freight, Overhead

### Future State

Rename `LineItemType` → `AccountingCategory`. Add QBO account mapping fields:

```python
class AccountingCategory(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    taxable = models.BooleanField(default=True)
    default_description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    # QBO mappings (populated after connecting to QBO)
    qbo_item_id = models.CharField(max_length=50, blank=True)             # QBO Item (Service/NonInventory) for invoice lines
    qbo_expense_account_id = models.CharField(max_length=50, blank=True)  # QBO expense account for bill/PO/expense lines
```

**Important:** QBO invoices require Item references, not direct account references. Each AccountingCategory maps to a QBO **Item** (Service or NonInventory type), which itself is linked to an income account in QBO. The `qbo_item_id` stores this Item reference. The income account mapping is configured on the Item in QBO, not in Minibini.

For the expense side (bills, POs, expenses), QBO uses account-based lines (`AccountBasedExpenseLineDetail`), so `qbo_expense_account_id` maps directly to a Chart of Accounts entry.

A category can map to one or both sides:
- "CNC Machining" → QBO Item (revenue from machining work)
- "Design Services" → QBO Item (non-taxable revenue)
- "Shop Supplies" → QBO expense account (COGS or operating expense)
- "Materials" → both (QBO Item when sold, expense account when purchased)
- "Storage" → QBO Item (customer material storage fees)

### How It's Used

**Invoice push:** Group Minibini invoice line items by accounting category + taxability. Each group becomes one QBO invoice line, using the category's `qbo_item_id` as `ItemRef`.

**Bill push:** Each bill line item maps to its category's `qbo_expense_account_id` via `AccountBasedExpenseLineDetail`.

**Expense push:** Expense uses its accounting category to map to the correct QBO expense account.

**Setup flow:** After connecting to QBO, the shop owner maps each accounting category:
- **Income side:** Select a QBO Item (Service or NonInventory) from a dropdown populated by pulling Items from QBO. The QBO Item determines which income account the revenue posts to.
- **Expense side:** Select a QBO expense account from a dropdown populated by pulling the chart of accounts from QBO.
This is a one-time configuration per category.

**Deferred: Chart of accounts drift.** If the business renames, deactivates, or restructures accounts in QBO after mapping, Minibini's stored `qbo_income_account_id` / `qbo_expense_account_id` references will break. Needs a validation or re-sync mechanism eventually — out of scope for initial build.

### Tax Handling

- `AccountingCategory.taxable` provides the default (e.g., "Design Services" is non-taxable in CA)
- `BaseLineItem.taxable_override` allows per-line exceptions
- `BaseLineItem.tax_rate_override` is used for **estimates only** (approximate tax display for customer)
- Actual tax on QBO invoices is calculated by QBO's Automated Sales Tax engine
- **Verify in sandbox (Phase 2):** Does QBO infer taxability from the income account/item configuration alone, or does Minibini need to explicitly pass `TaxCodeRef` (`TAX`/`NON`) on each invoice line? If QBO handles it from account settings, Minibini can skip sending taxability. If not, it's trivial to include since `AccountingCategory.taxable` already has the data.

### Rename Scope

The rename from `LineItemType` → `AccountingCategory` happens as part of the QBO integration build, not before. It touches: model, FK references on BaseLineItem and all subclasses, forms, views, serializers, templates, tests, fixtures, admin, and the `li_types` db_table.

---

## Invoice Flow

```
Job complete (or progress billing milestone reached)
  → User finalizes invoice in Minibini (detailed line items, totals)
  → User clicks "Send to QBO"
  → Minibini ensures Customer exists in QBO (create if needed)
  → Minibini generates job statement PDF (detailed cost breakdown)
  → Minibini groups invoice line items by accounting category + taxability
  → Minibini creates QBO Invoice with grouped lines, each mapped to QBO income account
  → Minibini uploads job statement PDF as attachment to QBO Invoice
  → Minibini marks QBO invoice as sent (EmailStatus = "EmailSent" via sparse update)
  → Minibini downloads the QBO invoice PDF (GET /invoice/{id}/pdf)
  → Minibini sends email to customer with both PDFs attached (QBO invoice + job statement)
  → Email sent via Minibini's email system with full control over To/CC/BCC/from/body
  → Store qbo_invoice_id on Minibini invoice record
  → Customer pays via QBO (credit card, ACH, check — Pay Now link in QBO invoice PDF)
  → Minibini polls for payment status (hourly management command)
  → Payment status displayed on job detail in Minibini
```

---

### Invoice Email Delivery

Email is sent by Minibini, not QBO. QBO's invoice email API has unreliable CC/BCC support (`BillEmailCc`/`BillEmailBcc` often silently fail to persist, and the `/send` endpoint only accepts a single `sendTo` address). Instead, Minibini handles all email delivery directly.

**Flow:**
1. After creating and attaching the job statement to the QBO invoice, Minibini marks the invoice as sent in QBO (`EmailStatus = "EmailSent"` via sparse update). This prevents QBO from showing a "needs to be sent" indicator.
2. Minibini downloads the QBO invoice PDF (`GET /invoice/{id}/pdf`). This PDF includes the QBO-calculated tax, total, and "Pay Now" link.
3. Minibini sends an email to the customer with both PDFs attached: the QBO invoice (for payment) and the job statement (for cost breakdown).

**Recipients:**
- **To**: single email address, typically the Contact who ordered the work. Pre-filled from the Contact's email; user can override before sending.
- **CC**: comma-separated. For AP departments, project managers, or other stakeholders.
- **BCC**: same format. For internal copies if needed.

This supports the common case of different contacts from the same business ordering work — each gets their invoice directly, with AP copied as needed. All recipient fields are fully controlled by Minibini.

**Deferred: AP contact / AP email on Business.** Currently CC/BCC are entered manually by the user at send time. In future, the Business model may need an `ap_email` field (or an AP Contact reference) so that CC can be auto-populated for invoice sends.

Email subject, body template, and from address are configured in Minibini (not QBO). The QBO invoice PDF includes a "Review and Pay" link automatically.

---

## Bill Flow (Accounts Payable)

```
PO created in Minibini (linked to job, inventory)
  → Goods received, inventory updated in Minibini
  → Vendor invoice arrives
  → User creates Bill in Minibini linked to PO
  → On finalization, Minibini pushes Bill to QBO
    → Ensure Vendor exists in QBO (create if needed)
    → Create QBO Bill with line items from PO
  → Bookkeeper pays bill in QBO
  → Minibini pulls payment status back
```

Bill line items map to PO line items which already exist in Minibini. Each line's accounting category provides the `qbo_expense_account_id` for proper categorization in QBO (COGS, operating expense, etc.).

---

## Expense Flow

Expenses are purchases made without a PO — credit card charges, petty cash, employee reimbursements.

### Submission and Approval (Minibini)

1. Employee submits expense: amount, accounting category, receipt photo, payment method (company card / personal card / petty cash / check), optionally linked to a job. The accounting category determines both the QBO expense account and taxability.
2. Approval workflow based on `can_approve_expenses` atom:
   - Under threshold: auto-approved (threshold TBD, configurable in Configuration)
   - Over threshold: requires approval from user with `can_approve_expenses`
3. Employee sees status in Minibini: submitted → approved/rejected → synced → reimbursed (if applicable).

### Push to QBO (on approval)

| Payment Method | QBO Entity | Notes |
|---|---|---|
| Company credit card | Purchase (Expense) | Linked to CC account in QBO |
| Company check | Purchase (Expense) | Linked to bank account |
| Petty cash | Purchase (Expense) | Linked to petty cash account |
| Personal card (reimbursement) | Bill to employee | Employee is vendor; bookkeeper pays via payroll or check |

### Job Linkage

If an expense is linked to a job, that cost feeds into the job P&L calculation in Minibini. The QBO entity doesn't need to know about the job — job costing is Minibini's domain.

---

## Job Profit & Loss

Calculated entirely in Minibini from local data:

| Revenue | Source |
|---|---|
| Invoice payments | Payment status pulled from QBO |

| Costs | Source |
|---|---|
| Labor | Bleps × hourly rate (Minibini) |
| Materials | PO line items linked to job (Minibini) |
| Expenses | Approved expenses linked to job (Minibini) |
| Subcontractor costs | Bills linked to job (Minibini) |

The only QBO dependency is knowing whether the customer has actually paid. Everything else is local.

---

## OAuth & Connection Management

### Authentication
- OAuth 2.0 authorization code flow (QBO's only option)
- Access token: 1-hour expiry
- Refresh token: 100-day expiry (rolling)
- Must store: access token, refresh token, realm_id (company ID), token expiry timestamps

### User Experience
- "Connect to QuickBooks" button in Settings (requires `can_manage_config`)
- OAuth redirect flow, tokens stored securely
- Connection status visible in Settings: connected/disconnected/token expiring
- If refresh token expires (100 days without activity), user must re-authorize

### Token Health
- Background job refreshes access token before expiry
- Warning when refresh token is approaching 100-day limit
- Email/notification to admin if connection drops

---

## SPA UI and API Endpoints

The Svelte SPA is the primary UI. All QBO interaction goes through API endpoints — no Django HTML views for QBO features.

### API Endpoints (`/api/qbo/`)

| Endpoint | Method | Permission | Purpose | Notes |
|---|---|---|---|---|
| `/api/qbo/connect/` | GET | `can_manage_config` | Redirect to Intuit OAuth | Browser navigation, not XHR. SPA opens in same window or popup. |
| `/api/qbo/callback/` | GET | `can_manage_config` | OAuth callback from Intuit | Browser redirect from Intuit. Stores tokens, redirects to SPA (e.g., `/#/settings`). |
| `/api/qbo/status/` | GET | `can_manage_config` | Connection status | DRF `@api_view`. Returns: connected/not_connected, realm_id, refresh token health. |
| `/api/qbo/disconnect/` | POST | `can_manage_config` | Deactivate connection | DRF `@api_view`. |
| `/api/qbo/accounts/` | GET | `can_manage_config` | Pull QBO chart of accounts | DRF `@api_view`. Returns income + expense accounts for category mapping. |
| `/api/qbo/sync-log/` | GET | `can_manage_config` | Recent sync history | DRF `@api_view`. Paginated list of QBOSyncLog entries. |

Future phases will add:
- `/api/invoices/{id}/send-to-qbo/` — push invoice + send email (Phase 2)
- `/api/bills/{id}/send-to-qbo/` — push bill (Phase 3)
- `/api/expenses/` — expense CRUD + approval (Phase 4)

### OAuth Flow (Browser-Based)

Connect and callback are the only non-XHR endpoints. The OAuth flow requires browser redirects:

1. SPA navigates to `/api/qbo/connect/` (full page navigation or popup)
2. Django redirects to Intuit authorization URL
3. User authorizes in Intuit
4. Intuit redirects to `/api/qbo/callback/`
5. Django stores tokens, redirects to `/#/settings` (SPA picks up)
6. SPA calls `/api/qbo/status/` to confirm connection

### SPA Components (by Phase)

**Phase 1: Settings — QBO Connection**
- Connection status card: connected/disconnected, realm_id, last sync time
- "Connect to QuickBooks" button (navigates to `/api/qbo/connect/`)
- "Disconnect" button (calls `/api/qbo/disconnect/`)
- Refresh token health warning if expiring soon

**Phase 2: Settings — Category Mapping + Invoice Push**
- Accounting category list with QBO account dropdowns (income + expense)
- Pull from `/api/qbo/accounts/` to populate dropdowns
- On job/invoice detail: "Send to QBO" button
- Email recipient picker: pre-filled from Contact, editable, CC/BCC fields
- QBO sync status badge on invoice (not synced / synced / payment received)

**Phase 3: Bill Push**
- QBO sync status badge on bill detail
- "Send to QBO" action on finalized bills

**Phase 4: Expenses**
- Expense submission form (amount, category, receipt upload, job link, payment method)
- Approval queue for managers
- Expense list with status (submitted/approved/synced/reimbursed)

**Phase 5: Job P&L**
- Revenue vs. cost summary on job detail page
- Breakdown by category (labor, materials, expenses, subcontractors)
- Payment status from QBO

---

## New Models (Preliminary)

```python
# Connection management
class QBOConnection(models.Model):
    """Stores OAuth tokens and connection state. Singleton per Minibini instance."""
    realm_id = models.CharField(max_length=50)
    access_token = models.TextField()  # encrypted
    refresh_token = models.TextField()  # encrypted
    access_token_expires_at = models.DateTimeField()
    refresh_token_expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    connected_at = models.DateTimeField()
    last_sync_at = models.DateTimeField(null=True)

# Sync tracking
class QBOSyncLog(models.Model):
    """Audit trail for all QBO sync operations."""
    entity_type = models.CharField(max_length=50)  # 'invoice', 'bill', 'expense', 'customer', 'vendor'
    entity_id = models.IntegerField()
    qbo_entity_type = models.CharField(max_length=50)
    qbo_entity_id = models.CharField(max_length=50)
    action = models.CharField(max_length=20)  # 'create', 'update', 'send'
    status = models.CharField(max_length=20)  # 'success', 'failed', 'pending'
    error_message = models.TextField(blank=True)
    synced_at = models.DateTimeField(auto_now_add=True)

# Expense (new feature)
class Expense(models.Model):
    """Employee-submitted expense, optionally linked to a job."""
    submitted_by = models.ForeignKey(User, on_delete=models.PROTECT)
    job = models.ForeignKey('jobs.Job', null=True, blank=True, on_delete=models.SET_NULL)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField()
    accounting_category = models.ForeignKey('core.AccountingCategory', on_delete=models.PROTECT)
    payment_method = models.CharField(max_length=20)  # company_card, personal, petty_cash, check
    receipt = models.FileField(upload_to='receipts/', null=True, blank=True)
    status = models.CharField(max_length=20)  # submitted, approved, rejected, synced, reimbursed
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='approved_expenses')
    submitted_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True)
    qbo_id = models.CharField(max_length=50, blank=True)

# Renamed model (from LineItemType)
# AccountingCategory adds: qbo_income_account_id, qbo_expense_account_id
# See "Accounting Categories" section above for full schema

# Fields added to existing models
# Business: qbo_customer_id, qbo_vendor_id
# Invoice: qbo_id, qbo_payment_status, qbo_amount_paid
# Bill: qbo_id, qbo_payment_status
```

---

## Implementation Phases

### Phase 1: OAuth + Customer/Vendor Sync
- QBOConnection model and token management
- "Connect to QuickBooks" settings UI
- Customer sync (Business → QBO Customer)
- Vendor sync (Business → QBO Vendor)
- QBOSyncLog for audit trail

### Phase 2: Invoice Push + AccountingCategory
- Rename LineItemType → AccountingCategory, add QBO account mapping fields
- QBO chart of accounts pull for mapping setup
- Settings UI for mapping accounting categories to QBO accounts
- Job statement PDF generation
- Invoice push: group line items by category + taxability, create QBO invoice
- PDF attachment upload, mark as sent in QBO, download QBO invoice PDF
- Invoice email delivery via Minibini (not QBO) with To/CC/BCC support
- Payment status polling (management command + cron, hourly)

### Phase 3: Bill Push
- Push bills to QBO on finalization
- Payment status polling for bills

### Phase 4: Expenses
- Expense model and submission UI
- Approval workflow
- Push approved expenses to QBO
- Reimbursement status tracking

### Phase 5: Job P&L View
- Aggregate revenue and costs per job
- Display on job detail page

---

## Dependencies

- **Python library:** `python-quickbooks` (community SDK)
- **QBO subscription:** Customer must have active QBO account (any tier — API access is included)
- **PDF generation:** Needed for job statements (Phase 2). Library TBD (WeasyPrint, ReportLab, or similar).
- **Cron** — for hourly payment status polling management command. Already available in Docker environment.

---

## Resolved Decisions

1. **Invoice model name** — stays "Invoice" internally. Customer-facing label is a UI concern, deferred.
2. **Expense categories** — use AccountingCategory (renamed LineItemType), which maps to QBO accounts. Not a separate system.
3. **Multi-job invoices** — not supported. Every invoice is for exactly one job. A job can have multiple invoices (progress billing).
4. **Progress billing** — each progress invoice pushes independently to QBO with its own grouped lines and job statement PDF.
5. **Tax handling** — Minibini tracks taxable/non-taxable per line via AccountingCategory + override. QBO calculates actual rates via AST. Estimates show approximate tax only.
6. **Income categorization** — QBO invoice lines grouped by accounting category, each mapped to QBO income account. Covers machine revenue, design services, storage, etc.
7. **Non-customer income** — tenant rent and bank interest are QBO-only, not pushed from Minibini.
8. **Auto-approval threshold** — Configuration key (`expense_auto_approval_threshold`), configurable per shop.
9. **Receipt storage** — deferred. FileField in the model; storage backend decided later.
10. **Async queue** — not for this cycle. Synchronous API calls with SPA handling UX (spinner, success/error). Hourly payment poll via management command + cron. Queue infrastructure likely coming app-wide in a future cycle.
11. **Webhook vs polling** — polling, hourly. Management command on a cron. Sufficient for payment status updates.
12. **DisplayName collisions** — first QBO record for a business uses the plain name; second role gets a suffix ("(Customer)" or "(Vendor)"). No renaming of existing records. CompanyName identical on both.
13. **Invoice email delivery** — Minibini sends invoice emails, not QBO. QBO's CC/BCC API is unreliable (`BillEmailCc`/`BillEmailBcc` silently fail; `/send` endpoint only accepts `sendTo`). Instead: mark QBO invoice as sent via `EmailStatus = "EmailSent"` sparse update, download QBO invoice PDF, send both PDFs via Minibini's email system with full recipient control.
