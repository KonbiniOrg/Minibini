# Invoice Wizard Design

**Date:** 2026-04-09
**Status:** Approved for planning

## Problem

Invoices in Minibini are generated from job actuals — bleps (time entries) and materials. The straightforward path produces a 1:1 mapping: each Task's bleps become a labor line item, each material becomes a material line item. That works for shops with simple billing, but some customers want their invoices presented differently — labor and materials grouped under task names, multiple tasks rolled into one line item, separate line items for materials vs. labor on the same task, manual line items mixed in, and so on.

The wizard exists so the user can take the same source data and re-aggregate it into the line items the customer wants to see, with the ability to name and price them freely.

## Goals

- Let the user combine bleps and materials from any tasks on a job into named line items in any grouping they choose.
- Let the user add free-form (manual) line items in the same UI.
- Prevent double-billing: an atom claimed by one invoice cannot appear on another.
- Persist work-in-progress automatically — closing the browser does not lose state.
- Reuse the existing draft-invoice lifecycle and the existing post-wizard edit path.

## Non-goals (out of scope for this design)

- The auto-generate "one click, no customization" path that produces a 1:1 invoice. Mentioned only as an alternate flow that will share the same data model.
- Triggers other than a manual button on the job page (e.g., auto-creating an invoice when a job hits `completed`).
- A direct invoice editor that operates outside the wizard. We assume one will exist; the wizard's data model is designed to coexist with it but it is not designed here.
- Flat-rate task billing (a task with no bleps and no materials that the shop still wants to bill). Workaround: model the charge as a Material row.
- QBO push and PDF generation. The existing `send_to_qbo` action keeps working unchanged on whatever line items the wizard produces.

## Vocabulary

- **Atom** — the smallest billable unit. Two kinds:
  - **Blep atom**: one `Blep` row. Computed amount = `elapsed × task.rate`.
  - **Material atom**: one `Material` row. Computed amount = `quantity × sell_price`.
- **Claim** — the existence of an `InvoiceLineItemSource` row pointing at an atom. An atom is "claimed" if such a row exists in any non-cancelled invoice.
- **Source pool** — the set of atoms visible to the wizard for a given job, organized as `WorkOrder → Task → atoms`.
- **Bundled line item** — an `InvoiceLineItem` that has one or more `InvoiceLineItemSource` rows. Its price is normally the sum of those atoms' computed amounts.
- **Manual line item** — an `InvoiceLineItem` with zero source rows. Its price, qty, units, and description are all user-typed.
- **Override** — the state in which a bundled line item's stored `price` differs from the sum of its sources' computed amounts. Derived; no flag stored.
- **In sync** — the state in which a bundled line item's stored `price` equals the sum of its sources' computed amounts.

## Data model

### New model: `InvoiceLineItemSource`

A polymorphic join between an `InvoiceLineItem` and the atom it represents. "Polymorphic" means only that the atom side can point at one of two model types (`Blep` or `Material`); it is not a Django generic relation.

```python
# apps/invoicing/models.py

class InvoiceLineItemSource(models.Model):
    SOURCE_BLEP = 'blep'
    SOURCE_MATERIAL = 'material'
    SOURCE_TYPE_CHOICES = [
        (SOURCE_BLEP, 'Blep'),
        (SOURCE_MATERIAL, 'Material'),
    ]

    source_id = models.AutoField(primary_key=True)
    invoice_line_item = models.ForeignKey(
        InvoiceLineItem,
        on_delete=models.CASCADE,
        related_name='sources',
    )
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPE_CHOICES)
    source_pk = models.PositiveIntegerField()

    class Meta:
        db_table = 'invoice_line_item_sources'
        unique_together = [('source_type', 'source_pk')]

    def resolve(self):
        if self.source_type == self.SOURCE_BLEP:
            from apps.jobs.models import Blep
            return Blep.objects.get(pk=self.source_pk)
        if self.source_type == self.SOURCE_MATERIAL:
            from apps.inventory.models import Material
            return Material.objects.get(pk=self.source_pk)
```

**Cardinality.** One `InvoiceLineItem` → 0..N `InvoiceLineItemSource` rows. One atom → 0..1 source row. The `unique_together` on `(source_type, source_pk)` is the database-level enforcement of whole-atom claim.

