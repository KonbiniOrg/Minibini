# Deliverables and Shipments — Design

A new app, `apps/deliverables/`, that tracks two related things:

1. **Deliverables** — the list of finished items a customer is buying on a Job. Distinct from estimate line items (which include billable inputs like setup, jigs, materials). Carries description, quantity, and units; no price.
2. **Shipments** — discrete fulfillment events. Each Shipment references one or more Deliverables and carries the quantity going out in that event. Multiple Shipments per Job support phased delivery / backorders.

The printed "packing list" is not a model — it is the rendered view of a Shipment with context from the Deliverables list and prior Shipments.

Change orders, which would let a customer-approved amendment modify the Deliverables list after the estimate is accepted, are **out of scope for this work session**. Design notes for that future work are captured in §11.

---

## 1. Goals and non-goals

**Goals**

- Capture the "what is the customer actually buying" list as first-class data on a Job.
- Render that list on customer-facing estimate documents alongside the line items.
- Block the customer-facing estimate from being sent unless the list is non-empty.
- Lock the list at estimate acceptance so the agreed-upon scope is stable.
- Support phased fulfillment via Shipments; show ordered / shipped / remaining per Deliverable.
- Provide a printable per-shipment packing list.

**Non-goals**

- Change orders — full design deferred (see §11).
- Server-side PDF generation for the packing list — use the SPA's printable HTML + browser Print-to-PDF for now.
- Coupling Shipment state to the Job status machine. Shipments are independent of `work_complete` / `completed`.
- Versioning the Deliverables list. The list is amended in place; there is no history.
- Linking Deliverable rows to `PriceListItem`, `Material`, `Task`, or any other catalog/atom. Rows are freeform typed text.

---

## 2. Data model

All three models live in `apps/deliverables/models.py`. None are decorated with `@history`.

### 2.1 `Deliverable`

One row per finished item the customer is buying.

| Field | Type | Notes |
|---|---|---|
| `id` | AutoField PK | |
| `job` | FK Job (CASCADE) | `related_name='deliverables'` |
| `description` | TextField | Freeform |
| `qty_ordered` | DecimalField(10, 2) | Matches `BaseLineItem.quantity` precision |
| `units` | CharField(50) | Drawn from `Configuration['units_list']` |
| `sort_order` | PositiveIntegerField | Auto-assigned to next slot on save when unset (mirrors `Task.save`) |
| `created_at`, `updated_at` | Timestamps | |

- `db_table = 'deliverables'`.
- Default ordering: `['sort_order']`.
- The list is editable only when `DeliverableService.is_editable(job)` returns `True`. See §3.
- Deletion calls `DeliverableService.delete`, which renumbers surviving siblings (same idea as `LineItemService.delete_line_item_with_renumber`).

### 2.2 `Shipment`

One row per fulfillment event for a Job. Multiple Shipments per Job.

| Field | Type | Notes |
|---|---|---|
| `id` | AutoField PK | |
| `job` | FK Job (CASCADE) | `related_name='shipments'` |
| `sequence` | PositiveIntegerField | Per-Job counter, auto-assigned on save. UI displays "Shipment #1, #2, …" |
| `status` | CharField — `prepared` / `picked_up` | Default `prepared` |
| `prepared_date` | DateTimeField | `default=timezone.now` on create |
| `picked_up_date` | DateTimeField, nullable | Set by `ShipmentService.mark_picked_up` |
| `notes` | TextField, blank | Optional |
| `created_at`, `updated_at` | Timestamps | |

- `db_table = 'shipments'`.
- `unique_together = [('job', 'sequence')]`.
- Default ordering: `['sequence']`.
- Status machine: `prepared → picked_up`. `picked_up` is terminal.
- Wired through `StatusTransitionMixin` (see §5).

### 2.3 `ShipmentItem`

One row per `(shipment, deliverable)` pair contributing to a shipment.

