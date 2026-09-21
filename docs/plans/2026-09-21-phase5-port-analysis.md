# Phase 5 (outsourced-work POs + reconciliation + task-rate prompt) — port analysis

Analysis of `feature/fees` Phase 5 for porting onto the current branch (`feature/estimating`).
Sources: spec §7 of `feature/fees:docs/plans/2026-08-02-task-owned-money.md`; plan
`feature/fees:docs/plans/2026-08-04-task-owned-money-phase5-plan.md`; commits
09a1e920 (Task 1), 148a419c (fix), d500def1 (Task 2), add14122 (Task 3), a8efed8c (fix),
544a4449 (Task 4), f9218be8 (Task 5), 21c39b73 (final-review fix wave); doc section §10a of
`feature/fees:docs/designs/materials-inventory-and-purchasing.md`; and the current working tree.

**Headline: the merge-base of feature/fees and HEAD is c0317faa, and the ENTIRE PO surface
(apps/purchasing models/services, apps/api/purchasing, frontend PO components/pages,
apps/jobs/financials.py, apps/invoicing/claims.py) is byte-identical between the merge-base and
HEAD except ONE line in `LineItemForm.svelte`** (`categories.filter((c) => !c.is_fallback)` in
the AC dropdown). Phase 5's diffs therefore apply almost cleanly at the file level. The porting
work is (a) mechanical rebase, (b) excising Phase-4 subtask machinery (parent_task is now a
dormant, no-read-no-write field), and (c) re-deriving the *meaning* of the rate prompt against
agreement-skeleton invoicing and §3.6c create-time money overrides.

---

## 1. Schema

All in migration `apps/purchasing/migrations/0025_po_reconciliation_fields.py` (commit 09a1e920).
**The `0025` slot is FREE on the current branch** — HEAD's latest purchasing migration is
`0024_anchor_deliverables_latest.py`, same as fees' parent. The migration can port verbatim.

### PurchaseOrder (new fields — NONE exist on current branch)

```python
bill_total = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
vendor_invoice_ref = models.CharField(max_length=100, blank=True, default='')
reconciled = models.BooleanField(default=False)
reconciled_date = models.DateTimeField(null=True, blank=True)
```

Deliberately NOT part of the PO status lifecycle — `reconciled` is a plain boolean; the 5-state
status machine (draft/issued/partly_received/received_in_full/cancelled) is untouched.

Plus (not fields):
- `PurchaseOrderQuerySet` with `awaiting_reconciliation()` → `filter(status=STATUS_RECEIVED_IN_FULL, reconciled=False)`; `objects = PurchaseOrderQuerySet.as_manager()`.
- `@property is_awaiting_reconciliation` — instance mirror.
- `@property ordered_total` — sum of `total_amount` over `not invoice_only` lines (`po_total` untouched — includes all lines).
- `@property variance` — `bill_total − ordered_total`, `None` while `bill_total` unset.

### PurchaseOrderLineItem (new fields — NONE exist on current branch)

```python
final_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # null = "as ordered"
invoice_only = models.BooleanField(default=False)  # appended at reconcile; excluded from receiving
```

Plus a new `clean()` override enforcing the task-link rule (top-level + job-bearing — see §7 re
subtasks) layered on `BaseLineItem.clean()`'s pre-existing task/inventory_item exclusivity.

### Already on the current branch (no schema work needed)

- `PurchaseOrderLineItem.task` — `models.ForeignKey('jobs.Task', on_delete=models.PROTECT, null=True, blank=True)`
  at `apps/purchasing/models.py:280` (working tree). The "reserved FK" Phase 5 activates. The
  current `apps/api/purchasing/views.py:137-138` still STRIPS `task` on line create
  (`data.pop('task', None)` — "reserved field; ignored by this feature"); Phase 5's Task 2
  removed that strip.
- The retired Bill/BillLineItem/BillPayment schema stubs (also carry a `task` FK) — untouched by
  Phase 5, stay parked.
- `InvoiceClaimService` (`apps/invoicing/claims.py`) with `is_invoiced(source_type, source_pk)` — exists, same signature.
- `LineItemService.normalize_fk_kwargs` (`apps/core/services.py:910`) and
  `delete_line_item_with_renumber` — both exist.