### Constraint: one draft invoice per job

A partial unique index on `Invoice`:

```python
# Migration
constraints = [
    models.UniqueConstraint(
        fields=['job'],
        condition=models.Q(status='draft'),
        name='unique_draft_invoice_per_job',
    ),
]
```

This makes "create a second draft for a job that already has one" fail at the database level. Multiple non-draft invoices per job (open, paid, cancelled) remain allowed.

### Drop `InvoiceLineItem.task`

The existing single-task FK on `InvoiceLineItem` was a pre-wizard convenience. It is dropped. The wizard's source linkage is the join table, and pre-production state lets us drop the column without a data migration. The `task` field also comes off `InvoiceLineItemSerializer` as part of the same change.

### No changes to `Blep` or `Material`

The atom models remain decoupled from invoicing. The wizard reaches into them via the join table; they do not reach out.

## Services

A new `InvoiceWizardService` in `apps/invoicing/services.py` is the orchestration layer for everything the wizard does. The existing `InvoiceService` keeps its current responsibilities (manual line item CRUD, reorder, status transitions). The wizard service composes on top.

### Methods

| Method | Responsibility |
|---|---|
| `open_for_job(job)` | Returns the draft `Invoice` for the job. Creates one if none exists. Refuses jobs in status `draft`, `submitted`, `cancelled`, or `rejected`. |
| `get_source_pool(invoice)` | Returns the tree: all work orders for the job → non-cancelled tasks → atoms. (`WorkOrder` has no cancelled status, so all work orders are included.) Filters out incomplete bleps (no `end_time`). Annotates each atom with state and computed amount. |
| `add_atoms_to_new_line_item(invoice, atoms)` | Atomically creates an `InvoiceLineItem` plus N `InvoiceLineItemSource` rows. Defaults described below. |
| `add_atoms_to_line_item(line_item, atoms)` | Appends source rows. Recomputes price subject to the in-sync rule. |
| `remove_atoms_from_line_item(line_item, source_ids)` | Deletes the matching source rows. Recomputes price subject to the in-sync rule. If the removal empties the source list, the line item is deleted regardless of override state. |
| `discard_draft(invoice)` | Hard-deletes the draft invoice. Cascade kills line items and source rows; all atoms become available again. |

Manual line item creation (`+ Manual` button), updates (rename, qty, units, manual price edits), reordering, and deletion go through the existing `InvoiceService` methods. The wizard service does not duplicate them.

### Defaults when bundling N atoms into a new line item

| Field | Default |
|---|---|
| `description` | Blank. UI shows a placeholder ("Name this line item…"). The wizard's job is naming; we deliberately don't guess. |
| `qty` | `1` |
| `units` | `'each'` |
| `price` | Sum of atom computed amounts. |
| `accounting_category` | If all atoms share a category, that category. Otherwise null — must be set before the invoice can leave draft (existing `Invoice.clean()` validation handles this when transitioning out of draft). |
| `taxable_override` | `null` (use category default), as today. |

### Recompute rule (in-sync vs. override)

When atoms are added or removed from a bundled line item:

```
old_sum = sum(s.computed_amount for s in line_item.sources)  # before mutation
old_price = line_item.price
in_sync = (old_price == old_sum)

# perform the add or remove

if in_sync:
    line_item.price = sum(s.computed_amount for s in line_item.sources)  # new sum
    line_item.save()
# else: leave price alone — the override survives
```

The override state is *derived* from data equality. There is no `price_overridden` flag stored. The UI computes "in sync" by comparing `price` to the sum of source amounts at display time.

A user "resets" an override by typing the matching number into the price field. A "Reset to computed" link in the UI is a convenience that performs the same action.

### Removal — partial vs. all

`remove_atoms_from_line_item` takes a *subset* of source IDs:

- Removes only the matching source rows. Other atoms stay on the line item.
- Recomputes price subject to the in-sync rule above.
- **If the removal empties the source list, the line item is deleted** — regardless of whether the price was overridden. A user who wants to keep an override after stripping all atoms must instead create a new manual line item.

### Source pool snapshot per session

