# Contacts refine: phone lists + active/inactive status

_Spec, 2026-10-11. Branch `feature/contacts-refine`. Disposable: delete once
shipped; the durable record goes into `docs/designs/contacts-and-businesses.md`,
`jobs-and-tasks.md`, `materials-inventory-and-purchasing.md`, and
`data-constraints.md`._

## 1. Goal

Two changes to `Contact` and `Business`:

1. **Phones become a list.** Replace Contact's three fixed phone columns
   (`mobile_number`, `work_number`, `home_number`) and Business's single
   `business_phone` with one `phones` list field on each model. Each entry
   is a number plus an optional free-text label. Zero entries is allowed; the
   "at least one phone" rule is removed. The first entry is the primary
   number; reorder to change it.
2. **Active / Inactive status.** Both models gain an `is_active` flag.
   Inactive records are read-only except for *reactivate* and *delete*, are
   hidden from every chooser and from default lists, show up in explicit
   searches, cannot be attached to new jobs or POs, and freeze the open jobs
   and POs that already point at them.

## 2. Non-goals

- No bulk deactivate from the list page.
- No disabling of every action button on frozen job/PO sub-pages; the server
  guard plus a header banner is the whole treatment (§6.5).
- No change to the QBO import's *matching* logic. Status (§6.6) and phones
  (§6.5) only change what the import writes for records it already matched.
- Inactive QBO customers/vendors that match nothing locally are never
  imported as new inactive records.
- The `JobScopedPermissionMixin` coverage audit is a separate LATER item
  (added 2026-10-11); the freeze guard lives in the service layer for now and
  that decision may be revisited after the audit.

## 3. Data model

### 3.1 `phones` (both models)

```python
phones = models.JSONField(default=list, blank=True)
```

Entry shape: `{"number": "<str>", "label": "<str>"}`.

A module-level helper `clean_phones(value)` in `apps/contacts/models.py`,
called from both models' `clean()`:

- `value` must be a list; each entry a dict. Anything else →
  `ValidationError({'phones': ['...']})`.
- `number`: required, string, whitespace-stripped, non-blank, max 50 chars.
- `label`: optional, string, stripped, max 50 chars; missing → `''`.
- Unknown keys are dropped. Returns the normalized list; `clean()` assigns it
  back to `self.phones`.
- Duplicate numbers are allowed (no rule).

Both models expose the primary number through a plain method, keeping
`Contact.phone()`'s existing call shape and adding the same on Business:

```python
def phone(self):            # primary number
    return self.phones[0]['number'] if self.phones else ''
```

Existing `.phone()` callers are unchanged. Serializers and templates keep
reading it as `source='phone'` / `{{ contact.phone }}`.

### 3.2 `phones_digits` (both models, hidden)

```python
phones_digits = models.CharField(max_length=1000, blank=True, default='', editable=False)
```

