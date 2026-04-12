# Expenses — Design

**Date:** 2026-04-11
**Status:** Draft
**Scope:** Employee/business expense tracking with QBO push. Covers entry, editing, reimbursement batching, and integration with the existing QBO infrastructure. Phase 4 of the QBO integration roadmap per `docs/designs/2026-03-28-quickbooks-integration.md`.

---

## Overview

Minibini tracks two kinds of expenses:

1. **Company-paid** — purchases the business made directly on its own credit card, checking account, petty cash, or electronic payment (PayPal/Zelle/etc., configured in QBO). These push to QBO as a `Purchase` immediately on save.
2. **Personal** — purchases an employee made with their own money and needs to be reimbursed for. These sit as *outstanding* until an admin with `can_manage_financials` gathers them into a **Reimbursement batch** (one or more expenses paid out together as a single transaction), which pushes to QBO as one `Purchase` with multiple lines.

Both flows support optional linkage to a `Material` on a `WorkOrder`, so job costing and invoicing can pick up actual costs. If no matching material exists, the expense form creates a new `Material` on a per-WorkOrder "Materials" bucket `Task` (auto-created in `complete` status).

There is **no separate approval state**. The data-entry admin is the review step: they categorize, attribute, and correct as they type. Corrections after the fact are handled via edits that re-sync to QBO.

---

## Scope

**In scope:**
- New `apps/expenses/` Django app with `Expense` and `Reimbursement` models.
- `/api/expenses/` and `/api/reimbursements/` DRF viewsets (replacing the existing `apps/api/expenses/` stub).
- Home card submission surface for self-service personal expenses (replacing the `ExpensesList.svelte` placeholder).
- Global `/#/expenses` rich view with filters, "outstanding reimbursements" summary card, and inline editing.
- `/#/reimbursements/:user_id` per-user reimbursement processing page.
- User Detail page gets an **Expenses tab** (shared `UserReimbursementPanel.svelte` with `/#/reimbursements/:user_id`).
- QBO push as `Purchase` entity — one per company-paid expense, one per reimbursement batch.
- Payment account configuration pulled from QBO, stored as JSON in `Configuration['qbo_payment_accounts']`.
- Retirement of the `can_approve_expenses` permission atom.
- Edit/re-sync/delete-void behavior matching the existing `QBOBillSyncService` pattern.

**Out of scope / deferred:**
- **Job Profit & Loss** — separate feature, separate design. This work produces the data but does not consume it.
- **Receipt photo upload.** Physical hand-off and free-text description covers the common case. `FileField` + storage backend decisions deferred.
- **Payroll reimbursement method.** Requires QBO Payroll integration.
- **QBO Employee-as-Vendor** record creation for reimbursements. `PrivateNote` audit trail is sufficient for v1.
- **Material → WorkOrder direct FK refactor.** Explicitly out of scope. Materials continue to live on Tasks; the "Materials" bucket task on each WO is the workaround.
- **Changing existing Material costs** when an expense links to them. Material keeps its estimated cost untouched; the expense carries the actual. Resolved at the P&L layer later.
- **Recurring expense templates, OCR/mobile capture, bulk CSV import.**
- **Custom `PaymentType` override per expense.** Derived mechanically.
- **Permission gating split** that would let a Bookkeeper reach the User page Expenses tab without `can_manage_config`. The global `/#/expenses` and `/#/reimbursements/:user_id` surfaces provide a full path for financials-only users; the User page tab is an Owner convenience.

---

## State machines

Two tracks branching on `payment_method`. Edits are allowed on any non-`rejected` expense and re-sync to QBO per the behavior in `apps/qbo/services.py` `QBOBillSyncService`.

**Personal (`payment_method = 'personal'`):**

```
submitted ──► reimbursed     (batch created; QBO Purchase push owned by the batch)
     │
     └──────► rejected       (never pushes to QBO)
```

`purchased_by` is **required** for personal expenses — it's who gets the reimbursement check. Edits to a `reimbursed` expense trigger a re-push of the owning batch's QBO Purchase (amount edits are technically destructive to real-world integrity; we trust the admin to handle any check-adjustment outside Minibini).

**Company-paid (`payment_method = 'company'`):**