## 2. Backend services

### `PurchaseOrderService.reconcile(po_id, bill_total=None, vendor_invoice_ref='', line_finals=None, appended_lines=None)`
(`feature/fees:apps/purchasing/services.py`, ~line 70; built in 09a1e920, REPLACE semantics in
148a419c, append-only mirror + rate-prompt support in d500def1, input hardening in 21c39b73)

- **Allowed once past `draft`** — issued, partly_received, received_in_full, **and cancelled**
  (a vendor bill can land for a partial shipment). Draft rejected:
  `'Cannot reconcile a purchase order before it has been issued.'` NOT gated on receiving state
  (the awaiting nudge is downstream, not a precondition).
- **Editable, not a lifecycle lock** — re-reconcile overwrites; `reconciled=True`,
  `reconciled_date=now()` (re)set every call.
- **Input coercion up front** (21c39b73): non-numeric `bill_total`/`line_finals` values and
  non-int appended `line_item_id`s → field-shaped `ValidationError` (never 500).
- **`line_finals` = {line_item_id: Decimal} — REPLACE, not merge** (148a419c): every ordered
  (`not invoice_only`) line NOT keyed in this call has `final_price` cleared to `None`, even if a
  prior call set it. Every key must belong to this PO (all-or-nothing validation before the
  `transaction.atomic()` opens). `invoice_only` lines are never auto-swept — touched only if
  explicitly keyed.
- **`appended_lines` = append-only MIRROR** (d500def1): each dict is whitelisted to
  `APPENDED_LINE_FIELDS = frozenset({'description','qty','units','price','accounting_category','task'})`
  plus optional `line_item_id` (`invoice_only` is always set server-side; caller-supplied
  `invoice_only` — or `qty_received`, `line_number`, etc. — rejected as smuggling, 21c39b73).
  With `line_item_id` → in-place update of that existing invoice_only line; without → create new
  with `invoice_only=True`. Any existing invoice_only line NOT re-sent is DELETED via
  `LineItemService.delete_line_item_with_renumber` (repo law). Every write goes through
  `full_clean()`/`save()` so task-link validation applies to appended lines too.
- Finally sets the four PO-level fields, `full_clean()`, `save()` — all inside one transaction.

### Receiving-flow exclusions (09a1e920, 21c39b73)

- `PurchaseOrderReceivingService._update_po_status` and `receive_all` exclude `invoice_only`
  lines from receiving-completeness; direct receiving against an invoice_only line is rejected.
- `cancel_line_item` rejects invoice_only lines (21c39b73 — "cancel remaining qty" is meaningless).

### `PurchaseOrderService._default_markup_percent()` → `(Decimal|None, found: bool)`

Reads `Configuration['default_material_markup_percent']` — verified on fees (by grep, documented
in the docstring) to be the codebase's ONE generic cost→sell markup config (also used by
`MaterialService.establish_reverse_markup` and InventoryItem lot pricing). Missing/unparseable →
`(None, False)`. NOTE: distinct from the current branch's
`apps/inventory/services.py::_default_markup_percent` which returns `Decimal('0')` on missing —
the PO version's `(None, False)` shape is what drives the `markup_applied` honesty flag.

### `PurchaseOrderService.compute_rate_prompts(po)` → `(prompts, markup_applied)`

**Pure read, never mutates.** Called only by the reconcile API action after a successful
reconcile.
- **Qualifying line rule**: `final_price` non-null AND `task` set AND
  `not InvoiceClaimService.is_invoiced(InvoiceLineItemSource.SOURCE_TASK, task.pk)`. A line
  missing any of the three is silently skipped.
- `suggested_rate = (final_price × (1 + markup/100)).quantize(0.01)` when the config exists;
  bare `final_price` with `markup_applied=False` otherwise.