Maintained in `save()` (via `clean()`'s normalized list): every entry's
`number` with the characters `space - . ( ) +` removed, joined with a single
space. Example: `[{"number":"(555) 123-4567"},{"number":"555-9999 x12"}]`
→ `"5551234567 5559999x12"`. Never exposed by any serializer. Used only by
search (§5).

This is the one named novelty in the design (no existing derived-column
precedent). Rationale: it keeps today's punctuation-insensitive phone search
without trying to string-strip inside MySQL JSON.

### 3.3 `is_active` (both models)

```python
is_active = models.BooleanField(default=True)
```

Boolean, matching the `RateScheme` / `AccountingCategory` precedent. Read-only
through the serializer: the only writers are the deactivate/reactivate
service methods (§4). History capture: both models already carry `@history`;
the flip shows up as a normal field-change entry. No new history plumbing.

### 3.4 Removed

- `Contact.mobile_number`, `work_number`, `home_number`
- `Business.business_phone`
- The "at least one phone number" check in `Contact.clean()`
- The matching check in `apps/core/management/commands/validate_data.py`

### 3.5 Migration

One migration file, three operations in order:

1. `AddField` ×3 on each model (`phones`, `phones_digits`, `is_active`).
2. `RunPython` fold:
   - Contact: `[work, mobile, home]` in that order, skipping blanks, labels
     `"work"`, `"mobile"`, `"home"`. Work first preserves the primary that the
     old `phone()` priority produced.
   - Business: `business_phone` non-blank → one entry, label `""`.
   - Compute `phones_digits` for every row.
   - Reverse: write the first entry labeled work/mobile/home (or the first
     entry, for Business) back into the old columns; other entries are lost
     (documented, acceptable).
3. `RemoveField` ×4.

Run the full Django suite **without** `--keepdb` after the migration lands
(memory rule: fresh-DB after any migration change).

### 3.6 Fixtures

`fixtures/large_datasets/nealseed.json` and `fixtures/playwright/seed.json`
get the same fold applied by a one-off script kept in the scratchpad (never
committed). RM authorized this transform for this change only; it is not a
general loosening of the "never regenerate nealseed" rule. Review the fixture
diff by eye before committing: only `contacts.contact` / `contacts.business`
rows change, only the phone fields + the three new fields.

Smaller fixtures (`fixtures/unit_test_data.json`,
`fixtures/contacts_base_data.json`, any others the grep finds) are edited by
hand. `tests/test_nealseed_fixture.py` and `tests/test_neals_*` must pass.

## 4. Status rules (service layer, `apps/contacts/services.py`)

### 4.1 Definitions

| Term | Means |
|---|---|
| Open job | `Job.status` in `draft, submitted, approved, in_progress, work_complete` |
| Closed job | `completed, rejected, cancelled` |
| Open invoice | `Invoice.status` in `draft, open, partly-paid` |
| Closed invoice | `paid, cancelled, superseded, defaulted` |
| Open PO | `PurchaseOrder.status` in `draft, issued, partly_received` |
| Closed PO | `received_in_full, cancelled` |

Use the model constants, never the strings.

### 4.2 `ContactService.deactivate_contact(contact)`

Collects **every** blocker, then raises one plain-sentence `ValidationError`
listing all of them, or flips `is_active=False` and saves.

Blockers:

1. Contact is `business.default_contact` **and** that business is active.
   Text: `default contact for <business name> (choose another default first)`.
2. Any open job with `job.contact == contact`. Text:
   `N open job(s) (<job numbers, up to 5, then "…">)`.
3. Any open invoice whose `invoice.job.contact == contact` (independent of
   the job's status — a completed job can still carry an unpaid invoice).
   Text: `N open invoice(s) (<invoice numbers…>)`.
4. Any open PO with `po.contact == contact`. Text: `N open PO(s) (<po
   numbers…>)`.

Message shape: `Cannot deactivate <name>: <blocker>; <blocker>; <blocker>.`
Already inactive → no-op, returns the contact, no error.

### 4.3 `ContactService.reactivate_contact(contact)`

- If `contact.business` exists and is inactive → `ValidationError('Cannot
  reactivate <name>: business <business name> is inactive. Reactivate the
  business first.')`.
- Else flip `is_active=True`, save. Already active → no-op.

### 4.4 `ContactService.deactivate_business(business)`

Blockers (collected, one sentence, same format):

1. Blockers 2–4 of §4.2 evaluated across **all** the business's contacts
   (the default-contact rule does not apply: the default goes inactive with
   the business).
2. Any open PO with `po.business == business`.

Then, in one `transaction.atomic()`: set the business inactive and set every
`business.contacts` row inactive (iterate + `save()`, never
`QuerySet.update()`, so history fires). Already inactive → no-op.

### 4.5 `ContactService.reactivate_business(business)`

In one transaction: set the business active and set **every** one of its
contacts active (symmetric with 4.4: the cascade undoes exactly what it did;
a contact that was individually inactive before the business was deactivated
comes back too — accepted). Already active → no-op.

### 4.6 `ContactService.deactivate_business_impact(business)`

Read-only. Returns
`{'contact_count': int, 'contact_names': [...], 'blockers': [str, ...]}` —
`blockers` empty when deactivation would succeed. Feeds the confirm dialog.

### 4.7 Edits to inactive records

`update_contact` / `update_business` raise `ValidationError('<name> is
inactive. Reactivate it before editing.')` for **any** field change. Same
guard on: `add_note` (the `notes` action), `add-tag`, `remove-tag`,
`set-default-contact`. Delete (two-phase) stays allowed on inactive records.

The default-contact self-healing in `Business.validate_and_fix_default_contact`
is unchanged (it is data-integrity upkeep, not a user edit).

### 4.8 Creating with an inactive party

`JobService.create_job` and `JobService.duplicate_job` raise
`ValidationError({'contact': ['<name> is inactive.']})` when the chosen
contact is inactive, and the same for `contact.business` when that business
is inactive. `PurchaseOrderService.create_po` does the same for `business`
and `contact`. This covers the job form, Duplicate, and the email-to-job and
email-to-PO flows without separate handling.

### 4.9 Duplicate-email 409

`ContactService` duplicate pre-check still matches inactive contacts (email
uniqueness is global). The 409 payload's `existing_contact` carries
`is_active`, so the SPA can offer **Reactivate** next to **View existing**
(§6.4). No new code key.

## 5. Freeze guard

Because open jobs, invoices, and POs block deactivation (§4), a job or PO
whose party is inactive is always a **closed** one. The freeze therefore
bites on reopening (any status transition out of `completed` / `rejected` /
`cancelled`, or out of `received_in_full` / `cancelled` for a PO), on field
edits, notes, tags, line items, deletes, and on anything else a closed record
still accepts today. The guard is written generically (it checks the party,
not the status) so it also holds if some future path leaves an open job on an
inactive contact.

### 5.1 Job

```python
JobService.assert_mutable(job)
```

Raises `ValidationError('This job's contact, <name>, is inactive. Reactivate
the contact, or move the job to an active contact at <business>, before
making changes.')` when `job.contact.is_active` is False. (If the contact's
business is inactive, the contact is inactive too by §4.4, so one check
suffices; the message mentions the business only when it is active.)

Called first in every user-driven mutation entry point that targets a Job or
something it owns:

- `JobService`: `update_job` (see carve-out), `update_status`, `hold_job`,
  `release_job`, `assert_job_deletable` (delete is a mutation), `release_loose_materials`.
- `TaskService`: `create_from_template`, `create_direct`, `update_task`,
  `delete_task`, `reorder_tasks`, `assign`.
- `TaskLifecycleService`: `add_actual_qty`, `complete_task`, `block_task`,
  `unblock_task`, `cancel_task`, `start_work`, `stop_work`, `cancel_work`.
- `BlepService`: `create_historical`, `update`, `delete`.
- Estimate, change-order, deliverable, shipment, and invoice services: every
  create/update/delete/line-item/status/send entry point that resolves to a
  Job. (The plan enumerates them from `grep -n "def " apps/*/services.py`.)
- Job notes (`HistoryEntry` add via the jobs `notes` action's service path).

**Bypass:** calls made with `system_transition=True`, and any path driven by
signals or polling (`apps/estimates/signals.py`, QBO payment polling, estimate
expiry), do **not** call the guard. A frozen job may still be auto-completed
by a QBO payment landing, for instance. `duplicate_job` does not guard the
*source* job (duplicating a frozen job into a new active contact is allowed
and is the intended escape hatch).

**Carve-out in `update_job`:** if the kwargs are exactly `{'contact': X}`
(or `contact_id`), and `X.is_active`, and
`X.business_id == job.contact.business_id`, and that business is not None and
is active, the update proceeds without the guard. Any other field in the same
call → guard fires.

### 5.2 Purchase order

```python
PurchaseOrderService.assert_mutable(po)
```

Raises when `po.business` is inactive or `po.contact` is inactive, naming
whichever is. Called first in every `PurchaseOrderService`,
`PurchaseOrderReceivingService`, and `PurchaseOrderEmailService` mutation
entry point (`update_po`, `update_status`, `reconcile`, `cancel_po`,
`delete_po`, `add_line_item*`, `change_line_job`, `update_line_item`,
`reorder_line_item(s)`, `delete_line_item`, `receive_items`, `receive_all`,
`cancel_line_item`, `reverse_receipt`, `send_po`).

**Carve-out in `update_po`:** exactly `{'contact': X}`, with `X.is_active`,
`X.business_id == po.business_id`, and `po.business.is_active`.

### 5.3 Placement note

Service layer, not the API permission mixin: the mixin covers five viewsets,
and the invoice/shipment/blep viewsets write job-owned state without it. See
the 2026-10-11 LATER entry; may be revisited.

## 6. API

### 6.1 Serializers

| Serializer | Change |
|---|---|
| `ContactSerializer` (detail/list) | `phones` (list, writable), `is_active` (read-only); the three old fields removed |
| Lightweight contact (`fields = ['contact_id','name','email', …]`) | replace the two phone columns with `phone` (primary, read-only) |
| `BusinessSerializer` / `BusinessDetailSerializer` | `phones` (writable), `is_active` (read-only); `business_phone` removed |
| Search result serializers (`apps/api/search/views.py`) | `phone` + `is_active` |
| Job / PO serializers | add `contact_is_active` (and `business_is_active` for PO), read-only, so the banner needs no extra fetch |

### 6.2 Endpoints

| Method + path | Perm | Does |
|---|---|---|
| `POST /api/contacts/{id}/deactivate/` | `CanManageJobs` | §4.2; 200 with the contact payload |
| `POST /api/contacts/{id}/reactivate/` | `CanManageJobs` | §4.3 |
| `POST /api/businesses/{id}/deactivate/` | `CanManageJobs` | §4.4 |
| `POST /api/businesses/{id}/reactivate/` | `CanManageJobs` | §4.5 |
| `GET /api/businesses/{id}/deactivate-impact/` | `CanManageJobs` | §4.6 |

Errors follow the standard contract: service `ValidationError` sentences
render as `{'detail': '...'}` 400 via the central handler. No catch-and-
reshape in the viewset.

### 6.3 List filtering

`GET /api/contacts/` and `GET /api/businesses/` accept `?status=active|
inactive|all`, default `active`. Applied before `starts_with`, `tag`, and
`search`. Retrieve (`/{id}/`) is unaffected: inactive records stay
fetchable.

### 6.4 Search

- Contacts list `search`: text branch unchanged; the stripped branch compares
  against `phones_digits__icontains` (replacing the three annotated columns).
- Businesses list `search`: `business_phone__icontains` → the same stripped
  branch against `phones_digits`.
- `apps/search/services.py` (global + search-within): same substitution in
  `search_contacts`, `search_businesses`, and the within-stored-results
  variants. Global search does **not** apply the status filter (explicit
  search shows inactive records).

### 6.5 QBO

- `push_customer(business)`: `PrimaryPhone` ← `business.phone()`.
- Customer import (`apps/qbo/import_services.py`), for every create/update
  site that currently writes `mobile_number` / `business_phone`: strip the QBO
  number with the §3.2 rule; if no existing entry strips to the same string,
  append `{"number": <qbo number as given>, "label": "qbo"}` at the **end**
  of the list; otherwise leave the list alone. New records get it as the sole
  (primary) entry.

### 6.6 QBO status sync (last phase of the plan)

Status is mirrored to QBO in both directions, for the records that have a
QBO counterpart: a Business (as Customer via `qbo_customer_id`, as Vendor
via `qbo_vendor_id`, or both) and a business-less Contact (as Customer).
Contacts that belong to a business have no QBO entity; their status is
local only, and the docs say so.

**Push (on deactivate / reactivate).** New
`QBOCustomerSyncService.set_active(obj, active)` and
`QBOVendorSyncService.set_active(business, active)`: fetch the QBO entity
by ID, set `Active`, sparse-update with the current `SyncToken`, record via
`save_and_log` (`entity_type` `customer` / `contact_customer` / `vendor`,
action `deactivate` / `reactivate`). `deactivate_business` /
`reactivate_business` call both services when the respective ID is set;
`deactivate_contact` / `reactivate_contact` call the customer one when the
contact has `qbo_customer_id`. Cascade-flipped contacts never push (they
have no QBO entity by the mutual-exclusivity rule).

**Failure policy.** The QBO write happens *inside* the deactivate /
reactivate transaction, after the local blockers pass:
- Record has no QBO ID, or there is no active `QBOConnection` → nothing to
  push; proceed locally.
- Record has a QBO ID and a connection is active → QBO must accept. A QBO
  error (refusal, network, token) raises `ValidationError('QuickBooks
  refused to <de|re>activate <name>: <QBO message>')` and the local flip is
  rolled back. The two systems never silently disagree because of a push.

**Pull (on import).** `QBOImportPullService.pull` also fetches customers
and vendors with `Active=False` (second query each; rows carry
`'active': bool`). `_contacts()` suggestions gain two states for *matched*
rows: `qbo_inactive` (QBO inactive, local active) and `qbo_active` (QBO
active, local inactive). Unmatched inactive rows are dropped. Committing a
`qbo_inactive` row calls `deactivate_business` / `deactivate_contact` with
the push skipped (QBO already agrees); the blocker sentence, if any, is
returned per row and the row stays. Committing a `qbo_active` row calls the
matching reactivate (symmetric cascade applies). A business with both a
customer and a vendor row: both rows show, either commit flips the business
(and the other row then reads as `imported` on the next diff).

**Sandbox verification before implementing this phase** (recorded in the
plan as its first task): QBO's " (deleted)" DisplayName suffix on
inactivation and whether reactivation strips it; whether the API refuses to
inactivate a Customer with a balance or a Vendor with open bills (our PO
blockers cannot see QBO bill balances). Re-read `_adopt_id_by_name`'s
inactive-collision note (`quickbooks-integration.md`) against the findings.
Record both answers in the QBO doc.

## 7. SPA

### 7.1 `PhoneListEditor.svelte` (new, `components/contacts/`)

Props: `phones` (bound list), `errors`. One row per entry: number input,
label input, ▲ (move up; hidden on the first row), ✕ remove. First row shows
a "primary" tag. "Add phone" button appends an empty row. Rows are pending
state; the parent form's Save commits (no blur-saves). Used by
`ContactForm.svelte` and `BusinessForm.svelte`, replacing the three/one phone
inputs. Field errors from `phones` render in a `FieldError` slot under the
editor.

### 7.2 Display

- `ContactDetail` / `BusinessDetail`: a phones block, one line per entry as
  `number · label` (label omitted when blank), primary first.
- `ContactList` / `BusinessList` rows, `CustomerActivity`, job/PO headers,
  `DuplicateContactNotice`, `SenderResolutionForm`, `Search.svelte`,
  `lib/email.js`: use `phone` (primary) wherever a single number was shown.
- Inactive badge (`<span class="badge inactive">inactive</span>`, style in
  `css/app.css`) in: detail headers, list rows when the list is in
  Inactive/All mode, search result rows, job and PO headers next to the
  contact/vendor name.

### 7.3 List page

`ContactListPage.svelte` adds an Active / Inactive / All segmented toggle
next to the Contacts/Businesses checkboxes, default Active, sent as
`status=` to both list calls. Resets `page` to 1 on change (same as the
letter filter).

### 7.4 Detail pages

- Active record: header actions are Edit, **Deactivate**, Delete (Deactivate
  and Delete only for `can_manage_jobs`).
- Inactive record: header actions are **Reactivate** and Delete; Edit, New
  Job, notes form, and tag editor are hidden.
- Contact Deactivate: `POST …/deactivate/` directly (reversible → no
  confirm). On 400, the sentence renders as a `FormMessage` under the header
  actions. On success, reload.
- Business Deactivate: `GET …/deactivate-impact/`; if `blockers` non-empty,
  show them as a `FormMessage` and stop; else open a `Modal`: "This will
  deactivate **Acme Corp** and its 4 contacts (Jane Doe, …). They will be
  hidden from choosers and any open records frozen until reactivated.
  Continue?" with Continue / Cancel. Continue → `POST …/deactivate/`, reload.
- Reactivate: direct POST; a 400 (business inactive) renders as a
  `FormMessage` with a link to the business.
- `DuplicateContactNotice`: when `existing_contact.is_active` is false, add a
  **Reactivate** button (POST reactivate, then navigate to the contact).

### 7.5 Frozen job / PO banner

`JobHeader.svelte` (and the PO detail header): when `contact_is_active` is
false, render a banner in the same slot/style as `JobDetail`'s
`change-request-banner`: "Frozen: contact **Jane Doe** is inactive.
Reactivate her, or move this job to another contact at Acme Corp." (second
clause only when the business is active). Contact name links to the contact.
Buttons elsewhere are not disabled; server refusals surface through
`triageError` as today. The contact swap uses the existing edit-job modal;
when the job is frozen, its `ContactPicker` is scoped with
`?business=<id>` so only same-business active contacts are offered.

### 7.6 Pickers

`ContactPicker`, `BusinessPicker`, `CustomerPicker`, `PurchaseOrderForm`'s
contact list, `PurchaseOrderFormPage`'s business list: no change needed —
they omit `status=` and therefore get active only. Add a Vitest assertion
per picker that the request carries no `status` param (guards against a
future "helpful" `status=all`).

## 8. Tests

**Backend (`tests/`), TDD:** `clean_phones` normalization + errors;
`phones_digits` maintenance; migration fold (via a `MigrationTestCase`-style
test or the fixture tests); each blocker in §4.2 and §4.4 individually and
combined into one sentence; reactivate rules; cascade both directions; §4.7
edit refusal per action; §4.8 create/duplicate refusal; §5 guard on a
representative entry point per service **plus** the two carve-outs (exact
match passes; one extra field fails; cross-business contact fails; inactive
business fails); `status=` filtering + default; search by punctuated phone
on both models; QBO import append-vs-skip; 409 payload carries `is_active`;
§6.6 with the QBO client mocked: push called only when ID + connection
present, QBO error rolls back the local flip with the contract message,
cascade contacts never push, pull includes inactive rows, both suggestion
states, commit of `qbo_inactive` surfaces blockers per row, commit of
`qbo_active` cascades, unmatched inactive rows dropped, customer+vendor
business reconciles to one flip.

**Vitest (`frontend/tests/`):** `PhoneListEditor` (add, remove, move-up,
primary tag, error slot); list-page status toggle sends `status=`;
detail-page action sets for active vs inactive; business deactivate modal
flow (impact → confirm → POST); duplicate notice Reactivate button;
`JobHeader` banner on `contact_is_active=false`; picker requests carry no
`status`.

**Playwright (`e2e/`):** (1) deactivate a contact with an open job → blocker
sentence; close the job (or pick a seed contact with no open records) →
succeeds, contact disappears from the default list, appears under Inactive
and in global search with the badge; (2) deactivate a business → confirm
modal shows the contact count → contacts go inactive; reactivate → all back;
(3) a closed job on an inactive contact shows the banner; reopen is
refused with the freeze sentence; swapping the contact to another at the
same business succeeds, unfreezes, and reopen then works; (4) phone editor round-trip on a contact (add two,
reorder, save, reload shows the new primary).

Only one agent runs Django tests at a time; always `--noinput`.

## 9. Docs to update in the same session

- `docs/designs/contacts-and-businesses.md`: Fields, `clean()`, status
  section (new), API endpoints, filters, search, QBO touchpoints, frontend.
- `docs/designs/jobs-and-tasks.md`: freeze guard + carve-out + banner.
- `docs/designs/materials-inventory-and-purchasing.md`: PO freeze + carve-out.
- `docs/designs/data-constraints.md`: `phones` shape, `is_active` invariants,
  the ok-to-deactivate conditions, and the frozen-record invariant.
- `docs/designs/quickbooks-integration.md`: import phone append rule, the
  status push/pull, the failure policy, the sandbox findings, and the
  "business contacts have no QBO status" note.
- `docs/designs/e2e-testing.md` only if a new persona or seed row is needed.
- Delete this file when the branch is done.

## 10. Decisions log (from the design conversation)

- Phones: list, first = primary, reorder to change; no `is_primary` flag.
- Status: boolean `is_active`, not a string status.
- Reactivation is symmetric: business brings back all its contacts; a
  contact cannot be reactivated under an inactive business.
- Delete stays allowed on inactive records; every other change is refused.
- Freeze covers everything on an open job/PO except the same-business
  contact swap; Duplicate of a frozen job is allowed with a new contact.
- Fixture transform authorized for this change only.
- QBO import appends unknown numbers labeled `qbo`, never clobbers.
- QBO status sync both ways (RM, 2026-10-11): push inside the transaction
  with QBO refusal failing the flip; pull as import suggestions a human
  commits; last phase of the plan so the local status work ships first.
- Guard placement in the service layer; LATER item records the possible
  reversal after the permission-mixin audit.