| Field | Type | Notes |
|---|---|---|
| `id` | AutoField PK | |
| `shipment` | FK Shipment (CASCADE) | `related_name='items'` |
| `deliverable` | FK Deliverable (PROTECT) | Defense-in-depth; logically unreachable since Deliverables are locked once Shipments can exist |
| `qty` | DecimalField(10, 2) | This shipment's contribution; must be `> 0` |

- `db_table = 'shipment_items'`.
- `unique_together = [('shipment', 'deliverable')]` — one row per pair. Shipping the same Deliverable again means creating another Shipment.
- Default ordering follows the parent Deliverable's `sort_order`.

### 2.4 Computed (not stored)

For each `Deliverable`, `DeliverableService.compute_fulfillment(deliverable)` returns:

```python
{
    'qty_ordered': Decimal,                  # = deliverable.qty_ordered
    'qty_picked_up': Decimal,                # sum across shipments with status='picked_up'
    'qty_prepped': Decimal,                  # sum across shipments with status='prepared'
    'qty_remaining': Decimal,                # qty_ordered - qty_picked_up - qty_prepped
}
```

These fields appear on the Deliverable serializer.

### 2.5 Validation rules

- `ShipmentItem.qty > 0`.
- `ShipmentItem.qty` cannot exceed the deliverable's `qty_remaining` at save time (computed on save, accounting for the row being added/updated itself).
- `ShipmentItem` cannot be created, updated, or deleted on a `Shipment` whose status is `picked_up`.
- `Deliverable` cannot be created, edited, or deleted while the D list is not editable (enforced in `DeliverableService`).
- `Shipment` cannot be created unless the D list is locked (i.e., the Job has an `accepted` estimate). Enforced in `ShipmentService.create`.
- `Shipment` cannot be deleted unless its status is `prepared` and it has zero `ShipmentItem`s.

---

## 3. Editability state

The Deliverables list is editable based on the Job's estimate state. The state is **computed**, not stored:

- **Editable** — no estimate exists on the Job, OR the latest non-terminal estimate is in `draft`.
- **Not editable** — otherwise. Sub-reasons surfaced to the UI for messaging only:
  - `estimate_sent` — the latest active estimate is `open`. User unblock path: revise the estimate (which moves the latest active estimate back to `draft`).
  - `estimate_accepted` — any estimate on the Job is in `accepted`. No unblock path in this session (change orders deferred).

"Latest non-terminal estimate" means the Job's most recent estimate that is not `superseded` or `rejected`. There is at most one of these.

Service interface:

```python
DeliverableService.is_editable(job) -> bool
DeliverableService.editability_reason(job) -> 'estimate_sent' | 'estimate_accepted' | None
```

API surface: `GET /api/jobs/{id}/deliverables/editability/` returns `{editable: bool, reason: str | null}`.

---

## 4. Workflow integration

### 4.1 Estimate-send guard

The draft → open transition on `Estimate` must reject if the Job has no Deliverables.

Change site: `EstimateService.mark_open` (or whichever method on `EstimateService` performs the draft → open transition). Add a precondition:

```python
if not Deliverable.objects.filter(job=estimate.job).exists():
    raise ValidationError('Cannot send estimate: job has no deliverables.')
```

This is the only modification to existing code in `apps/estimates/`.

### 4.2 Customer-facing estimate document

The Deliverables list appears on the customer-facing estimate (alongside the line items). The current estimate-to-customer flow renders a PDF; the deliverables block is added to that render.

For this session: the SPA estimate view also renders the Deliverables list as a separate section. Server-side PDF rendering integration follows whatever pattern the existing estimate PDF uses.

### 4.3 Locking at estimate-acceptance

No new code is needed for the lock itself — the editability rule (§3) already returns `False` once any estimate on the Job is `accepted`. The lock is implicit.

### 4.4 Shipment creation gating

`ShipmentService.create` raises `ValidationError` if the Job has no `accepted` estimate.

### 4.5 Job status independence