- Each prompt: `{'task_id', 'task_name', 'current_rate' (= task.rate read directly), 'suggested_rate'}`.
- **Accept** = the CLIENT issues `PATCH /api/jobs/{job_id}/tasks/{task_id}/ {rate: suggested_rate}`
  — the existing money-gated task path (`TaskSerializer.MONEY_FIELDS`). **There is no accept
  endpoint.** Decline = purely local frontend state; nothing persisted; every reconcile
  recomputes prompts fresh.

### Job costing — `apps/jobs/financials.py::_linked_po_variances(job)` (544a4449)

Called from `compute_job_financials` (new key `linked_po_variances`). Finds every PO with ≥1 line
linked to the job via `PurchaseOrderLineItem.task__job` OR via a `Material` the job owns
referencing the PO line (`Material.po_line_item`). Per PO returns
`{'po_id','po_number','status','reconciled','ordered_total','bill_total','variance','multi_job'}`,
money quantized to cents, `bill_total`/`variance` None pre-bill. `multi_job=True` when the PO
also touches another job through any line/Material. **No proration** — whole numbers on every
job touched. (API-only on fees; no frontend display — LATER entry, see §6/§9.)

### validate_data belt-checks (544a4449, 21c39b73)

- ERROR: invoice_only line has receiving data (`qty_received`/`received_by`/`received_date`,
  plus `qty_cancelled` after 21c39b73).
- WARN: `final_price` set but PO not reconciled (stale partial entry).
- ERROR: task link points at a subtask (belt for the model guard) — **loses meaning on current
  branch, see §7**.

## 3. API surface (d500def1)

- **`POST /api/purchase-orders/{id}/reconcile/`** — `CanManageFinancials` (default
  `get_permissions()` gate; deliberately not added to the viewset's IsAuthenticated-only action
  list, which on the CURRENT branch is `list/retrieve/history/notes/send_defaults/receive/
  receive_all/receipts/cancel_line_item/reverse_receipt` + GET line_items — identical structure,
  so the port needs zero permission plumbing). Body:
  `{bill_total, vendor_invoice_ref, line_finals: {line_item_id: number}, appended_lines: [...]}`.
  Keys of `line_finals` coerced to int; malformed shape → 400
  `{'line_finals': ['Must be an object keyed by line item id.']}`. Response: full
  `PurchaseOrderSerializer` payload **plus** `rate_prompts` and `markup_applied` (computed fresh,
  never persisted).
- **`GET /api/purchase-orders/?awaiting_reconciliation=true`** (`1`/`yes`, case-insensitive) —
  list filter via the queryset helper.
- **`PurchaseOrderSerializer`** adds `bill_total`, `vendor_invoice_ref`, `reconciled`,
  `reconciled_date` (all read-only — write path is the reconcile action only),
  `awaiting_reconciliation` (SerializerMethodField), `variance` (string, quantized, nullable).
