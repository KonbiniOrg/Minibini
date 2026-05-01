# Code Review Findings — 2026-04-20

Review of the Minibini codebase for architectural cleanup, test coverage gaps, and duplication. No code changes made; this is a findings report to guide future work.

## Scope and method

- Surveyed all `apps/*/services.py` (7,412 lines total), all `apps/api/*/views.py` (2,978 lines), `apps/api/mixins.py` (313 lines), `apps/api/permissions.py` (17 lines), and `tests/` (217 test files).
- Spot-checked specific claims against current source before recording them here.
- Several findings below started as agent hypotheses that didn't survive verification — those are called out explicitly.

---

## 1. Architectural cleanup

### 1.1 DELETE endpoints returning 204 (CLAUDE.md flags as "fix opportunistically")

CLAUDE.md says *all* DELETE responses should return 200 with a JSON body because `frontend/src/lib/api.js` assumes every response has JSON. The real violators are `ModelViewSet` subclasses that never override `destroy()` — DRF's default returns 204 with an empty body.

**Viewsets currently returning 204** (no `destroy()` override):
- `apps/api/invoicing/views.py:12` — `InvoiceViewSet`
- `apps/api/estimates/views.py:12` — `EstimateViewSet`
- `apps/api/jobs/views.py:22` — `JobViewSet`
- `apps/api/worksheets/views.py:14` — `EstWorksheetViewSet`
- `apps/api/purchasing/views.py:367` — `BillViewSet`
- `apps/api/templates_config/views.py:20,82,105` — `WorkTemplateViewSet`, `TaskTemplateViewSet`, `AccountingCategoryViewSet`
- `apps/api/inventory/views.py:12` — `PriceListItemViewSet`

**Note (correction to first-pass review):** `RateSchemeViewSet` (`apps/api/rate_schemes/views.py:19`) and `BlepViewSet` (`apps/api/bleps/views.py:123`) return `Response({...})` *without* explicit status — DRF's `Response` defaults to 200, so these are already compliant. `MaterialViewSet` overrides to return 405 which is also fine.

**Suggested consolidation:** a tiny `JSONDestroyMixin` with a base `destroy()` that computes a default `{'message': '<Model> deleted.'}` payload and returns 200. Apply to all eight viewsets above.

### 1.2 Delete-confirmation pattern duplicated across three viewsets

Same two-phase flow implemented independently in:
- `apps/api/contacts/views.py:57–83` — `ContactViewSet.destroy`
- `apps/api/contacts/views.py:146–180` — `BusinessViewSet.destroy`
- `apps/api/reimbursements/views.py:60–74` — `ReimbursementViewSet.destroy`

Each one: check `request.query_params['confirm']`, compute an impact dict on first call, run the real delete on second call. Candidate for a `ConfirmDeleteMixin` with a subclass-overridable `get_deletion_impact(obj) -> dict` hook.

### 1.3 `apps/jobs/signals.py` is effectively empty

`apps/jobs/signals.py` has **1 line**. By contrast `apps/estimates/signals.py` is 124 lines with three receivers handling cross-model state changes (`estimate_status_changed_for_worksheet`, `estimate_status_changed_for_job`, `estimate_accepted`).

This is an inconsistency, not automatically a bug: Job status side-effects may well be handled in `apps/jobs/services.py` (~1,100 lines). Worth deciding which pattern the project commits to — services-only or service+signals — and documenting it in CLAUDE.md. The current split reads as historical drift.

### 1.4 CLAUDE.md stub list is stale

CLAUDE.md lists `/api/expenses/` as a stub. It isn't — `apps/api/expenses/views.py` is a 102-line ExpenseViewSet with a full CRUD implementation and is tested in `tests/test_api_expenses.py`. Update the doc, not the code.

`apps/api/stubs.py` itself only defines a factory (`stub_501`); actual stub registrations live in each app's `urls.py`. The doc claim "Stubs (not yet implemented): /api/auth/refresh/, /api/emails/send/, /api/shifts/, /api/expenses/, /api/time-tracking/" is partially wrong.

### 1.5 Validation logic leaking into viewsets

Two places where viewsets do work that belongs in the serializer or service layer:

- `apps/api/bleps/views.py:38–81` — `BlepViewSet.create` hand-parses `task`, `start_time`, `end_time`, `user`, validates they exist, parses ISO datetimes, then calls `BlepService.create_historical`. This is a serializer's job. `BlepSerializer` is set as `serializer_class` but bypassed for create.
- `apps/api/contacts/views.py:57–83, 146–180` — Both `ContactViewSet.destroy` and `BusinessViewSet.destroy` run direct `Job.objects.filter(...)` queries to compute the impact dict. The impact query belongs on the service, not the viewset.

### 1.6 Deprecated HTML views still live

CLAUDE.md says HTML views are "deprecated and will be removed." Still active:
- `apps/contacts/views.py:9–224` — full contact/business CRUD HTML forms, including the email-to-job session flow.
- `apps/estimates/views.py:88–665` — `estimate_list`, `estimate_detail`, template management.
- `apps/jobs/views.py:27–342` — `job_list`, `job_detail`, `job_create`, `job_edit`, material management.
- `apps/invoicing/views.py:9–39` — read-only plus `invoice_reorder_line_item` POST.

These overlap with Svelte SPA routes that already cover jobs and contacts. Worth a deliberate pass to either remove each HTML view or rewrite its Svelte equivalent; the current state is "both exist and can drift."

---

## 2. Duplication and generalization

### 2.1 `_validate_draft` repeated in every document service