The set of atoms in the pool tree is determined at wizard mount and frozen for that session. New bleps logged or new materials added by other users (or by the same user in another tab) do *not* appear during the session. Reopening the wizard later (new mount) re-queries fresh.

Within a session, atoms transition between `available` and `claimed_by_current` as the user moves them in and out of line items on the right pane. State updates from concurrent sessions are *not* reflected in the pool display — they are surfaced only when the user attempts to claim an atom that has been claimed elsewhere (see Concurrency below).

### Concurrency: claim conflicts

The `unique_together` on `InvoiceLineItemSource` is the source of truth. When two sessions race to claim the same atom, the second insert raises `IntegrityError`.

The service layer catches this, surfaces it as a `ClaimConflict` exception with the offending atom IDs, and the API returns HTTP 409 with:

```json
{
  "error": "atoms_already_claimed",
  "atom_ids": [{"type": "blep", "id": 123}]
}
```

The frontend can highlight the affected rows and prompt the user to reopen the wizard for a fresh source pool.

## API surface

### SPA route

`#/invoices/:id/wizard` — the wizard works against a specific invoice. Bookmarkable; entering the URL directly loads the existing draft (or 404s if it doesn't exist).

### Endpoint table

**New endpoints:**

| Method | URL | Purpose |
|---|---|---|
| `POST` | `/api/jobs/{id}/start-invoice-wizard/` | Returns `{invoice_id}` for the job's draft. Creates one if none exists. Refuses if the job is in `draft`, `submitted`, `cancelled`, or `rejected` status. |
| `GET` | `/api/invoices/{id}/source-pool/` | Returns the tree (work orders → tasks → atoms) with state and computed amounts. |
| `POST` | `/api/invoices/{id}/line-items-from-atoms/` | Body: `{atoms: [{type, id}, ...]}`. Creates a new line item from N atoms. |
| `POST` | `/api/invoices/{id}/line-items/{lid}/add-atoms/` | Body: same shape. Appends sources to an existing line item. |
| `POST` | `/api/invoices/{id}/line-items/{lid}/remove-atoms/` | Body: `{source_ids: [...]}`. Removes sources. Response: `{line_item, line_item_deleted: bool}`. |

**Existing endpoints reused (with serializer extensions):**

| Method | URL | Use |
|---|---|---|
| `GET` | `/api/invoices/{id}/` | Load draft header, totals, status. |
| `GET` | `/api/invoices/{id}/line-items/` | Load line items — extended to include `sources` per item. |
| `POST` | `/api/invoices/{id}/line-items/` | Create manual line item (no atoms). |
| `PATCH` | `/api/invoices/{id}/line-items/{lid}/` | Rename, edit price/qty/units. |
| `DELETE` | `/api/invoices/{id}/line-items/{lid}/` | Delete a line item (frees its atoms via cascade). |
| `POST` | `/api/invoices/{id}/line-items/reorder/` | Reorder. |
| `DELETE` | `/api/invoices/{id}/?confirm=true` | Discard draft (existing two-step delete pattern). |

### Permissions

All wizard endpoints require `IsAuthenticated` + `CanManageFinancials`, matching the rest of `InvoiceViewSet`.

### Serializer changes

- `InvoiceLineItemSerializer` gets a nested `sources` field. Each source is serialized as `{source_id, source_type, source_pk, description, computed_amount}` — description and amount resolved from the underlying atom at serialization time so the SPA does not need an extra round trip.
- New `SourcePoolSerializer` for the tree response. Custom shape, not a `ModelSerializer`.

## UI / wizard layout

The wizard is a full-width SPA page at `#/invoices/:id/wizard`. Two panes side by side, plus a header and a footer.

```
┌────────────────────────────────────────────────────────┐
│ Header: JOB-2026-0042 / Acme Corp / Draft INV-2026-… │
├──────────────────────────┬─────────────────────────────┤
│ Source pool              │ Line items (N)              │
│   (tree of atoms)        │   (cards, one per line item)│
├──────────────────────────┴─────────────────────────────┤
│ [Discard]   [+ Manual] [→ Add to #N] [→ New] [Done]    │
└────────────────────────────────────────────────────────┘
```

### Source pool (left pane)

Tree: `WorkOrder → Task → atoms`. Tasks and work orders are collapsible. Each atom is a checkbox row showing description, optional sub-info (date, user for bleps), and computed amount.

**Atom states:**

- **Available** — checkbox enabled, normal text.
- **Claimed by current draft** — checkbox checked-and-disabled, text dimmed, tiny `→ #N` link to the line item card on the right.
- **Claimed by other invoice** — checkbox disabled, text dimmed, tiny link `→ INV-XXXX` to the claiming invoice's detail page.

**Tasks:**

- A non-cancelled task with at least one billable atom is shown expanded by default with its atoms as children.
- A non-cancelled task with no bleps and no materials is shown in dimmed style with the hint "(no billable items)" and no children.
- Cancelled tasks are not shown.

**Filter controls (top of pane):**

- Hide already-claimed atoms (default off — visible for context).
- Hide tasks with no billable items (default off — visible for context).

### Line items panel (right pane)

A vertical list of line item cards in `line_number` order. One card may be "selected" (focused) at a time, which controls which "→ Add to #N" target the footer button uses.

**Card layout — bundled line item:**

- Header row: line number, name (inline-editable), drag handle for reorder, delete button.
- Price block:
  - **In sync:** single number (e.g., `$125.00`).
  - **Overridden:** two numbers, labeled — `Computed: $127.43 / Billed: $125.00 — overridden`. A "Reset to computed" link clears the override by setting price to the computed value.
- Atom list (collapsible): one row per source, showing description and a small "remove" (×) that releases just that atom back to the pool.

**Card layout — manual line item:**

- Same header row, with a small "manual" badge.
- No price block (replaced by editable inputs).
- Editable fields: qty, units, price.
- No atom list.

### Footer / global actions

| Button | Behavior |
|---|---|
| `Discard draft` | Bottom-left, separated from the others. Confirmation dialog. Hard-deletes the draft Invoice. |
| `+ Manual` | Creates an empty manual line item. |
| `→ Add to #N` | Enabled when atoms are checked in the source pool *and* a line item is selected. Adds checked atoms to that line item. |
| `→ New line item from selected` | Primary action. Enabled when atoms are checked. Creates a new bundled line item from them and scrolls it into view with name field focused. |
| `Done` | Closes the wizard, navigates to the standard invoice detail page. Does not transition the draft to `open` — that is a separate explicit action elsewhere. |

### Discard placement

`Discard draft` lives only inside the wizard. The job page may show a "Continue draft (INV-XXXX)" link when a draft exists, but discarding requires opening the wizard first. This adds one click of friction to a destructive action.

### Concurrent-claim error UI

When the user clicks a claim action and the API returns 409:

1. Toast: "Some atoms were claimed by another invoice while you were working. Reopen the wizard to refresh."
2. Disable the affected atom rows in the source pool with the new claiming-invoice link.
3. Any successfully-claimed atoms in the same request remain in their new line item.

### Closing the wizard without finishing

Browser back, refresh, navigation away — all just leave the draft sitting on the job. Reopening the wizard from the job page picks it up.

## Testing strategy

Per the project's TDD discipline, every layer gets tests written first.

### Model layer

- `InvoiceLineItemSource` unique constraint enforcement.
- `InvoiceLineItemSource.resolve()` returns the right concrete instance per source type.
- `unique_draft_invoice_per_job` constraint enforcement.
- Cascade: deleting an `InvoiceLineItem` deletes its source rows.
- Cascade: deleting an `Invoice` deletes its line items and source rows.

### Service layer (`InvoiceWizardService`)

- `open_for_job` creates a draft when none exists.
- `open_for_job` returns the same draft on a second call.
- `open_for_job` refuses on terminal/pre-approval job statuses.
- `get_source_pool` excludes incomplete bleps.
- `get_source_pool` excludes cancelled tasks and work orders.
- `get_source_pool` includes tasks with no atoms, marked disabled.
- `get_source_pool` annotates atom states correctly: `available`, `claimed_by_current`, `claimed_by_other`.
- `get_source_pool` treats atoms on cancelled invoices as available.
- `add_atoms_to_new_line_item` creates the line item and source rows in one transaction.
- Default price equals sum of atoms; default category is uniform-or-null.
- `add_atoms_to_line_item` recomputes price when in sync.
- `add_atoms_to_line_item` preserves price when overridden.
- `remove_atoms_from_line_item` removes a partial subset and recomputes when in sync.
- `remove_atoms_from_line_item` preserves the override price on a partial removal.
- Empty-source-list rule: line item is deleted when the last atom is removed, even if the price was overridden.
- `discard_draft` cascades and frees atoms.
- Wizard mutations against a non-draft invoice raise `ValidationError`.
- Concurrent claim raises a clean `ClaimConflict` with atom IDs, no partial state.

### API layer

- `start-invoice-wizard` creates or returns the draft, refuses bad job status, requires `CanManageFinancials`.
- `source-pool` returns the expected tree shape; permissions enforced.
- `line-items-from-atoms` returns the new line item with sources; 409 on conflict; 400 on non-draft invoice.
- `add-atoms` appends and returns updated line item.
- `remove-atoms` returns `line_item_deleted` flag.
- All endpoints reject anonymous and unauthorized users.

### Frontend

Component-level tests are not part of the project's current testing pattern. The wizard relies on the API tests above for everything that crosses the network boundary, plus manual smoke testing for UI behavior.

## File layout

### New files

```
apps/invoicing/
  models.py                            # Add InvoiceLineItemSource
  services.py                          # Add InvoiceWizardService
  migrations/
    NNNN_add_invoice_line_item_source.py
    NNNN_unique_draft_invoice_per_job.py
    NNNN_drop_invoicelineitem_task_fk.py

apps/api/invoicing/
  views.py                             # Add wizard actions to InvoiceViewSet
  serializers.py                       # Add InvoiceLineItemSourceSerializer,
                                       # extend InvoiceLineItemSerializer with `sources`,
                                       # add SourcePoolSerializer

apps/api/jobs/
  views.py                             # Add start_invoice_wizard action on JobViewSet

frontend/src/
  routes/invoices/
    InvoiceWizardPage.svelte           # New route component
  components/invoices/
    WizardSourcePool.svelte
    WizardLineItemCard.svelte
    WizardFooter.svelte

tests/
  test_invoice_line_item_source.py
  test_invoice_wizard_service.py
  test_invoice_wizard_api.py
```

### Modified files

```
apps/invoicing/models.py               # Drop InvoiceLineItem.task FK
frontend/src/App.svelte                # Add /invoices/:id/wizard route
frontend/src/routes/jobs/JobDetailPage.svelte
                                       # Add "Build invoice" / "Continue draft (INV-XXX)"
                                       # button — same button, label depends on
                                       # whether a draft exists for the job
```

### Migration order

1. **Add `InvoiceLineItemSource`** — creates the table and unique constraint. Empty initial data.
2. **Add `unique_draft_invoice_per_job`** — partial unique index on `Invoice`. Includes a pre-flight check operation that errors with a helpful message if the database currently has duplicate drafts (shouldn't happen in pre-production state, but worth catching).
3. **Drop `InvoiceLineItem.task`** — removes the legacy column. No data migration needed; pre-production state lets us drop without backfilling. Fixtures referencing the old field need updating in the same change set per the project's "fixtures track migrations" convention.

## Future work (deferred)

- **Auto-generate path** — a one-click "create invoice from all uninvoiced atoms" action that produces a 1:1 draft without opening the wizard. Will share the same data model.
- **Auto-trigger** — creating a draft invoice when a job hits `completed` (or some other status). Requires policy decisions about which work orders are billed.
- **Direct invoice editor** — a non-wizard editor for tweaking existing invoices. Will need to coexist with the wizard's data model; the override mechanism is already designed to support inline price edits in this context.
- **Flat-rate task billing** — a way to bill a task with no bleps and no materials (e.g., a permit fee modeled as work, not as a Material). Current workaround: model as a Material row.
- **Partial-atom billing** — billing 4 of 10 hours from a blep (or 5 of 20 widgets from a material row). Current model is whole-atom only. The `InvoiceLineItemSource` table can be extended with a `quantity` column later if this becomes a real need.