```
(on save) ──► synced          (QBO Purchase created, qbo_id stored)
                │
                └──► re-sync on edit
                │
                └──► sync_failed  (push failure; retry button available)
```

`purchased_by` is **optional** — the person who physically made the purchase if different from the admin entering the receipt. Often left blank for company-paid data entry from a pile of receipts.

No `rejected` transition for company-paid; deletion is the escape hatch (voids the QBO Purchase).

**Reimbursement batch state (`Reimbursement.status`):**

```
pending ──► synced      (QBO Purchase created with N lines, one per expense)
    │
    └────► sync_failed  (retryable)
```

The batch owns the QBO sync state for personal reimbursements; the expenses in the batch are always `reimbursed` in Minibini regardless of QBO sync outcome. The real-world event (the check being cut) is authoritative; QBO is the thing that needs to catch up.

---

## Models

```python
# apps/expenses/models.py

class Expense(models.Model):
    PAYMENT_METHOD_COMPANY = 'company'
    PAYMENT_METHOD_PERSONAL = 'personal'
    PAYMENT_METHOD_CHOICES = [
        (PAYMENT_METHOD_COMPANY, 'Company'),
        (PAYMENT_METHOD_PERSONAL, 'Personal (reimbursement)'),
    ]

    STATUS_SUBMITTED = 'submitted'
    STATUS_REIMBURSED = 'reimbursed'
    STATUS_REJECTED = 'rejected'
    STATUS_SYNCED = 'synced'
    STATUS_SYNC_FAILED = 'sync_failed'
    STATUS_CHOICES = [...]

    # Who
    entered_by = models.ForeignKey('core.User', on_delete=models.PROTECT,
                                   related_name='entered_expenses')
    purchased_by = models.ForeignKey('core.User', on_delete=models.PROTECT,
                                     null=True, blank=True,
                                     related_name='purchased_expenses')
    # required when payment_method == 'personal', enforced in .clean()

    # What
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    purchased_on = models.DateField()
    description = models.TextField(blank=True)
    accounting_category = models.ForeignKey('core.AccountingCategory',
                                            on_delete=models.PROTECT)

    # Payment
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    payment_account_id = models.CharField(max_length=50, blank=True, default='')
    # references Configuration['qbo_payment_accounts'][*].qbo_account_id
    # required when payment_method == 'company'
    reference_number = models.CharField(max_length=50, blank=True, default='')
    # check number / confirmation number / anything; always optional

    # Job linkage
    material = models.ForeignKey('inventory.Material', on_delete=models.SET_NULL,
                                 null=True, blank=True,
                                 related_name='expenses')

    # Status + QBO (for company-paid)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    qbo_id = models.CharField(max_length=50, blank=True, default='')
    qbo_sync_error = models.TextField(blank=True, default='')

    # Reimbursement batch link (personal flow only)
    reimbursement = models.ForeignKey('expenses.Reimbursement',
                                      on_delete=models.PROTECT,
                                      null=True, blank=True,
                                      related_name='expenses')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'expenses'
        ordering = ['-purchased_on', '-created_at']

    def clean(self):
        if self.payment_method == self.PAYMENT_METHOD_PERSONAL:
            if not self.purchased_by:
                raise ValidationError({'purchased_by':
                    'Required for personal (reimbursement) expenses.'})
            if self.payment_account_id:
                raise ValidationError({'payment_account_id':
                    'Not allowed for personal expenses.'})
        elif self.payment_method == self.PAYMENT_METHOD_COMPANY:
            if not self.payment_account_id:
                raise ValidationError({'payment_account_id':
                    'Required for company-paid expenses.'})
```

```python
class Reimbursement(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SYNCED = 'synced'
    STATUS_SYNC_FAILED = 'sync_failed'
    STATUS_CHOICES = [...]

    purchased_by = models.ForeignKey('core.User', on_delete=models.PROTECT,
                                     related_name='reimbursements')
    paid_on = models.DateField()
    payment_account_id = models.CharField(max_length=50)
    # QBO account the money came from. References Configuration payment accounts.
    reference_number = models.CharField(max_length=50, blank=True, default='')
    notes = models.TextField(blank=True, default='')

    created_by = models.ForeignKey('core.User', on_delete=models.PROTECT,
                                   related_name='created_reimbursements')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_PENDING)
    qbo_id = models.CharField(max_length=50, blank=True, default='')
    qbo_sync_error = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reimbursements'
        ordering = ['-paid_on', '-created_at']

    @property
    def total(self):
        return sum((e.amount for e in self.expenses.all()), Decimal('0'))
```