Shipments do **not** affect the Job status machine. A Job can be `work_complete` with pending Shipments; a Job can be `completed` (via invoice paid) with pending Shipments. The Job's lifecycle is unchanged by this work.

---

## 5. Service layer

`apps/deliverables/services.py`.

### 5.1 `DeliverableService`

| Method | Purpose |
|---|---|
| `create(*, job_id, description, qty_ordered, units, sort_order=None) -> Deliverable` | Validates editable. Auto-assigns `sort_order` if not provided. |
| `update(*, deliverable, **fields) -> Deliverable` | Validates editable. Whitelist of updatable fields: `description`, `qty_ordered`, `units`, `sort_order`. |
| `delete(*, deliverable) -> None` | Validates editable. On success, renumbers surviving siblings. (PROTECT on `ShipmentItem.deliverable` is a defense-in-depth backstop; logically unreachable since Deliverables can't be deleted once Shipments are possible.) |
| `reorder(*, job, ordered_ids) -> list[Deliverable]` | Validates editable. Bulk reassign `sort_order`. |
| `is_editable(job) -> bool` | See §3. |
| `editability_reason(job) -> str \| None` | See §3. |
| `compute_fulfillment(deliverable) -> dict` | See §2.4. |

### 5.2 `ShipmentService`

| Method | Purpose |
|---|---|
| `create(*, job_id) -> Shipment` | Validates D list is locked (Job has an `accepted` estimate). Assigns next per-Job `sequence`. Status `prepared`, `prepared_date=now()`. |
| `update(*, shipment, **fields) -> Shipment` | Validates status is `prepared`. Updatable: `notes`. |
| `delete(*, shipment) -> None` | Validates status is `prepared` and `shipment.items.exists()` is false. |
| `mark_picked_up(*, shipment) -> Shipment` | `prepared → picked_up`, sets `picked_up_date=now()`. Wired through `StatusTransitionMixin`. |
| `add_item(*, shipment, deliverable_id, qty) -> ShipmentItem` | Validates status `prepared`, qty `> 0`, qty `<=` deliverable's current `qty_remaining`. |
| `update_item(*, item, qty) -> ShipmentItem` | Validates status `prepared`, qty `> 0`, qty within bounds (accounting for the row's own current value). |
| `remove_item(*, item) -> None` | Validates status `prepared`. |
| `packing_list_payload(shipment) -> dict` | See §7. |

All write methods wrap their work in `transaction.atomic()`. Quantity bound checks use `select_for_update()` on the parent `Deliverable` to avoid race conditions where two concurrent shipment edits each pass the bound check independently.

---

## 6. API surface

### 6.1 Deliverables (job-nested)

| Method + path | Permission | Notes |
|---|---|---|
| `GET /api/jobs/{id}/deliverables/` | `IsAuthenticated` | List for a job |
| `POST /api/jobs/{id}/deliverables/` | `CanManageJobs` | Create |
| `GET /api/jobs/{id}/deliverables/{did}/` | `IsAuthenticated` | Retrieve |
| `PATCH /api/jobs/{id}/deliverables/{did}/` | `CanManageJobs` | Update |
| `DELETE /api/jobs/{id}/deliverables/{did}/` | `CanManageJobs` | 200 + JSON body |
| `POST /api/jobs/{id}/deliverables/reorder/` | `CanManageJobs` | Bulk reorder, body `{ordered_ids: [...]}` |
| `GET /api/jobs/{id}/deliverables/editability/` | `IsAuthenticated` | `{editable: bool, reason: str \| null}` |

Serializer includes computed fields from `compute_fulfillment`: `qty_picked_up`, `qty_prepped`, `qty_remaining`.

### 6.2 Shipments

| Method + path | Permission | Notes |
|---|---|---|
| `GET /api/shipments/?job={id}` | `IsAuthenticated` | List, filterable by job |
| `POST /api/jobs/{id}/shipments/` | `IsAuthenticated` | Create |
| `GET /api/shipments/{sid}/` | `IsAuthenticated` | Retrieve |
| `PATCH /api/shipments/{sid}/` | `IsAuthenticated` | Update (notes only; status uses pick-up action) |
| `DELETE /api/shipments/{sid}/` | `IsAuthenticated` | 200 + JSON. Allowed when `prepared` and no items. |
| `POST /api/shipments/{sid}/pick-up/` | `IsAuthenticated` | Status transition `prepared → picked_up`. Wired via `StatusTransitionMixin`. |
| `GET /api/shipments/{sid}/items/` | `IsAuthenticated` | List items in a shipment |
| `POST /api/shipments/{sid}/items/` | `IsAuthenticated` | Add item, body `{deliverable_id, qty}` |
| `PATCH /api/shipments/{sid}/items/{iid}/` | `IsAuthenticated` | Update item qty |
| `DELETE /api/shipments/{sid}/items/{iid}/` | `IsAuthenticated` | 200 + JSON |
| `GET /api/shipments/{sid}/packing-list/` | `IsAuthenticated` | Rendering payload for the printable view |

Conventions followed:

- All DELETE responses return HTTP 200 with `{message: '...'}` per project rule.
- ViewSets use service classes for all writes (`perform_create`/`perform_update`/`perform_destroy` delegate).
- Quantity-bound violations on `add_item`/`update_item` return HTTP 400 with `{detail: 'Quantity exceeds remaining.'}`.

### 6.3 New viewsets and url wiring

New files:

- `apps/api/deliverables/` — `urls.py`, `views.py`, `serializers.py`
- `apps/api/deliverables/views.py` exposes:
  - `DeliverableViewSet` (job-nested, mounted under `/api/jobs/{id}/deliverables/`)
  - `ShipmentViewSet` (mounted at `/api/shipments/`, with `/api/jobs/{id}/shipments/` for creation)
  - `ShipmentItemViewSet` (nested under `/api/shipments/{sid}/items/`)

`apps/api/urls.py` includes the new app's URLs.

---

## 7. Packing list rendering

Two surfaces:

### 7.1 JSON payload — `GET /api/shipments/{sid}/packing-list/`

Returns:

```jsonc
{
  "shipment": {
    "id": 12,
    "sequence": 2,
    "status": "prepared",
    "prepared_date": "2026-05-14T10:00:00Z",
    "picked_up_date": null,
    "notes": ""
  },
  "job": {
    "id": 37,
    "job_number": "JOB-2026-0042",
    "name": "Stool set, walnut",
    "customer": "..."
  },
  "rows": [
    {
      "deliverable_id": 91,
      "description": "Assembled walnut stool",
      "units": "ea",
      "qty_ordered": "15.00",
      "qty_this_shipment": "5.00",
      "qty_previously_picked_up": "10.00",
      "qty_remaining_after_this_shipment": "0.00"
    }
  ]
}
```

`qty_previously_picked_up` only counts other shipments with status `picked_up`. `qty_remaining_after_this_shipment` assumes this shipment is picked up.

Rows are emitted in Deliverable `sort_order`, including Deliverables that aren't on this shipment (with `qty_this_shipment = 0`). This lets the printed packing list show the full ordered scope as context.

### 7.2 Printable SPA route — `#/shipments/:sid/print`

`PackingListPrint.svelte` consumes the JSON payload and renders a print-CSS-friendly page. The user uses the browser's native Print-to-PDF.

No server-side PDF generation in this session. If we later need to email packing lists directly, follow the pattern in `apps/invoicing/pdf.py`.

---

## 8. UI placement

### 8.1 Job Detail page

The current layout (`JobDetail.svelte`) is:

```
JobHeader
[ Description | History ]    (two-column flex row)
Accordion pillars: Worksheet | Estimate | Tasks | Invoice | Purchase Orders
```

Becomes:

```
JobHeader
[ Description | DELIVERABLES | History ]    (three-column flex row)
Accordion pillars: Worksheet | Estimate | Tasks | Invoice | Shipments | Purchase Orders
```

### 8.2 `DeliverablesSection.svelte`

Always-visible middle column of the flex row.

- Heading: "Deliverables" plus a state pill when not editable (`estimate sent` / `estimate accepted`)
- "Edit" link in the heading when editable, opens `DeliverablesEditModal.svelte`
- Compact table inside a scroll container: `#`, description, qty_ordered, units, qty_picked_up, qty_remaining
- Empty state varies by editability

### 8.3 `DeliverablesEditModal.svelte`

Single modal that owns the full editing experience.

- Lists all current Deliverables with inline edit controls
- "Add deliverable" appends a row
- Per-row delete button
- Per-row up/down arrows for reordering (mirrors `WorksheetTaskTable`)
- Save commits all changes; cancel discards

### 8.4 `ShipmentsPillar.svelte`

Read-only accordion pillar on Job View, between Invoice and Purchase Orders.

- Single matrix table, one row per Deliverable, one column per Shipment in sequence order
- Each shipment column header stacks: shipment number, status pill, date
- Cells show `qty` for that `(deliverable, shipment)` pair, blank if no item
- "Qty ordered" and "Qty remaining" columns flank the shipment columns
- A prominent **"Manage shipments"** link/button opens the click-through page; clicking elsewhere in the table does nothing

### 8.5 `JobShipmentsPage.svelte` — full editor

Route: `#/jobs/:jobId/shipments`.

- Same matrix table, full size, with editing
- Per-shipment column header has an actions menu: "Mark picked up", "Print packing list", "Delete shipment" (delete enabled only when `prepared` and column is empty)
- Cells in `prepared` columns: click to edit qty inline. Setting `0` removes the row.
- Cells in `picked_up` columns: read-only
- "Add shipment" button creates a new prepared column with no items
- Footer row: per-column qty totals

### 8.6 `PackingListPrint.svelte`

Route: `#/shipments/:sid/print`. Print-CSS-friendly rendering of the packing-list JSON payload.

### 8.7 Default-pillar rule update

`JobDetail.svelte` chooses an initial open pillar by "furthest along". Updated rule:

1. Job complete → Invoice
2. Has shipments with outstanding `qty_remaining` somewhere on the Job → Shipments
3. Has work → Tasks
4. Has accepted estimate but no tasks yet → Estimate
5. Has estimate sent or earlier → Estimate
6. Else → Worksheet

Deliverables doesn't appear in this rule because the section is always visible (it isn't a pillar).

---

## 9. Permissions summary

| Surface | Read | Write |
|---|---|---|
| Deliverables (list, retrieve, editability) | `IsAuthenticated` | — |
| Deliverables (create, update, delete, reorder) | — | `CanManageJobs` |
| Shipments (list, retrieve, packing-list) | `IsAuthenticated` | — |
| Shipments (create, update, delete, pick-up) | — | `IsAuthenticated` |
| ShipmentItems (list, retrieve) | `IsAuthenticated` | — |
| ShipmentItems (create, update, delete) | — | `IsAuthenticated` |

Rationale:

- Deliverables are a planning artifact — only job managers should be changing what we're committing to deliver. Reading is open to all authenticated users.
- Shipments are operational — any employee picking, packing, or marking goods picked up should be able to do so without elevated permissions. Mirrors how `Blep` writes are open to any authenticated user.

---

## 10. Tests

Required test coverage (in `tests/`):

- Deliverable CRUD: create / update / delete / reorder, all gated by editability state across the three sub-states (no estimate, draft estimate, sent estimate, accepted estimate).
- Estimate `mark_open` rejects when Deliverables are empty; allows when non-empty.
- Shipment create rejected when D list isn't locked; allowed when accepted estimate exists.
- ShipmentItem qty validation: rejects zero / negative / over-remaining; honors picked-up status (immutable).
- `mark_picked_up` transitions the shipment and sets `picked_up_date`; renders items immutable thereafter.
- `compute_fulfillment` returns correct values across mixed prepared / picked-up shipments.
- Packing list payload includes all Deliverables in `sort_order`, with `qty_previously_picked_up` only counting other picked-up shipments.
- Delete shipment allowed only when `prepared` and has no items.
- Permissions: Deliverable writes require `CanManageJobs`; Shipment / ShipmentItem writes only require `IsAuthenticated`.

Fixtures: extend `unit_test_data.json` with a sample Job + estimate + deliverables + shipments setup.

---

## 11. Change orders — deferred, design notes

Out of scope for this work session. Captured here so the next pass has a starting point.

A Change Order is a customer-approved post-acceptance amendment that may modify both:

- **Scope (Deliverables)** — adding new rows, modifying existing rows' qty / description / units, removing rows.
- **Billing** — adding line items (positive or negative price) that flow into the same atom pool as estimate line items.

Likely shape:

- New model `ChangeOrder` in a new `apps/change_orders/` app (or in `apps/deliverables/`). Estimate-shaped: number, status (`draft → open → accepted | rejected`), customer-approval gate, total, FK to Job, FK to parent Estimate.
- New model `ChangeOrderLineItem` — billing-side, similar to `EstimateLineItem`.
- New model `ChangeOrderDeliverableChange` — one row per delta action, with `action` in `{ADD, MODIFY, REMOVE}` plus a target `Deliverable` FK for modify/remove and new field values for add/modify.
- On `accepted`: apply the deltas to the Job's Deliverables list, create billing atoms, and lock the change order itself.

Hooks in the present design that anticipate this:

- `DeliverableService.is_editable` will need to learn about an "amendment in flight" state (probably another not-editable sub-reason like `change_order_open`).
- The Deliverables UI will gain a "Propose change order" link when the D list is `locked` and the user has `CanManageJobs`.
- The lifecycle of a `Shipment` is unaffected by change orders — Shipments continue to reference the live `Deliverable` rows. A change order that removes a Deliverable will be blocked by `PROTECT` from `ShipmentItem.deliverable` if any item references it; the UI must guide the user to first issue compensating shipments or use a different remediation path.

Until change orders ship, the current design has **no escape hatch for an accepted-estimate Deliverables list.** Mistakes will require either revising the estimate before acceptance or developer intervention. This is explicit and acceptable for the session.

---

## 12. Open questions

- **Three-column flex row on narrower viewports.** The Description / Deliverables / History row may wrap awkwardly on small screens. Existing Description+History row's responsive behavior is unchanged otherwise; verify the three-column layout reads well at typical widths. If it breaks, fall back to stacking Deliverables below the row.
- **Deliverable display in the customer-facing estimate PDF.** Confirm with the existing estimate PDF rendering pipeline (likely in `apps/estimates/`) where to insert the Deliverables block. This may require a small change to the estimate PDF generator.
- **Cascade on Job delete.** A Job delete cascades to its Deliverables, then to Shipments and ShipmentItems. Confirm the Job delete path handles this gracefully (no surprise from PROTECT on a Deliverable that has ShipmentItems — the cascade order of Shipment → ShipmentItem fires first, freeing the Deliverable for cascade).

---

## 13. Implementation notes for the plan writer

- New Django app `apps/deliverables/`. Single migration introducing all three models.
- New API app `apps/api/deliverables/` for views, serializers, urls.
- Modifications to existing code, kept minimal:
  - `apps/estimates/services.py` — `EstimateService.mark_open` adds the Deliverables-non-empty precondition.
  - `apps/api/urls.py` — include the new app's URLs.
  - `frontend/src/routes/jobs/JobDetailPage.svelte` — switch to three-column flex row, add `<DeliverablesSection>` and `<ShipmentsPillar>`.
  - `frontend/src/App.svelte` — register `#/jobs/:jobId/shipments` and `#/shipments/:sid/print` routes.
- New SPA components per §8.
- Fixtures + tests per §10.