Every document type re-implements the same pre-edit status check:
- `apps/invoicing/services.py:15–19` — named method `_validate_draft`
- `apps/estimates/services.py:72,130,146,163,180,194,207` — inline `if estimate.status != STATUS_DRAFT: raise ValidationError(...)`
- `apps/estimates/services.py:451–462` — separate `_validate_draft_worksheet`
- `apps/purchasing/services.py` — same pattern for PO and Bill

Candidate for a shared `DocumentService.ensure_editable(doc)` helper in `apps/core/services.py`.

### 2.2 `add_line_item` and `add_line_item_from_pli` duplicated 4×

Near-identical implementations:
- `apps/estimates/services.py:124–137` (add) / `201–223` (from PLI)
- `apps/invoicing/services.py:22–34` / `37–60`
- `apps/purchasing/services.py:172–191` / `194–271` (PO) and `768–780` / `783–806` (Bill)

All four: fetch parent, validate draft, normalize FK kwargs, create line item. The existing `LineItemService` in `apps/core/services.py:626` already knows how to reorder/renumber; it could host a `create_for_parent(parent, **kwargs)` method parameterized on the line-item model.

### 2.3 Line-item source serializers repeated

- `apps/api/estimates/serializers.py:6–24` — `EstimateLineItemSourceSerializer`
- `apps/api/invoicing/serializers.py:6–26` — `InvoiceLineItemSourceSerializer`

Identical field list (`source_id`, `source_type`, `source_pk`, `description`, `computed_amount`); only `get_description` differs. Extract `BaseLineItemSourceSerializer` with an abstract `get_description` hook.

### 2.4 FK display boilerplate in serializers

Pattern repeated throughout `apps/api/*/serializers.py`:
```python
business_name = serializers.CharField(source='business.business_name', read_only=True)
```
A small helper (`fk_display(source)`) would make these consistent and searchable.

### 2.5 Line-item services bypass `LineItemService` for renumbering

Each service reimplements reorder logic (`apps/estimates/services.py:157`, `apps/invoicing/services.py:79`, `apps/purchasing/services.py:319`) rather than delegating to `LineItemService` in `apps/core/services.py:626`. The shared service already exists but isn't always used.

---

## 3. Test coverage gaps

### 3.1 Critical (money, auth, multi-user)

- **QBO OAuth failure paths.** `apps/qbo/services.py:46–53` handles token refresh; no test exercises `AuthClient.refresh()` raising. A revoked or expired refresh token would fail silently during invoice sync. Add a test that mocks `AuthClient.refresh` to raise `OAuth2Error` and asserts the sync log captures the error without corrupting DB state.

- **`TaskLifecycleService.start_work(action='takeover')`** at `apps/jobs/services.py:576–633` closes other users' bleps. I could not find a test asserting that after a takeover exactly one open blep remains and the prior user's closed blep has the correct `end_time`. This directly affects payroll/billing attribution.

- **Two-phase delete confirmation.** The `?confirm=true` flow has no end-to-end test on `ContactViewSet`, `BusinessViewSet`, or `ReimbursementViewSet`. A regression that silently drops the `confirm` check would allow accidental cascade deletes with no UX warning.

### 3.2 Moderate

- **Permission denial (authenticated-but-missing-atom) for Job actions.** `tests/test_api_jobs.py` covers `copy_from_worksheet` permission denial at ~line 470, but `add_from_template` and `populate_from_estimate` have only happy-path tests. Add 403 checks for an authenticated user without `can_manage_jobs`.

- **Deep estimate revision chains + atom carry-over.** `apps/estimates/signals.py:117–123` fires `carry_over_for_estimate` on accept. Revision chains (e1 → e2 → e3) aren't tested; duplication or loss of atoms would silently skew invoices.

- **Tax calculation across all BaseLineItem subclasses.** `TaxCalculationService` is called from `InvoiceGroupingService` but I didn't find a unit test that runs it against each concrete subclass (Estimate, Invoice, PO, Bill) × each tax-category configuration. QBO sync correctness depends on this.

### 3.3 Minor

- **No frontend test infrastructure.** `frontend/package.json` has no `test` script and no Vitest/Jest config. Svelte components, stores (`auth.js`, `viewMode.js`), and `lib/api.js` are entirely uncovered. Even a minimal Vitest setup with one component and one `api.js` test would protect the CSRF/auth flow.

- **Task parent/child deletion.** No test for what happens to child tasks when a parent `Task` is deleted. `apps/jobs/models.py` defines `parent_task` as a FK; behavior depends on the `on_delete` setting (CASCADE vs SET_NULL). Worth a direct test.

- **Signal handlers under concurrent writes.** The estimate→job status signals (`apps/estimates/signals.py:36–114`) don't acquire row locks. Two estimates accepted in rapid succession on the same job could produce duplicate HistoryEntry rows. A test using `transaction.atomic()` + `select_for_update` assertions would catch regressions here.

---

## 4. Suggested order of attack

If someone picks this up, rough ROI order:

1. **204→200 destroy mixin** — 8 viewsets, mechanical change, prevents a class of Svelte bugs.
2. **Update CLAUDE.md stub list** — 5-minute doc fix; currently misleads new contributors.
3. **Shared `ensure_editable(doc)` helper** — touches 10+ call sites but makes the status-gate policy explicit.
4. **BaseLineItemCRUDService** — larger refactor (4 services, many tests to re-green) but removes the biggest duplicate block in the codebase.
5. **Frontend test harness** — one-time setup, unlocks future work.
6. **HTML view decommission** — do one app at a time (contacts first; it's already fully covered by Svelte).

Nothing here is urgent — the codebase is in good enough shape that all of these are "tidy up while the code is fresh in your head" items, not fires.