**Notes on model choices:**

- `entered_by` vs `purchased_by` split. `entered_by` is always the logged-in user doing data entry. `purchased_by` is who physically made the purchase. Same person for self-submissions; different for admin-entered-on-behalf-of-someone.
- `purchased_on` is separate from `created_at`. The purchase happened at some date; the entry happens later. Both matter.
- `Reimbursement.purchased_by` lives on the batch itself, not derived from its expenses, to prevent batches that accidentally mix two employees' expenses. Enforced in `ReimbursementService.create_batch`.
- `material` on delete is `SET_NULL` (not `PROTECT` or `CASCADE`). Deleting a material shouldn't block or cascade-delete the expense record — the expense is a historical transaction that outlives any particular material link.
- `AccountingCategory` is required; its `qbo_expense_account_id` mapping drives the QBO line-item account.
- No receipt `FileField` — deferred.
- No `job` FK — reached via `material.task.work_order.job`. Can be denormalized later if query patterns require.
- The bill-push code in `apps/qbo/services.py:493-568` is the pattern to follow for the QBO push/edit/void plumbing.

---

## Payment account configuration

One `Configuration` key holds a JSON array of payment accounts pulled from QBO:

```json
// Configuration['qbo_payment_accounts']
[
  {"qbo_account_id": "42", "display_name": "BoA Business Checking", "account_type": "Bank"},
  {"qbo_account_id": "57", "display_name": "Amex Business", "account_type": "Credit Card"},
  {"qbo_account_id": "89", "display_name": "Petty Cash", "account_type": "Other Current Asset"},
  {"qbo_account_id": "91", "display_name": "PayPal Business", "account_type": "Bank"}
]
```

**Settings flow** (new section on existing `/#/settings`, gated on `can_manage_config`):
1. "Refresh from QBO" button calls `/api/qbo/payment-accounts/` which wraps `QBOExpenseSyncService.get_payment_accounts()`.
2. The backend queries QBO for accounts where `AccountType in ('Bank', 'Credit Card', 'Other Current Asset')` and `Active = true`, following the same pattern as `QBOService.get_expense_accounts()` at `apps/qbo/services.py:597-618`.
3. Admin sees a checklist, selects which to enable, optionally edits display names, saves.
4. Save writes the JSON to the Configuration key.

Pulling fresh from QBO on each save lets accounts deactivated in QBO drop out naturally on the next refresh. No background polling.

**Supporting modern electronic payment services (PayPal/Zelle/Venmo/etc.)** works automatically: the bookkeeper configures them as Bank-type accounts in QBO, Minibini's pull picks them up, they show in the dropdown. On push, they use `PaymentType='Cash'` (see derivation below) and a reference number if one was entered.

---

## UI surfaces

Four surfaces, one shared reimbursement panel component. No new sidebar links for workers; one new link (`Expenses`) for users with `can_manage_financials`.

### 1. Home card (self-service submission)

Replaces the existing `frontend/src/components/home/ExpensesList.svelte` placeholder. Shows:

- "**+ New expense**" button opening `ExpenseForm.svelte` (same form used everywhere else).
- List of the logged-in user's recent expenses where they are `purchased_by` (not `entered_by`), with status badges.

Accessible to any authenticated user. For users without `can_manage_financials`, the form defaults to `payment_method = 'personal'` but allows company-paid submission per our v1 permissions decision. Company-paid paths for workers are permitted; the form shows the full payment account dropdown regardless of permission.

### 2. Global `/#/expenses` (rich admin list)

Gated on `can_manage_financials`. Sidebar link under Admin. Layout:

```
┌─ Outstanding reimbursements ─────────────────┐
│  Dana       3 items    $138.25     →         │
│  Carlos     1 item     $22.00      →         │
│  Ana        5 items    $327.14     →         │
└──────────────────────────────────────────────┘

Filters: user | date range | status | category |
         payment method | job | sync state

[ + New expense ]

Date │ User │ Description │ Category │ Amount │ Status │ Job / Material │ Sync
─────┼──────┼─────────────┼──────────┼────────┼────────┼────────────────┼─────
...
```

- "Outstanding reimbursements" card rows are clickable → `/#/reimbursements/:user_id`.
- Main table rows are clickable for inline edit (form modal or inline row expansion — TBD at implementation).
- `sync_failed` rows show a "Retry push" button inline.
- Username in the table is a link to `/#/reimbursements/:user_id`.
- "+ New expense" button for admin data entry from the receipt pile.

### 3. `/#/reimbursements/:user_id` (per-user reimbursement page)

Gated on `can_manage_financials`. Reached via:
- username click on any `/#/expenses` row
- the summary card on `/#/expenses`
- direct URL / bookmark

Renders `UserReimbursementPanel.svelte` with three sections:

**(a) Outstanding reimbursements** — checkbox table of `submitted` + `personal` expenses for this user. Running total on selection. "Reimburse selected ($X)" button expands an inline metadata form (paid_on / payment account / reference number / notes) with "Confirm reimbursement" submit. Each row has edit/reject actions.

**(b) Past reimbursements** — history of batches for this user with QBO sync state. `sync_failed` rows get a "Retry push" button. Click a row for details.

**(c) Show rejected** — toggle, off by default. When on, reveals a read-only list of rejected expenses for this user (in case a mistaken rejection needs to be visible again).

### 4. `/#/users/:id` Expenses tab

Existing `UserDetailPage.svelte` gains a new tab. Visible when the viewer has `can_manage_config` (current `/users/:id` gating). The tab renders `<UserReimbursementPanel user={user} />` — the same component as `/#/reimbursements/:user_id`.

This means Owners (who have both `can_manage_config` and `can_manage_financials` in the default groups) have two paths to the same reimbursement UI. No duplication, no inconsistency.

---

## Finding / adding a Material on the Expense form

The expense form handles job linkage via a two-step picker:

1. **Job typeahead** — filters to jobs with status in `{draft, approved, needs_attention, blocked}`. Not `complete` or `rejected`.
2. **Material flat list** — once a job is chosen, show every `Material` across every `Task` on every `WorkOrder` of that job, flattened into a single filterable list. Each row shows the material description, parent task name, and estimated quantity.

If nothing matches, a "**+ Add new material**" row expands inline below the list with:
- Quantity + unit
- Description
- Optional PriceListItem typeahead
- **No task picker** — the service auto-attaches to the WO's "Materials" bucket task.

**"Materials" bucket task behavior:**

- One per WorkOrder. Created lazily the first time a user creates a new material via the expense form.
- Name: `"Materials"`.
- Status: `Task.STATUS_COMPLETE` (reachable from `pending` per the transition map at `apps/jobs/models.py:258`). Created in `complete` state directly so it never appears in worker task lists, boards, or in-progress views.
- Reused on every subsequent inline-create for the same WO.

This is a deliberate workaround for the "Materials require a Task parent" constraint. The cleaner refactor — letting Materials attach directly to a WorkOrder with an optional Task — is explicitly out of scope.

**Linking to an existing Material does not mutate it.** The material's estimated cost and quantity stay as-is. The expense carries the actual cost. P&L calculations (future work) will resolve the two by preferring the expense amount over the material's estimated cost on invoicing.

---

## QBO push mechanics

Uniform model: one `Purchase` entity per push.

- **Company-paid expense** → one `Purchase` with one line.
- **Reimbursement batch** → one `Purchase` with N lines, one per expense in the batch.

**Top-level Purchase fields:**

| Field | Source |
|---|---|
| `AccountRef` | `payment_account_id` (the account the user picked) |
| `PaymentType` | Derived from account type — see below |
| `TxnDate` | Expense's `purchased_on`, or batch's `paid_on` for reimbursements |
| `DocNumber` | `reference_number` if present, otherwise unset |
| `PrivateNote` | For company-paid: `"Minibini expense #N — entered by <username>"`. For reimbursements: `"Reimbursement to <username> — Minibini batch #N"` |
| `EntityRef` | Unset in v1. Employee-as-Vendor deferred. |