- **`POLineItemSerializer`** adds `final_price`, `invoice_only` (both read-only —
  reconciliation-owned). `task` stays writable; the create-path strip
  (`data.pop('task', None)` in the viewset's line-create) is removed so `task` is writable on
  create as it already was on PATCH.
- No new permission classes; permission matrix pinned by tests (financials-only can reconcile;
  no-atom worker and manage-jobs-only user get 403).

## 4. Frontend (add14122, a8efed8c, 21c39b73)

All under `frontend/src/components/purchaseorders/` + `frontend/src/components/TaskLinkPicker.svelte`
+ `frontend/src/routes/purchaseorders/`.

- **`TaskLinkPicker.svelte`** (new, shared): cascading JobPicker → that job's tasks fetched via
  `GET /api/jobs/{id}/tasks/`, filtered client-side to `parent_task == null` (courtesy; server
  is backstop), `value` = task id or null. Edit-mode: resolves the job from
  `GET /api/tasks/{value}/` once. Uses existing `JobPicker.svelte` (present on current branch).
- **`LineItemForm.svelte`**: adds an optional "Task Link" `TaskLinkPicker` row in Manual mode,
  independent of the material `jobId` (a line can carry a Material for job A while attributing
  cost to a task on job B); sends `task` in the create payload when set. (Current-branch file
  has the one-line `is_fallback` AC-filter divergence — trivial merge.)
- **`ReconciliationSection.svelte`** (new, ~290 lines): rendered on PO detail for any non-draft
  PO. For `canManageFinancials`: a form with Bill Total, Vendor Invoice Ref, a per-ordered-line
  table with a "Final Price" input (placeholder "as ordered"), an Invoice-Only Lines table
  (description/qty/units/price/AC/TaskLinkPicker/Remove) + "Add Invoice-Only Line", variance
  display, and Save. **Mount-seeds from `po` and resends the COMPLETE picture every save**
  (mirrors backend REPLACE/mirror semantics — an unedited save is an identity op). Removing a
  PERSISTED invoice-only row shows an honest notice ("N recorded lines will be deleted when you
  save") with one-click re-add (a8efed8c) — no confirm() (repo doctrine: reversible pre-save).
  Non-financials users get a read-only summary once reconciled.
- **`RatePromptDialog.svelte`** (new): modal table of prompts (Task / Current Rate / Suggested
  Rate / Accept·Decline per row, rows resolve independently with per-row retry-on-error). Accept
  does `GET /api/tasks/{id}/` (for the job id) then
  `PATCH /api/jobs/{job.id}/tasks/{task_id}/ {rate: suggested_rate}`. Decline sets local state
  only. Shows "No markup configured — suggestion equals vendor cost" when
  `markupApplied === false` (21c39b73).
- **`PurchaseOrderDetailPage.svelte`**: `handleReconcile(payload)` → POST reconcile → reload →
  success toast (reads pre-reload `reconciled` for correct first-save wording, 21c39b73) → if
  `canManageFinancials && rate_prompts.length`, open RatePromptDialog. ReconciliationSection is
  wrapped in `{#key `${po.po_id}:${po.reconciled_date ?? ''}`}` — **load-bearing remount** so a
  freshly-appended invoice-only line picks up its server id (otherwise the next save
  delete-recreates it and the removal notice lies) (21c39b73). Errors triaged via
  `triageError` → field errors / form message / overlay.
- **`PurchaseOrderList.svelte`**: amber "Awaiting Reconciliation" badge column when
  `po.awaiting_reconciliation`.
- **`PurchaseOrderListPage.svelte`**: "Awaiting reconciliation only" checkbox → the list filter
  param.
- **`ReceiveItemsForm.svelte`**: excludes `invoice_only` lines from the receivable list (21c39b73).

Flow as a user story: add PO line (optionally task-linked) → issue → receive (existing flow) →
PO shows amber awaiting badge once received-in-full → financials user opens PO detail, fills
Bill Total/vendor ref/per-line finals, appends freight as invoice-only → Save → rate-prompt
modal for each clean final on an uninvoiced linked task → Accept updates the task's rate →
invoice later picks up the new rate.

Note: fees Phase 5 wired reconcile ONLY into the standalone `PurchaseOrderDetailPage` route —
NOT into `POPanel.svelte`/`PurchaseOrderDetail.svelte` (the job-side panel, which exists on both
branches). Port can keep that scope or extend; keeping is the faithful option.

## 5. Config keys

**None added.** Phase 5 deliberately REUSES `default_material_markup_percent` (already exists on
the current branch — read by `apps/inventory/services.py`; documented in data-constraints §1.1)
as the generic cost→sell markup. The absent-key case is first-class (`markup_applied=False`,
suggestion = bare cost, UI note). The plan explicitly said "if no markup config exists, offer
final-cost-derived suggestion without markup and note it" — built exactly so.

## 6. Tests + e2e shipped on fees

- **`tests/test_po_reconciliation.py`** (~880 lines): happy path (fields/date/status untouched);
  re-reconcile overwrite; REPLACE semantics (omitted line reverts, empty line_finals clears all,
  untargeted invoice_only untouched); pre-issue rejected / issued ok / cancelled ok;
  line_finals ownership + no-partial-apply; invoice_only receiving-completeness exclusion +
  direct-receive rejection + status-recompute immunity; task-link validation (top-level ok,
  subtask rejected create+update, optional, multi-job); awaiting-reconciliation membership
  matrix (all 5 statuses × reconciled, incl. re-awaiting after receiving reversal);
  appended-lines drop/replace/keep + renumbering + cross-PO id rejection + ordinary-line-id
  rejection; whitelist smuggling (qty_received, line_number, invoice_only); malformed-input
  400s; cancel_line_item invoice_only guard.
- **`tests/test_api_po_reconciliation.py`** (~440 lines): endpoint happy path; rate_prompts +
  markup_applied in response; no prompt without final_price; appended round-trip via API; 404;
  field-shaped 400s (before-issue, bad line_finals shape, malformed values); permission matrix
  (financials yes; bare worker no; manage-jobs-only no); serializer field exposure; variance
  null pre-bill; variance excludes invoice_only; list filter; task-link via line create/PATCH
  (subtask 400s field-shaped).
- **`tests/test_job_financials.py`** additions (~155 lines): linked-PO variance rollup —
  task-linked, material-linked, multi_job flag, quantization, empty case.
- **`tests/test_validate_data.py`** additions (~165 lines): the three belt-checks.
- **Vitest**: `frontend/tests/components/TaskLinkPicker.test.js`, and under
  `frontend/tests/components/purchaseorders/`: `RatePromptDialog.test.js`,
  `ReconciliationSection.test.js` (incl. persisted-removal notice), plus additions to
  `LineItemForm/PurchaseOrderDetailPage/PurchaseOrderList/PurchaseOrderListPage/ReceiveItemsForm`
  tests (remount-key behavior, markup note, badge, filter, invoice_only exclusion).
- **e2e**: `e2e/specs/purchasing/po-reconciliation.spec.js` (~280 lines) — ONE continuous
  test.step() flow: vendor/job/two flat tasks backdrop → PO with task-linked lines → issue →
  receive-all → awaiting badge + list filter → reconcile (bill total, vendor ref, per-line
  final, invoice-only append, persisted-removal notice) → rate prompt (accept on one line,
  decline on the other — "cheapest arrangement" for both branches) → invoice wizard reads the
  updated task rate live. Persona `finjobs`. Includes a toast-dismissal helper (success overlay
  intercepts clicks on the rate-prompt modal). The `e2e/specs/purchasing/` directory does NOT
  exist on the current branch.
- **Docs shipped** (f9218be8): materials doc §10a (~270 lines, the authoritative behavioral
  reference — quoted extensively above), data-constraints field/validation entries,
  jobs-and-tasks + estimates-and-prices cross-refs, invoicing-and-expenses no-hard-block note,
  quickbooks-integration bills-stay-in-QBO + future pull-matcher note, `docs/ui-flows/Purchasing.md`
  (new, §1-§8 — also absent on current branch).

## 7. Dependency audit (what differs on the current branch)

| Dependency | fees-era assumption | Current branch reality | Verdict |
|---|---|---|---|
| **Phase 4 subtasks / parent_task** | Task-link must be TOP-LEVEL; `PurchaseOrderLineItem.clean()` reads `task.parent_task_id`; validate_data subtask belt-check; TaskLinkPicker filters `parent_task == null`; LATER item 2 (reparent guard) | Subtasks REMOVED (better-fees). `Task.parent_task` is dormant: model comment at `apps/jobs/models.py:328` says **"No code may read or write parent_task"**; `validate_data.check_no_parent_task` flags ANY non-NULL value | **Re-shape: DROP the top-level rule entirely.** The clean() parent-task branch, the validate_data subtask check, the picker filter, and both subtask tests would violate the no-read rule and guard a state that `check_no_parent_task` already forbids globally. Keep only the job-bearing defense-in-depth check (or drop clean() entirely and rely on FK non-null job). LATER item 2 (reparent guard) evaporates. |
| **Phase 2 freeform_kind (work/material/fee hand-line kinds)** | Spec §7 step 1-2: estimate "Work" hand-line or "outsourced X" ServiceItem crystallizes to a flat entered-qty task | Phase 2 rejected. Current authoring: unified Add-Line picker (§6.4 estimates doc) — catalog picks (ServiceItem/inventory) + hand service lines; `is_material` only (no freeform_kind, `apps/estimates/models.py:622,743`); acceptance crystallizes service lines via the checklist (§9a) incl. per-unit mint | **Survives with re-worded flow steps.** Phase 5's CODE has zero dependency on freeform_kind — it never touches estimate lines. Only the spec's narrative steps 1-2 need re-grounding: the sell-side task arrives via a hand service line / ServiceItem pick / Add Task with §3.6c money overrides. |
| **Old Fee model** | None — Phase 5 never touched Fee | Fee deleted wholesale | No impact. |
| **fees-era flat-task shape ("entered-qty, qty 1, typed sell rate")** | Task owns money: `qty_source`/`rate`/`unit_label`/`accounting_category`/`active_modifiers` | SAME model shape survived the re-land (`apps/jobs/models.py:355-375`; `TaskSerializer.MONEY_FIELDS` at `apps/api/tasks/serializers.py:155`). PLUS: `flat_fee` algorithm reintroduced 2026-08-16 in a NEW shape (§2.2a — scheme is pure behavior, rate locked 0; the ServiceItem carries the amount; `resolve_stamp` puts the amount INTO `Task.rate`, `qty_source=ENTERED_QTY`) | **Survives, and improves.** The rate prompt PATCHes `Task.rate` — a plain MONEY_FIELDS write, valid on any task incl. flat_fee-stamped ones (drift from provenance is by-design audit signal, §3.6a). A flat_fee ServiceItem "Outsourced powder coating" is now the natural sell-side authoring shape; §3.6c create-time `rate` override covers the no-ServiceItem case. LATER item 1's "derivation-mode parent shows $0.00" clause evaporates (no parents); its "ignores active_modifiers in current_rate" clause still holds — port should display `task.effective_rate()` or note the gap. |
| **Task PATCH accept path** | `PATCH /api/jobs/{job}/tasks/{id}/ {rate}` gated by `TaskSerializer.MONEY_FIELDS` (`CanManageJobOrPM` or `can_manage_financials`) | Identical mechanism exists; §3.6b: UI gating must use `can_write_money`, not `can_manage` | Ports as-is. Dialog's client-side `canManageFinancials` gate still correct (that atom always satisfies the server gate). |
| **`InvoiceClaimService.is_invoiced(SOURCE_TASK, pk)`** | Gates the prompt to uninvoiced tasks | Exists unchanged (`apps/invoicing/claims.py:48`); agreement-skeleton invoicing KEPT whole-atom claims (`InvoiceLineItemSource`, `unique_together`) | Ports as-is. Semantics still right: a task claimed by a live invoice shouldn't get a silent rate move. |
| **Invoicing ("wizard stays dumb, prices qty × current task rate")** | Rate update flows to the future invoice automatically | Agreement-skeleton: draft seeds from `compose_agreement` lines, BUT `seed_from_agreement`/`restore` immediately **re-derive a backed line's price from claimed atoms' actuals** (`InvoiceService._rederive_price_from_actuals`, `apps/invoicing/services.py:568`) = `task.compute_amount()` = actual_qty × effective_rate | **Survives — same effect, new mechanism.** An accepted rate update flows into any invoice seeded AFTER it (actuals basis) and shows as backing/actuals drift on one seeded before it. The port docs must restate the no-hard-block rule in agreement-skeleton terms ("reconciliation never blocks seeding; late variance is recorded margin"). |
| **entered_qty completion settle-up** | Flat task "NOT born complete"; completion gates billability | Current: completing an entered_qty task ALWAYS round-trips the settle-up prompt and requires final total > 0 (§4.2) | **Compose-check.** An outsourced task completes when vendor work is received; whoever completes it enters qty (typically 1). No conflict, but the port spec should name this: the completer answers the qty prompt; money still never asked at completion (spec §7 rejected list). |
| **§3.6c create-time money overrides (2026-09-19)** | N/A (post-dates fees) | Add-Task POST accepts `rate`/`unit_label`/`accounting_category` overrides after stamp, money-gated | **Composes cleanly** — it's the authoring half of the outsourced flow (type the quoted sell price at task creation); the rate prompt is the later correction half. No interaction with reconcile code. |
| **`default_material_markup_percent`** | The one markup config | Still the one markup config (verified: only `apps/inventory/services.py` reads it) | Ports as-is. |
| **Job financials** | `compute_job_financials` returns 4 keys; Task 4 added the 5th | Current `apps/jobs/financials.py` identical to fees' parent (4 keys + `spend_breakdown`); `JobSerializer._financials` cache pattern intact | Ports as-is (trivial context drift only). |
| **validate_data** | fees added 3 PO checks | File heavily diverged (+298 lines vs merge-base: per-unit/bundling checks etc.) | Re-apply by hand (semantic port, minus the subtask check). |
| **Converter (nealsdata)** | Task 4 verified: converter emits POs but never the 6 new fields; defaults correct; no changes needed | Same converter lineage; must re-verify with `tests.test_neals_builders` per memory rule | Port the verification, expect no changes. |
| **PO viewset/serializers/frontend PO surface** | — | Byte-identical to fees' parent except 1 line | Ports nearly clean. |

## 8. Current-branch touchpoints (integration points TODAY)

- **PO lifecycle** (`docs/designs/materials-inventory-and-purchasing.md` §9-10, working tree):
  status machine draft→issued→partly_received⇄received_in_full, issued→cancelled;
  auto-derivation in `PurchaseOrderReceivingService._update_po_status` (settled =
  `qty_received + qty_cancelled >= qty`); receiving via `receive_items`/`receive_all`/
  `cancel_line_item`/`reverse_receipt`; `update_line_item` draft-only; deliberately NO billed
  state ("invoice-vs-PO reconciliation is bookkeeper work done in QBO" — §9 note the port doc
  must supersede). `PurchaseOrderLineItem.task` documented as "Reserved for a future 'service
  PO' feature; not currently used by any flow".
- **PO API** (`apps/api/purchasing/views.py`): `get_permissions()` — receiving actions are
  IsAuthenticated; everything else CanManageFinancials. Line-create still strips `task`
  (line 137-138). Queryset already `select_related`/`prefetch_related`s
  `purchaseorderlineitem_set__task__job` (line 44) — N+1 groundwork already present.
- **PO frontend**: `PurchaseOrderDetailPage/ListPage/FormPage/SendPage` routes;
  `LineItemForm/ReceiveItemsForm/MaterialSeverDialog/PurchaseOrderList/POPanel/
  PurchaseOrderDetail/PurchaseOrderForm` components; Vitest coverage in
  `frontend/tests/components/purchaseorders/`. All practically identical to what fees' Phase 5
  patched.
- **Money-side context the rate prompt composes with**: §3.6c create-time overrides (above);
  §3.6a client-side restamp (edit modal can re-pick `source_scheme` + send the whole money
  block — a rate-prompt Accept PATCHing bare `rate` leaves provenance alone, consistent);
  §3.6b `can_write_money` UI gating; flat_fee §2.2a; per-unit lines §9b + Tasks-page bundling
  (estimate lines from atom bundles — irrelevant to PO code but the docs' cross-refs land there
  now); drift badges open explanatory modals (recent spec commits) — a design-language neighbor
  for how the rate prompt should feel.
- **Outsourced sell-side today (interim practice)**: no dedicated flow; RM's resolved-shapes
  list (`estimates-and-prices.md:3888`) marks "Outsourced work (powder coating, waterjet) → PO
  reconciliation (Phase 5)" as the known missing piece; interim = ordinary entered-qty tasks
  (worker/PM enters qty; §3.6c lets a money-capable caller type the quoted sell rate at
  creation) or a flat_fee ServiceItem.

## 9. Port verdict per piece

| Component | Verdict |
|---|---|
| Migration 0025 + 6 fields | **Port as-is** (0025 slot free; same parent 0024). |
| `PurchaseOrderQuerySet.awaiting_reconciliation` / `is_awaiting_reconciliation` / `ordered_total` / `variance` | **Port as-is.** |
| `PurchaseOrderLineItem.clean()` task-link guard | **Re-shape: drop the parent_task/top-level branch** (violates the no-read-parent_task rule; guards an impossible state). Keep job-bearing check or drop clean() entirely — decide in spec; the mutual-exclusivity with `inventory_item` is pre-existing `BaseLineItem.clean()` and needs nothing. |
| `PurchaseOrderService.reconcile()` (+ whitelist, REPLACE, mirror, input coercion) | **Port as-is** (services.py context drift is trivial). |
| Receiving exclusions (invoice_only in `_update_po_status`/`receive_all`/direct-receive/`cancel_line_item`) | **Port as-is.** |
| `_default_markup_percent` / `compute_rate_prompts` | **Port with one re-shape**: consider `current_rate = task.effective_rate()` (modifiers-aware) instead of raw `task.rate` — fees' own LATER item 1; the derivation-mode half of that item is moot. Suggested-rate math unchanged. |
| Reconcile endpoint + serializer fields + list filter + task-strip removal | **Port as-is.** |
| `TaskLinkPicker.svelte` | **Re-shape (trim)**: drop the `parent_task == null` client filter (all tasks are top-level); rest as-is. |
| `LineItemForm` task-link row | **Port as-is** (merge around the is_fallback filter line). |
| `ReconciliationSection` + persisted-removal notice + `{#key}` remount | **Port as-is** (semantics are UI-of-record for backend REPLACE/mirror; keep the remount comment). |
| `RatePromptDialog` | **Port with re-shapes**: accept path unchanged (`PATCH rate`); ensure current_rate display matches whatever compute_rate_prompts sends; consider wording vs the current branch's drift-badge/modal design language. |
| Awaiting badge + list filter | **Port as-is.** |
| `ReceiveItemsForm` invoice_only exclusion | **Port as-is.** |
| `_linked_po_variances` + JobSerializer exposure | **Port as-is** (still API-only; carry the LATER entry, or the port spec commissions the job-page display). |
| validate_data checks | **Port 2 of 3** (invoice_only-receiving ERROR, stale-final WARN); **drop** the subtask-link ERROR (superseded by `check_no_parent_task`). |
| Backend tests | **Port with edits**: drop/replace subtask-link tests (`test_link_subtask_rejected_*`, `test_appended_reconcile_line_task_link_validated`'s subtask case, API twins); everything else re-usable nearly verbatim. |
| Vitest tests | **Port with trims** (TaskLinkPicker filter test). |
| e2e `po-reconciliation.spec.js` | **Re-shape**: flow survives whole, but rebuild against current personas/seed and the CURRENT invoice surface — the final step "invoice wizard reads the task's rate" becomes "seeded/restored backed line arrives on actuals basis reflecting the new rate" (agreement-skeleton seeding). Sell-side task setup should use the current authoring path (flat_fee ServiceItem or Add Task + §3.6c rate override). |
| Docs (§10a etc.) | **Re-write from fees' text**: port §10a into the current materials doc (replacing §9's "no billed state" note), data-constraints entries, invoicing no-hard-block note re-grounded in agreement-skeleton terms, QBO note, new ui-flows/Purchasing.md; update the §9 line-items table's `task` row. |
| Spec §7 narrative steps 1-2 (estimate → crystallize) | **Re-ground**: current authoring paths (unified picker / ServiceItem / Add Task overrides); no freeform_kind. |
| LATER carry-notes | Item 1 → half-fix in port (effective_rate) or carry; item 2 → **drop** (no reparenting exists); item 3 (manual line-POST doesn't strip caller-supplied `invoice_only`) → **fix in port** (cheap serializer read-only already covers API; the service-level hole is the note's point). |
| Phase-2 QBO Bill pull-matcher | Stays future (unbuilt on fees too). |

### Blockers

None hard. Two design decisions the port spec must make explicitly:
1. **Rate-prompt current_rate/suggested_rate semantics** vs modifiers (`effective_rate`) — fix
   now or carry the LATER note.
2. **What Accept means under agreement-skeleton invoicing** — updating `Task.rate` changes the
   actuals basis future seeded lines land on and creates visible actuals-vs-agreement drift on
   already-seeded lines; the spec should say this out loud (it's arguably better than the
   fees-era story, but it's a different story).