**`PaymentType` derivation** (QBO requires this field on Purchase even though it's redundant with `AccountRef`):

```python
def qbo_payment_type_for(account_type, reference_number):
    if account_type == 'Credit Card':
        return 'CreditCard'
    if account_type == 'Bank' and reference_number:
        return 'Check'
    return None  # let QBO default to Cash
```

- Bank with reference → `Check` (the common "I wrote a check" case).
- Bank without reference → unset; QBO defaults to `Cash`, which is accurate for electronic transfers (PayPal/Zelle/Venmo/etc.).
- Credit Card → `CreditCard` always.
- Other Current Asset (petty cash, cash on hand) → unset; QBO defaults to `Cash`.

**Line items** use `AccountBasedExpenseLineDetail`, same pattern as the existing `QBOBillSyncService` at `apps/qbo/services.py:547-568`. Both flows build lines the same way — the only difference is the source list (a single-expense iterable for company-paid, or `batch.expenses.all()` for a reimbursement):

```python
# Shared helper used by both push_expense() and push_reimbursement().
def _build_expense_line(expense):
    line = AccountBasedExpenseLine()
    line.Amount = expense.amount
    line.Description = expense.description or f"Expense #{expense.pk}"
    detail = AccountBasedExpenseLineDetail()
    detail.AccountRef = expense.accounting_category.qbo_expense_account_id
    line.AccountBasedExpenseLineDetail = detail
    return line

# Company-paid: one line from the expense itself.
purchase.Line = [_build_expense_line(expense)]

# Reimbursement batch: N lines from the batched expenses.
purchase.Line = [_build_expense_line(e) for e in batch.expenses.all()]
```

No customer/class tracking on line items for v1 — job costing stays local.

**Edit → re-sync:** Mutate the Minibini record in a transaction, then fetch the QBO Purchase by `qbo_id`, rebuild the line(s), write back via sparse update. DB commit stands even if the QBO update fails; state flips to `sync_failed` on the owning entity (expense or batch).

**Delete → void:** Delete the QBO Purchase via the SDK. If the QBO delete fails, Minibini still deletes locally and logs a `QBOSyncLog` entry for bookkeeper follow-up.

---

## Services

```python
# apps/expenses/services.py

class ExpenseService:
    @staticmethod
    def submit(*, entered_by, payment_method, amount, purchased_on,
               accounting_category, description='',
               payment_account_id='', reference_number='',
               purchased_by=None, material=None) -> Expense: ...
    # For company-paid: pushes to QBO synchronously after DB commit; status=synced
    # or sync_failed. For personal: status=submitted, no push.

    @staticmethod
    def update(*, expense, actor, **fields) -> Expense: ...
    # Edits mutate in DB, then re-sync to QBO if the expense (or its owning batch)
    # has a qbo_id. Flips to sync_failed on error.

    @staticmethod
    def delete(*, expense, actor): ...
    # Voids QBO Purchase if synced. Deletes Minibini row. QBO failure logs to
    # QBOSyncLog but doesn't block the local delete.

    @staticmethod
    def reject(*, expense, actor) -> Expense: ...
    # Personal only. status=rejected. No QBO push.

    @staticmethod
    def retry_sync(*, expense, actor) -> Expense: ...
    # Retries the QBO push for sync_failed company-paid expenses.

    @staticmethod
    def find_or_create_materials_task(*, work_order) -> Task: ...
    # Returns the WO's "Materials" bucket task, creating it in STATUS_COMPLETE
    # if it doesn't exist.


class ReimbursementService:
    @staticmethod
    def create_batch(*, purchased_by, expense_ids, paid_on,
                      payment_account_id, reference_number, notes,
                      created_by) -> Reimbursement: ...
    # Validates expenses (all belong to purchased_by, all submitted + personal),
    # transactionally creates the batch and flips expenses to reimbursed.
    # After commit, pushes to QBO. Sets status=synced or sync_failed.

    @staticmethod
    def retry_sync(*, batch, actor) -> Reimbursement: ...

    @staticmethod
    def delete(*, batch, actor): ...
    # Voids the batch's QBO Purchase, flips all linked expenses back to
    # submitted, deletes the batch row. Two-phase confirm in the UI.
```

```python
# apps/qbo/services.py (additions)

class QBOExpenseSyncService:
    @staticmethod
    def push_expense(expense: Expense) -> str: ...
    @staticmethod
    def update_expense(expense: Expense): ...
    @staticmethod
    def void_expense(expense: Expense): ...

    @staticmethod
    def push_reimbursement(batch: Reimbursement) -> str: ...
    @staticmethod
    def update_reimbursement(batch: Reimbursement): ...
    @staticmethod
    def void_reimbursement(batch: Reimbursement): ...

    @staticmethod
    def get_payment_accounts() -> list[dict]:
        # Pulls Bank, Credit Card, and Other Current Asset accounts from QBO.
        # Follows the pattern of get_expense_accounts() at services.py:597-618.
```

---

## API endpoints

| Method | URL | Purpose | Permission |
|---|---|---|---|
| `GET` | `/api/expenses/` | List, filterable | `IsAuthenticated` — scoped to `purchased_by=request.user` unless caller has `can_manage_financials` |
| `POST` | `/api/expenses/` | Create | `IsAuthenticated` (trust model; no payment-method/purchased_by restriction in v1) |
| `GET` | `/api/expenses/:id/` | Retrieve | `purchased_by=self` or `can_manage_financials` |
| `PATCH` | `/api/expenses/:id/` | Edit | `can_manage_financials` |
| `DELETE` | `/api/expenses/:id/` | Delete (voids QBO) | `can_manage_financials` |
| `POST` | `/api/expenses/:id/reject/` | Reject personal | `can_manage_financials` |
| `POST` | `/api/expenses/:id/retry-sync/` | Retry failed push | `can_manage_financials` |
| `GET` | `/api/reimbursements/` | List batches, `?purchased_by=` | `can_manage_financials` |
| `POST` | `/api/reimbursements/` | Create batch | `can_manage_financials` |
| `GET` | `/api/reimbursements/:id/` | Retrieve | `can_manage_financials` |
| `POST` | `/api/reimbursements/:id/retry-sync/` | Retry failed batch | `can_manage_financials` |
| `DELETE` | `/api/reimbursements/:id/` | Unwind batch (two-phase) | `can_manage_financials` |
| `GET` | `/api/reimbursements/outstanding-summary/` | Summary card data | `can_manage_financials` |
| `GET` | `/api/qbo/payment-accounts/` | Pull from QBO for settings | `can_manage_config` |

**DELETE responses return 200 + JSON body** per CLAUDE.md convention — never 204.

**Reimbursement DELETE two-phase:** first `DELETE` returns impact counts (N expenses flipped back, 1 QBO Purchase voided). Second `DELETE ?confirm=true` executes.

---

## Retiring `can_approve_expenses`

Mechanical removal as part of this feature.

**Migration** on `apps.core`:
1. Remove `can_approve_expenses` from `User.Meta.permissions`.
2. Data migration deletes the `Permission` row:
   ```python
   Permission.objects.filter(codename='can_approve_expenses',
                             content_type__app_label='core').delete()
   ```
3. Data migration removes the atom from existing groups (Bookkeeper, Manager, Owner per `apps/core/migrations/0005_create_default_groups.py`):
   ```python
   for group_name in ('Bookkeeper', 'Manager', 'Owner'):
       group = Group.objects.filter(name=group_name).first()
       if group:
           perm = Permission.objects.filter(
               codename='can_approve_expenses',
               content_type__app_label='core',
           ).first()
           if perm:
               group.permissions.remove(perm)
   ```
4. `reverse_code` re-adds the permission for symmetry.

**Code changes:**
- `apps/core/models.py` — remove the atom.
- `apps/api/permissions.py` — remove `CanApproveExpenses` factory class.
- `fixtures/unit_test_data.json` and any other fixtures — grep and remove references in `auth.group` permissions arrays.
- `tests/test_permissions.py`, `tests/test_atom_api_permissions.py` — remove/update tests referencing the atom.
- `tests/test_api_users.py` — the 5-atom validation test becomes a 4-atom test.
- `frontend/src/routes/users/UserDetailPage.svelte:9-14` — remove the `can_approve_expenses` entry from the `ATOMS` constant.
- `CLAUDE.md` — update the Permission Atoms table (drop row) and Default Groups table (drop atom from Bookkeeper/Manager/Owner entries).
- `docs/designs/2026-03-24-permission-atom-redesign.md` — append a note that the atom was retired in the expenses feature; don't rewrite history.

**Important:** `apps/api/users/serializers.py` `PermissionsUpdateSerializer` derives its atom list from `User._meta.permissions` at import time, so it updates automatically when the model changes — no code edit needed there.

---

## Testing strategy

TDD throughout per `CLAUDE.md`. Tests never run from parallel subagents (shared MySQL test DB).

**Test files:**

```
tests/test_expense_model.py                     # Expense model validation, clean()
tests/test_reimbursement_model.py               # Reimbursement, total property
tests/test_expense_service.py                   # ExpenseService (mocked QBO)
tests/test_reimbursement_service.py             # ReimbursementService (mocked QBO)
tests/test_api_expenses.py                      # ExpenseViewSet + permission matrix
tests/test_api_reimbursements.py                # ReimbursementViewSet, two-phase delete
tests/test_qbo_expense_push.py                  # QBOExpenseSyncService (mocked client)
tests/test_retire_can_approve_expenses.py       # PermissionsUpdateSerializer regression
```

**No migration test** — the project has no existing migration test infrastructure and the retirement is indirectly validated by the API/permission tests breaking if the atom still exists.

**QBO mocking boundary:** `QBOService.get_client()` returns a fake client whose `Purchase` constructor captures the pushed payload for assertion. Matches the pattern in `tests/test_qbo_bill_push.py`.

**Integration tests in `tests/test_qbo_expense_push.py`:**

- `test_new_material_creates_bucket_task_once_per_workorder` — first expense creates the "Materials" bucket task in `complete` state; second expense on the same WO with a new material reuses the existing bucket. Assert exactly one "Materials" task on the WO after N new-material expenses.
- `test_existing_material_is_reused_not_duplicated` — expense linked to a pre-existing Material (from an estimate/worksheet) links directly without creating any new task or material. No "Materials" bucket task is spawned. The existing Material's quantity and cost are **unchanged**.
- `test_company_card_expense_end_to_end` — full SFMOMA-paint scenario: create WO, log company-card expense linked to a new material, assert QBO Purchase payload is correct (AccountRef, PaymentType, line AccountRef from the category's `qbo_expense_account_id`, DocNumber blank, PrivateNote populated).
- `test_reimbursement_batch_end_to_end` — three personal expenses, batch into one reimbursement, assert one QBO Purchase with three lines, correct totals, DocNumber = check number.

**Test coverage matrix:**
- Every state transition for Expense and Reimbursement.
- Each branch: company-paid success/failure, personal submit/reject/batch/retry.
- Permission matrix on every API endpoint.
- Error shapes on 400 responses (field-keyed per DRF convention).
- Inline Material creation with and without an existing bucket task.
- Expense edit → QBO re-sync for both company-paid and batch-owned personal expenses.

---

## Known follow-ups (out of scope for this feature)

1. **Job Profit & Loss view** — reads expense data alongside time, bills, and invoice payments. Will prefer the `Expense.amount` over `Material.cost` when computing actuals.
2. **Receipt photo upload** — `FileField` + storage backend.
3. **Material → WorkOrder direct FK refactor** — retires the "Materials" bucket task workaround.
4. **Employee-as-Vendor QBO sync** for reimbursement `EntityRef` and 1099 tracking.
5. **Payroll reimbursement method** — requires QBO Payroll integration.
6. **Multi-account hinting** — remembered default per user or per shop; ability to mark one account as the default for quick entry.
7. **Recurring expenses / templates.**
8. **OCR / mobile receipt capture.**
9. **Bulk CSV import from CC statement.**
10. **Richer permission gating** allowing Bookkeepers (no `can_manage_config`) to see the User page Expenses tab directly. Current v1 accepts the Owner-only path on `/users/:id` + global reimbursement route for others.
11. **Spending dashboards / rollups** by category, job, month.
