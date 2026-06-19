# Invoiced-atom Visibility + Freeze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a per-atom "Invoiced" link on the job overview and detail the sources on each line item, and guarantee an invoiced atom can never change its billed amount.

**Architecture:** One centralized predicate (`InvoiceClaimService`) answers "is this atom invoiced, and on which invoice." Freeze guards on the task/material write paths enforce immutability of amount-feeding fields once an atom is billable (task `complete`) or billed (material). The wizard gates billability by lifecycle (task `complete`, material `consumed`). Serializers expose an `invoice` field fed by a per-job claim map (no N+1). The frontend renders the indicator and a stacked per-source list.

**Tech Stack:** Django 5.2 + DRF (MySQL), Svelte 5 SPA (Vite), Django TestCase (`tests/`), Vitest (`frontend/tests/`).

## Global Constraints

- **Never write to the dev DB.** Tests use their own DB; never run `migrate`, `shell`, `loaddata`, or ORM writes against dev. Read-only SQL SELECT is OK for diagnostics.
- **TDD always:** failing test → verify it fails → minimal code → verify pass → commit.
- **Run tests singly, never in parallel** (`python manage.py test tests.test_x`); shared MySQL test DB deadlocks otherwise.
- Use model status constants, never string literals (`Task.STATUS_COMPLETE`, `Invoice.STATUS_CANCELLED`, `Material.CONSUMPTION_STATE_CONSUMED`).
- **Line item deletes** go through `LineItemService.delete_line_item_with_renumber` (not relevant here, but do not introduce direct line-item `.delete()`).
- All DELETE responses return 200 with JSON (not relevant here; no new DELETEs).
- Frontend: no CSS frameworks; links navigate (`<a use:link>` / `href="#/..."`), buttons act; semantic HTML.
- On completion, update `docs/designs/` docs listed at the end. `docs/plans/` is the disposable working dir.

**Source spec:** `docs/plans/2026-06-17-invoiced-atom-visibility-and-freeze-design.md`

---

## File Structure

**Backend — create:**
- `apps/invoicing/claims.py` — `InvoiceClaimService` (the centralized predicate + batch maps).

**Backend — modify:**
- `apps/expenses/services.py` — refactor `_assert_not_invoiced` onto `InvoiceClaimService`.
- `apps/jobs/services.py` — task freeze in `TaskService.update_task`; blep freeze in `BlepService.create_historical`.
- `apps/inventory/services.py` — material freeze in `update_pricing` and `unconsume`.
- `apps/api/inventory/views.py` — material freeze in `MaterialViewSet.partial_update` (freeform sell_price path).
- `apps/invoicing/services.py` — `get_source_pool` billability gates; add-atoms write-path guard (in `apps/core/wizard.py` via a hook).
- `apps/api/jobs/serializers.py` — build `claims_for_job` and pass via context to task/material serializers.
- `apps/api/tasks/serializers.py` — `invoice` field on `TaskSerializer`.
- `apps/api/inventory/serializers.py` — `invoice` field on `MaterialSerializer`.
- `apps/api/expenses/serializers.py` + `apps/api/expenses/views.py` — `invoice` field on `ExpenseSerializer` + context map.

**Frontend — modify:**
- `frontend/src/components/jobs/JobDetail.svelte` — "Invoiced" link on tasks, materials, loose expenses.
- `frontend/src/components/invoices/WizardSourcePool.svelte` + `WizardAtom` — greyed `not_billable` state.
- `frontend/src/components/LineItemTable.svelte` — stacked per-source list.

**Tests:**
- `tests/test_invoice_claims.py` (new), and additions to `tests/test_api_materials.py`, `tests/test_api_bleps.py`, `tests/test_api_jobs.py`, `tests/test_api_invoicing.py`, `tests/test_api_expenses.py`.
- `frontend/tests/JobDetail.invoiced.test.js`, `frontend/tests/LineItemTable.test.js`, `frontend/tests/WizardSourcePool.test.js` (new or extended).

---

## Task 1: `InvoiceClaimService` — centralized predicate + batch maps

**Files:**
- Create: `apps/invoicing/claims.py`
- Test: `tests/test_invoice_claims.py`

**Interfaces:**
- Produces:
  - `InvoiceClaimService.is_invoiced(source_type: str, source_pk: int) -> bool`
  - `InvoiceClaimService.claims_for_job(job) -> dict[tuple[str,int], dict]` where each value is `{'invoice_id': int, 'invoice_number': str}`
  - `InvoiceClaimService.claims_for_atoms(source_type: str, pks: list[int]) -> dict[tuple[str,int], dict]`
  - Constants reused: `InvoiceLineItemSource.SOURCE_TASK`, `SOURCE_MATERIAL`, `SOURCE_EXPENSE`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_invoice_claims.py
from decimal import Decimal
from tests.base import BaseTestCase
from apps.invoicing.claims import InvoiceClaimService
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource


class InvoiceClaimServiceTest(BaseTestCase):
    def _make_invoice_line_with_source(self, job, source_type, source_pk, status):
        inv = Invoice.objects.create(job=job, status=status)
        li = InvoiceLineItem.objects.create(
            invoice=inv, description='x', qty=Decimal('1'),
            units='none', price=Decimal('5.00'),
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=li, source_type=source_type, source_pk=source_pk,
        )
        return inv

    def test_is_invoiced_true_for_live_source(self):
        job = self.make_job()  # see note below
        self._make_invoice_line_with_source(
            job, InvoiceLineItemSource.SOURCE_TASK, 4242, Invoice.STATUS_DRAFT,
        )
        self.assertTrue(
            InvoiceClaimService.is_invoiced(InvoiceLineItemSource.SOURCE_TASK, 4242)
        )

    def test_is_invoiced_false_when_only_cancelled(self):
        job = self.make_job()
        self._make_invoice_line_with_source(
            job, InvoiceLineItemSource.SOURCE_TASK, 4243, Invoice.STATUS_CANCELLED,
        )
        self.assertFalse(
            InvoiceClaimService.is_invoiced(InvoiceLineItemSource.SOURCE_TASK, 4243)
        )

    def test_claims_for_job_keys_and_excludes_cancelled(self):
        job = self.make_job()
        self._make_invoice_line_with_source(
            job, InvoiceLineItemSource.SOURCE_MATERIAL, 11, Invoice.STATUS_DRAFT,
        )
        self._make_invoice_line_with_source(
            job, InvoiceLineItemSource.SOURCE_TASK, 22, Invoice.STATUS_CANCELLED,
        )
        claims = InvoiceClaimService.claims_for_job(job)
        self.assertIn((InvoiceLineItemSource.SOURCE_MATERIAL, 11), claims)
        self.assertNotIn((InvoiceLineItemSource.SOURCE_TASK, 22), claims)
        ref = claims[(InvoiceLineItemSource.SOURCE_MATERIAL, 11)]
        self.assertEqual(set(ref.keys()), {'invoice_id', 'invoice_number'})
```

> **Note on `self.make_job()`:** if `BaseTestCase` has no such helper, create a minimal Job inline using the project's existing job-creation test pattern (grep `tests/test_api_invoicing.py` for how invoices+jobs are built in setUp) and reuse that exact pattern. Do **not** invent fields.

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_invoice_claims -v 2`
Expected: FAIL with `ModuleNotFoundError: apps.invoicing.claims`.

- [ ] **Step 3: Write minimal implementation**

```python
# apps/invoicing/claims.py
from apps.invoicing.models import Invoice, InvoiceLineItemSource


class InvoiceClaimService:
    """Single source of truth for 'is this atom on a live (non-cancelled) invoice'."""

    @staticmethod
    def _live_sources():
        return (
            InvoiceLineItemSource.objects
            .exclude(invoice_line_item__invoice__status=Invoice.STATUS_CANCELLED)
        )

    @classmethod
    def is_invoiced(cls, source_type, source_pk):
        return cls._live_sources().filter(
            source_type=source_type, source_pk=source_pk,
        ).exists()

    @classmethod
    def _map(cls, queryset):
        result = {}
        for src in queryset.select_related('invoice_line_item__invoice'):
            inv = src.invoice_line_item.invoice
            result[(src.source_type, src.source_pk)] = {
                'invoice_id': inv.pk,
                'invoice_number': inv.invoice_number,
            }
        return result

    @classmethod
    def claims_for_job(cls, job):
        return cls._map(
            cls._live_sources().filter(invoice_line_item__invoice__job=job)
        )

    @classmethod
    def claims_for_atoms(cls, source_type, pks):
        if not pks:
            return {}
        return cls._map(
            cls._live_sources().filter(source_type=source_type, source_pk__in=list(pks))
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_invoice_claims -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Refactor `ExpenseService._assert_not_invoiced` onto the predicate**

In `apps/expenses/services.py`, replace the body of `_assert_not_invoiced` (currently `apps/expenses/services.py:137-159`) so the live-source query is delegated, preserving the expense-or-linked-material behavior:

```python
    @staticmethod
    def _assert_not_invoiced(expense):
        """Raise if the expense — or its linked material — is on a non-cancelled
        invoice. An expense is immutable while billed (remove it from the invoice
        first)."""
        from apps.invoicing.claims import InvoiceClaimService
        from apps.invoicing.models import InvoiceLineItemSource
        if InvoiceClaimService.is_invoiced(
            InvoiceLineItemSource.SOURCE_EXPENSE, expense.pk,
        ) or (
            expense.material_id and InvoiceClaimService.is_invoiced(
                InvoiceLineItemSource.SOURCE_MATERIAL, expense.material_id,
            )
        ):
            raise ValidationError(
                'Cannot edit an expense that is on an invoice; '
                'remove it from the invoice first.'
            )
```

- [ ] **Step 6: Run the expense suite to verify the refactor is behavior-preserving**

Run: `python manage.py test tests.test_api_expenses -v 2`
Expected: PASS (no regressions).

- [ ] **Step 7: Commit**

```bash
git add apps/invoicing/claims.py tests/test_invoice_claims.py apps/expenses/services.py
git commit -m "feat(invoicing): centralize is-invoiced predicate in InvoiceClaimService

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Task freeze on `complete` (field edits)

**Files:**
- Modify: `apps/jobs/services.py` (`TaskService.update_task`, currently `apps/jobs/services.py:883-894`)
- Test: `tests/test_api_jobs.py` (or `tests/test_api_job_tasklist.py` — use whichever already builds tasks; check both, pick the one with task-edit coverage)

**Interfaces:**
- Consumes: nothing new.
- Produces: `update_task` raises `django.core.exceptions.ValidationError` when editing any field of a `complete` task except `sort_order`.

- [ ] **Step 1: Write the failing test**

```python
# in the task-editing test module (mirror its existing setUp for building a task)
from django.core.exceptions import ValidationError
from apps.jobs.models import Task
from apps.jobs.services import TaskService

def test_update_task_rejects_edit_on_complete_task(self):
    task = self._make_task()                 # reuse the module's existing helper
    task.status = Task.STATUS_COMPLETE
    task.save(update_fields=['status'])
    with self.assertRaises(ValidationError):
        TaskService.update_task(task.pk, name='renamed')

def test_update_task_allows_sort_order_on_complete_task(self):
    task = self._make_task()
    task.status = Task.STATUS_COMPLETE
    task.save(update_fields=['status'])
    # sort_order is cosmetic; must remain editable
    TaskService.update_task(task.pk, sort_order=5)
    task.refresh_from_db()
    self.assertEqual(task.sort_order, 5)
```

> Reuse the existing task-builder in that test module (grep for `Task.objects.create(` or `create_direct` in the file). Do not invent task fields.

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_jobs -v 2` (adjust module)
Expected: FAIL — first test does not raise; edit succeeds.

- [ ] **Step 3: Write minimal implementation**

Modify `TaskService.update_task` (`apps/jobs/services.py:883`):

```python
    @staticmethod
    def update_task(pk, **kwargs):
        """Update an existing Task by PK."""
        try:
            task = Task.objects.get(pk=pk)
        except Task.DoesNotExist:
            raise NotFoundError(f'Task {pk} not found')
        _assert_job_not_on_hold(task.job, 'edit this task')
        # A complete task is terminal and frozen: its work and billing inputs are
        # settled. sort_order is cosmetic (list position) and stays editable so a
        # list containing a complete task can still be reordered.
        if task.status == Task.STATUS_COMPLETE and set(kwargs) - {'sort_order'}:
            raise ValidationError(
                'Cannot edit a complete task. Its work and billing are settled; '
                'corrections belong on the invoice.'
            )
        for field, value in kwargs.items():
            setattr(task, field, value)
        task.full_clean()
        task.save()
        return task
```

> Confirm `ValidationError` is imported in this module (it is used elsewhere, e.g. `apps/jobs/services.py:42`). If not, add `from django.core.exceptions import ValidationError`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_jobs -v 2`
Expected: PASS. Then run the broader task suite to catch fixtures that edit completed tasks:
Run: `python manage.py test tests.test_api_job_tasklist tests.test_api_jobs -v 2`
Expected: PASS (fix any test that legitimately edited a complete task by adjusting that test's setup, not by weakening the guard).

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services.py tests/test_api_jobs.py
git commit -m "feat(jobs): freeze a complete task's fields (except sort_order)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Blep freeze — no historical bleps on a `complete` task

**Files:**
- Modify: `apps/jobs/services.py` (`BlepService.create_historical`, `apps/jobs/services.py:246`)
- Test: `tests/test_api_bleps.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `BlepService.create_historical(...)` raises `ValidationError` when `task.status == Task.STATUS_COMPLETE`. (The live `start_work` path already rejects non-pending/in-progress tasks at `apps/jobs/services.py:1168` — no change there.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_bleps.py — reuse the module's user/task/shift setup
from django.core.exceptions import ValidationError
from apps.jobs.models import Task
from apps.jobs.services import BlepService

def test_create_historical_rejects_complete_task(self):
    task = self._make_task_with_open_window()   # reuse existing helper/setup
    task.status = Task.STATUS_COMPLETE
    task.save(update_fields=['status'])
    start, end = self._recent_interval()        # reuse existing time helpers
    with self.assertRaises(ValidationError):
        BlepService.create_historical(
            actor=self.user, task=task, start_time=start, end_time=end,
        )
```

> Grep `tests/test_api_bleps.py` for how it currently builds a task + a covering shift and reuse those helpers verbatim; a blep requires an enclosing shift (`apps/jobs/services.py:286`).

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_bleps -v 2`
Expected: FAIL — blep is created on the complete task.

- [ ] **Step 3: Write minimal implementation**

In `BlepService.create_historical`, add the guard immediately after the existing job-status assertion (`apps/jobs/services.py:266-271`):

```python
        if task.status == Task.STATUS_COMPLETE:
            raise ValidationError(
                "Cannot log time on a complete task. Create a new task for "
                "additional work."
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_bleps -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services.py tests/test_api_bleps.py
git commit -m "feat(jobs): reject historical bleps on a complete task

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Material freeze — sell_price + unconsume on an invoiced material

**Files:**
- Modify: `apps/inventory/services.py` (`update_pricing` `:564`, `unconsume` `:677`)
- Modify: `apps/api/inventory/views.py` (`MaterialViewSet.partial_update` `:123`, freeform branch)
- Test: `tests/test_api_materials.py`

**Interfaces:**
- Consumes: `InvoiceClaimService.is_invoiced` (Task 1).
- Produces:
  - `MaterialService.update_pricing(...)` raises `ValidationError` if the material is invoiced and `sell_price` would change.
  - `MaterialService.unconsume(material)` raises `ValidationError` if the material is invoiced.
  - `PATCH /api/materials/{id}/` with `sell_price` on an invoiced freeform material returns 400.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api_materials.py — reuse the module's material + invoice builders
from decimal import Decimal
from django.core.exceptions import ValidationError
from apps.inventory.services import MaterialService
from apps.inventory.models import Material
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource

def _invoice_material(self, material):
    inv = Invoice.objects.create(job=material.job, status=Invoice.STATUS_DRAFT)
    li = InvoiceLineItem.objects.create(
        invoice=inv, description='m', qty=material.quantity,
        units='none', price=material.sell_price,
    )
    InvoiceLineItemSource.objects.create(
        invoice_line_item=li,
        source_type=InvoiceLineItemSource.SOURCE_MATERIAL,
        source_pk=material.pk,
    )

def test_update_pricing_blocks_sell_price_when_invoiced(self):
    mat = self._make_consumed_material()        # reuse existing helper
    self._invoice_material(mat)
    with self.assertRaises(ValidationError):
        MaterialService.update_pricing(mat, sell_price=Decimal('99.00'))

def test_unconsume_blocked_when_invoiced(self):
    mat = self._make_consumed_material()
    self._invoice_material(mat)
    with self.assertRaises(ValidationError):
        MaterialService.unconsume(mat)
```

> Reuse the module's existing helpers for building a consumed material (grep `consume(` / `CONSUMPTION_STATE_CONSUMED` in the file). If none exists, build one with `MaterialService.create_on_job(...)` then `MaterialService.consume(...)` using the same args the module already uses.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_api_materials -v 2`
Expected: FAIL — pricing change and unconsume both succeed.

- [ ] **Step 3: Implement the service guards**

In `apps/inventory/services.py`, add a small helper near the top of `MaterialService` and call it:

```python
    @staticmethod
    def _assert_not_invoiced(material):
        from apps.invoicing.claims import InvoiceClaimService
        from apps.invoicing.models import InvoiceLineItemSource
        if InvoiceClaimService.is_invoiced(
            InvoiceLineItemSource.SOURCE_MATERIAL, material.pk,
        ):
            raise ValidationError(
                'Cannot change a material that is on an invoice; '
                'remove it from the invoice first.'
            )
```

In `update_pricing` (`:564`), after the on-hold assertion and before mutating, guard only when `sell_price` actually changes:

```python
        from apps.jobs.services import _assert_job_not_on_hold
        _assert_job_not_on_hold(material.job, 'edit this material')
        if sell_price is not None and sell_price != material.sell_price:
            MaterialService._assert_not_invoiced(material)
```

In `unconsume` (`:677`), add the guard at the top (after the existing state check):

```python
        if material.consumption_state != Material.CONSUMPTION_STATE_CONSUMED:
            raise ValidationError(
                f'unconsume requires consumed state; got {material.consumption_state}'
            )
        MaterialService._assert_not_invoiced(material)
```

> Confirm `ValidationError` (`django.core.exceptions`) is imported in `apps/inventory/services.py`; it is used throughout, so it is. Do not add a duplicate import.

- [ ] **Step 4: Add the API-layer test for the freeform path**

```python
# tests/test_api_materials.py — uses the DRF test client the module already sets up
def test_patch_sell_price_blocked_on_invoiced_freeform_material(self):
    mat = self._make_consumed_freeform_material()   # no inventory_item
    self._invoice_material(mat)
    self.client.force_login(self.user)              # match module's auth pattern
    resp = self.client.patch(
        f'/api/materials/{mat.pk}/', {'sell_price': '77.00'},
        content_type='application/json',
    )
    self.assertEqual(resp.status_code, 400)
```

- [ ] **Step 5: Implement the view guard (freeform branch)**

In `apps/api/inventory/views.py` `partial_update` (`:123`), the PLI-linked pricing branch already routes through `update_pricing` (now guarded). Add the guard to the freeform/non-pricing branch before `serializer.save()` (`:159`):

```python
        # Freeform path or non-pricing fields: assert not on_hold before saving,
        # then fall through to the default serializer save.
        from apps.jobs.services import _assert_job_not_on_hold
        try:
            _assert_job_not_on_hold(instance.job, 'edit this material')
            if 'sell_price' in serializer.validated_data and (
                serializer.validated_data['sell_price'] != instance.sell_price
            ):
                from apps.inventory.services import MaterialService
                MaterialService._assert_not_invoiced(instance)
        except DjangoValidationError as e:
            detail = e.message_dict if hasattr(e, 'message_dict') else (
                e.message if hasattr(e, 'message') else str(e)
            )
            return Response({'detail': detail}, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(MaterialSerializer(instance).data)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python manage.py test tests.test_api_materials -v 2`
Expected: PASS. Then run the inventory + purchasing suites for regressions:
Run: `python manage.py test tests.test_api_inventory tests.test_api_purchasing -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/inventory/services.py apps/api/inventory/views.py tests/test_api_materials.py
git commit -m "feat(inventory): freeze sell_price and unconsume on an invoiced material

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Wizard billability gates (task complete, material consumed)

**Files:**
- Modify: `apps/invoicing/services.py` (`get_source_pool` `:437-488`; add per-type billability hook for the add-atoms write path)
- Modify: `apps/core/wizard.py` (`add_atoms_to_new_line_item` `:210`, `add_atoms_to_line_item` `:257` — call a billability hook)
- Test: `tests/test_api_invoicing.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `get_source_pool` atom dicts may carry `state == 'not_billable'` with `not_billable_reason` (`'task_incomplete'` or `'material_unconsumed'`).
  - `InvoiceWizardService` rejects adding a non-`complete` task or non-`consumed` material as an atom (raises `ValidationError`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api_invoicing.py — reuse the module's job/task/material/invoice setup
from apps.jobs.models import Task
from apps.inventory.models import Material
from apps.invoicing.services import InvoiceWizardService

def test_source_pool_marks_incomplete_task_not_billable(self):
    # task left in a non-complete status
    pool = InvoiceWizardService.get_source_pool(self.invoice)
    task_atom = self._find_atom(pool, 'task', self.incomplete_task.pk)
    self.assertEqual(task_atom['state'], 'not_billable')
    self.assertEqual(task_atom['not_billable_reason'], 'task_incomplete')

def test_source_pool_marks_pending_material_not_billable(self):
    pool = InvoiceWizardService.get_source_pool(self.invoice)
    mat_atom = self._find_atom(pool, 'material', self.pending_material.pk)
    self.assertEqual(mat_atom['state'], 'not_billable')
    self.assertEqual(mat_atom['not_billable_reason'], 'material_unconsumed')

def test_add_atoms_rejects_incomplete_task(self):
    from django.core.exceptions import ValidationError
    with self.assertRaises(ValidationError):
        InvoiceWizardService.add_atoms_to_new_line_item(
            self.invoice, [{'type': 'task', 'id': self.incomplete_task.pk}],
        )
```

> `_find_atom(pool, type, id)` is a small test helper: walk `pool['tasks'][*]['atoms']` (and the loose-materials group) for a matching `type`+`id`. Add it to the test module if not present. Reuse the module's existing invoice/task/material builders for `self.incomplete_task` / `self.pending_material`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_api_invoicing -v 2`
Expected: FAIL — atoms come back `available`; add succeeds.

- [ ] **Step 3: Implement billability in `get_source_pool`**

In `apps/invoicing/services.py`, define a `default_state` for a non-billable atom and apply it before the claim lookup. Replace the task-atom state assignment (`:448-449`) and the material-atom state assignment (`:469-470`) so a non-billable lifecycle wins over `available` (but a real claim still shows as claimed):

```python
        def billability(atom_type, instance):
            if atom_type == 'task' and instance.status != Task.STATUS_COMPLETE:
                return {'state': 'not_billable', 'not_billable_reason': 'task_incomplete',
                        'claiming_line_item_id': None, 'claiming_line_number': None,
                        'claiming_invoice_id': None, 'claiming_invoice_number': None}
            if atom_type == 'material' and (
                instance.consumption_state != Material.CONSUMPTION_STATE_CONSUMED
            ):
                return {'state': 'not_billable', 'not_billable_reason': 'material_unconsumed',
                        'claiming_line_item_id': None, 'claiming_line_number': None,
                        'claiming_invoice_id': None, 'claiming_invoice_number': None}
            return None
```

Then for the task atom:

```python
            key = (InvoiceLineItemSource.SOURCE_TASK, task.pk)
            state_info = claims.get(key) or billability('task', task) or default_state
```

and for each material atom (both the task-attached loop `:469` and the loose-materials loop):

```python
                key = (InvoiceLineItemSource.SOURCE_MATERIAL, mat.pk)
                state_info = claims.get(key) or billability('material', mat) or default_state
```

> `Task` and `Material` are already imported at the top of `get_source_pool` (`apps/invoicing/services.py:393-394`). Add `'not_billable_reason': None` to the shared `default_state` dict (`:429-435`) so every atom carries the key uniformly.

- [ ] **Step 4: Implement the add-atoms write guard**

Add a billability hook to the wizard base and override it for invoices. In `apps/core/wizard.py`, in both `add_atoms_to_new_line_item` (after `instances = [...]`, `:215`) and `add_atoms_to_line_item` (after `instances = [...]`, `:265`):

```python
        for inst in instances:
            cls._assert_atom_billable(inst)
```

Add the default no-op hook to the base class:

```python
    @classmethod
    def _assert_atom_billable(cls, instance):
        """Override to reject atoms that aren't in a billable lifecycle state."""
        return None
```

Override it in `InvoiceWizardService` (`apps/invoicing/services.py`):

```python
    @classmethod
    def _assert_atom_billable(cls, instance):
        from apps.jobs.models import Task
        from apps.inventory.models import Material
        if isinstance(instance, Task) and instance.status != Task.STATUS_COMPLETE:
            raise ValidationError('Cannot bill a task that is not complete.')
        if isinstance(instance, Material) and (
            instance.consumption_state != Material.CONSUMPTION_STATE_CONSUMED
        ):
            raise ValidationError('Cannot bill a material that is not consumed.')
```

> `ValidationError` is already imported in `apps/invoicing/services.py`. Expenses have no billability gate (override does nothing for them).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_api_invoicing -v 2`
Expected: PASS. Existing wizard tests may have billed in-progress tasks / pending materials — fix those tests to complete/consume the atom first (the new rule is correct), not by weakening the guard.

- [ ] **Step 6: Commit**

```bash
git add apps/invoicing/services.py apps/core/wizard.py tests/test_api_invoicing.py
git commit -m "feat(invoicing): gate wizard billability — task complete, material consumed

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `invoice` field on Task + Material serializers (via job claim map)

**Files:**
- Modify: `apps/api/jobs/serializers.py` (`get_tasks` `:113-120`, `get_materials` `:122-127`)
- Modify: `apps/api/tasks/serializers.py` (`TaskSerializer`)
- Modify: `apps/api/inventory/serializers.py` (`MaterialSerializer`)
- Test: `tests/test_api_jobs.py`

**Interfaces:**
- Consumes: `InvoiceClaimService.claims_for_job` (Task 1).
- Produces: job-detail payload `tasks[*].invoice` and `materials[*].invoice` = `null` or `{id, number}`. Context key: `invoice_claims` = `{(source_type, source_pk): {invoice_id, invoice_number}}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_jobs.py — reuse the module's job-detail GET pattern
def test_job_detail_marks_invoiced_task(self):
    # arrange: a complete task on the job, put on a draft invoice line+source
    self._invoice_task(self.task)               # add helper mirroring Task 4's _invoice_material
    self.client.force_login(self.user)
    resp = self.client.get(f'/api/jobs/{self.job.pk}/')
    self.assertEqual(resp.status_code, 200)
    task_row = next(t for t in resp.json()['tasks'] if t['task_id'] == self.task.pk)
    self.assertIsNotNone(task_row['invoice'])
    self.assertEqual(set(task_row['invoice'].keys()), {'id', 'number'})

def test_job_detail_uninvoiced_task_has_null_invoice(self):
    self.client.force_login(self.user)
    resp = self.client.get(f'/api/jobs/{self.job.pk}/')
    task_row = next(t for t in resp.json()['tasks'] if t['task_id'] == self.task.pk)
    self.assertIsNone(task_row['invoice'])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_jobs -v 2`
Expected: FAIL — `KeyError: 'invoice'`.

- [ ] **Step 3: Add the `invoice` field to both atom serializers**

Add a reusable mixin (same shape for both). In `apps/api/tasks/serializers.py`, add to `TaskSerializer`:

```python
    invoice = serializers.SerializerMethodField()
    # ... add 'invoice' to Meta.fields ...

    def get_invoice(self, obj):
        claims = self.context.get('invoice_claims')
        if not claims:
            return None
        ref = claims.get(('task', obj.pk))
        if not ref:
            return None
        return {'id': ref['invoice_id'], 'number': ref['invoice_number']}
```

In `apps/api/inventory/serializers.py` `MaterialSerializer`, add the same field with `('material', obj.pk)` and add `'invoice'` to `Meta.fields`:

```python
    invoice = serializers.SerializerMethodField()
    # ... add 'invoice' to Meta.fields ...

    def get_invoice(self, obj):
        claims = self.context.get('invoice_claims')
        if not claims:
            return None
        ref = claims.get(('material', obj.pk))
        if not ref:
            return None
        return {'id': ref['invoice_id'], 'number': ref['invoice_number']}
```

- [ ] **Step 4: Build the claim map once in `JobSerializer` and pass via context (detail only)**

In `apps/api/jobs/serializers.py`, add a memoized helper and thread context into the two method fields:

```python
    def _invoice_claims(self, obj):
        view = self.context.get('view')
        if view is not None and getattr(view, 'action', None) == 'list':
            return {}
        cache = getattr(self, '_claims_cache', None)
        if cache is None:
            cache = {}
            self._claims_cache = cache
        if obj.pk not in cache:
            from apps.invoicing.claims import InvoiceClaimService
            cache[obj.pk] = InvoiceClaimService.claims_for_job(obj)
        return cache[obj.pk]

    def get_tasks(self, obj):
        from apps.api.tasks.serializers import TaskSerializer
        tasks = obj.tasks.all()
        if not hasattr(obj, '_prefetched_objects_cache') or 'tasks' not in obj._prefetched_objects_cache:
            tasks = tasks.order_by('sort_order')
        return TaskSerializer(
            tasks, many=True,
            context={**self.context, 'invoice_claims': self._invoice_claims(obj)},
        ).data

    def get_materials(self, obj):
        from apps.api.inventory.serializers import MaterialSerializer
        materials = obj.materials.all()
        if not hasattr(obj, '_prefetched_objects_cache') or 'materials' not in obj._prefetched_objects_cache:
            materials = materials.order_by('pk')
        return MaterialSerializer(
            materials, many=True,
            context={**self.context, 'invoice_claims': self._invoice_claims(obj)},
        ).data
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_api_jobs -v 2`
Expected: PASS.

- [ ] **Step 6: Add an N+1 guard test**

```python
def test_job_detail_invoice_claims_single_query(self):
    # multiple invoiced tasks/materials must not scale queries with atom count
    self.client.force_login(self.user)
    with self.assertNumQueries(self._expected_job_detail_query_count):
        self.client.get(f'/api/jobs/{self.job.pk}/')
```

> Determine `_expected_job_detail_query_count` empirically: run once, read the count from the failure message, pin it, and assert it does **not** increase when you add a second invoiced atom in the same test. The point is to lock that claims are one query regardless of atom count.

- [ ] **Step 7: Run and commit**

Run: `python manage.py test tests.test_api_jobs -v 2`
Expected: PASS.

```bash
git add apps/api/jobs/serializers.py apps/api/tasks/serializers.py apps/api/inventory/serializers.py tests/test_api_jobs.py
git commit -m "feat(api): expose per-atom invoice ref on task/material serializers (no N+1)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `invoice` field on Expense serializer (loose expenses)

**Files:**
- Modify: `apps/api/expenses/serializers.py` (`ExpenseSerializer`)
- Modify: `apps/api/expenses/views.py` (`ExpenseViewSet` — provide `invoice_claims` context for the page)
- Test: `tests/test_api_expenses.py`

**Interfaces:**
- Consumes: `InvoiceClaimService.claims_for_atoms('expense', pks)` (Task 1).
- Produces: expense list/detail rows carry `invoice` = `null` or `{id, number}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_expenses.py — reuse the module's expense + invoice builders
def test_expense_list_marks_invoiced_expense(self):
    exp = self._make_loose_expense(self.job)         # material-less
    self._invoice_expense(exp)                        # add helper: line+source type 'expense'
    self.client.force_login(self.user)
    resp = self.client.get(f'/api/expenses/?job={self.job.pk}')
    row = next(r for r in resp.json()['results'] if r['id'] == exp.pk)
    self.assertEqual(set(row['invoice'].keys()), {'id', 'number'})
```

> Match the module's pagination shape (`results` vs bare list). `_invoice_expense` mirrors Task 4's `_invoice_material` but with `source_type=InvoiceLineItemSource.SOURCE_EXPENSE` and `source_pk=exp.pk`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_expenses -v 2`
Expected: FAIL — `KeyError: 'invoice'`.

- [ ] **Step 3: Add the field to `ExpenseSerializer`**

In `apps/api/expenses/serializers.py`, add to `ExpenseSerializer` and to `Meta.fields` (+ `read_only_fields`):

```python
    invoice = serializers.SerializerMethodField()

    def get_invoice(self, obj):
        claims = self.context.get('invoice_claims')
        if not claims:
            return None
        ref = claims.get(('expense', obj.pk))
        if not ref:
            return None
        return {'id': ref['invoice_id'], 'number': ref['invoice_number']}
```

- [ ] **Step 4: Provide the context map in `ExpenseViewSet`**

In `apps/api/expenses/views.py`, override `list` and `retrieve` to inject a page-scoped claim map (one query for the page):

```python
    def _claims_context_for(self, expenses):
        from apps.invoicing.claims import InvoiceClaimService
        pks = [e.pk for e in expenses]
        return InvoiceClaimService.claims_for_atoms('expense', pks)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        objs = page if page is not None else list(queryset)
        ctx = {**self.get_serializer_context(),
               'invoice_claims': self._claims_context_for(objs)}
        serializer = self.get_serializer(objs, many=True, context=ctx)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        ctx = {**self.get_serializer_context(),
               'invoice_claims': self._claims_context_for([instance])}
        return Response(self.get_serializer(instance, context=ctx).data)
```

> `Response` is already imported in this module (`apps/api/expenses/views.py:3`). `get_serializer` honors a passed `context` kwarg in DRF.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_api_expenses -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/expenses/serializers.py apps/api/expenses/views.py tests/test_api_expenses.py
git commit -m "feat(api): expose invoice ref on expenses (page-scoped claim map)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Overview UI — "Invoiced" link on tasks, materials, loose expenses

**Files:**
- Modify: `frontend/src/components/jobs/JobDetail.svelte` (Tasks pillar ~`:829`, Materials & Expenses pillar ~`:948-1040`)
- Test: `frontend/tests/JobDetail.invoiced.test.js` (new)

**Interfaces:**
- Consumes: `task.invoice`, `mat.invoice`, `exp.invoice` (`{id, number}` or `null`) from Tasks 6–7.

- [ ] **Step 1: Write the failing test**

```javascript
// frontend/tests/JobDetail.invoiced.test.js
import { render } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import JobDetail from '../src/components/jobs/JobDetail.svelte';

// Follow docs/designs/frontend-testing.md for the standard JobDetail mount
// (props it requires: job, expenses, etc. — mirror an existing JobDetail test).
function baseJob(overrides = {}) {
  return {
    job_id: 1, job_number: 'JOB-1', name: 'J', status: 'in_progress',
    tasks: [], materials: [], ...overrides,
  };
}

describe('JobDetail invoiced indicator', () => {
  it('renders an Invoiced link on an invoiced task', () => {
    const job = baseJob({
      tasks: [{ task_id: 7, name: 'Cut', status: 'complete',
                invoice: { id: 3, number: 'INV-3' } }],
    });
    const { getByText } = render(JobDetail, { props: { job, expenses: [] } });
    const link = getByText(/INV-3/);
    expect(link.getAttribute('href')).toBe('#/invoices/3');
  });

  it('omits the link when task.invoice is null', () => {
    const job = baseJob({
      tasks: [{ task_id: 7, name: 'Cut', status: 'complete', invoice: null }],
    });
    const { queryByText } = render(JobDetail, { props: { job, expenses: [] } });
    expect(queryByText(/Invoiced/)).toBeNull();
  });
});
```

> Before writing, open an existing `frontend/tests/*JobDetail*` test (if any) and copy its exact mount/props setup; `JobDetail.svelte` takes many props. Adjust `baseJob` to satisfy required props so it renders.

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test:run -- JobDetail.invoiced`
Expected: FAIL — no INV-3 link.

- [ ] **Step 3: Implement a small snippet and use it in all three rows**

In `frontend/src/components/jobs/JobDetail.svelte`, add a reusable markup snippet near the top of the markup section:

```svelte
{#snippet invoicedLink(inv)}
  {#if inv}
    <a class="badge-invoiced" href={`#/invoices/${inv.id}`} use:link
       title="Billed on this invoice">Invoiced · {inv.number}</a>
  {/if}
{/snippet}
```

Render it in the Tasks pillar row (alongside the task name/status), in the material row (near the existing `badge-paid` at `:987`), and in the loose-expense row (near the `expense` badge at `:1029`):

```svelte
{@render invoicedLink(task.invoice)}
{@render invoicedLink(mat.invoice)}
{@render invoicedLink(exp.invoice)}
```

Add a minimal style consistent with the existing badges:

```svelte
<style>
  .badge-invoiced { font-size: 0.85em; text-decoration: none; border: 1px solid #888;
                    border-radius: 3px; padding: 0 4px; margin-left: 6px; }
</style>
```

> Verify `link` is imported from `svelte-spa-router` in this file (it uses hash routing); if not, add `import { link } from 'svelte-spa-router';`. Match the existing badge class names/placement so it reads consistently.

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm run test:run -- JobDetail.invoiced`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/jobs/JobDetail.svelte frontend/tests/JobDetail.invoiced.test.js
git commit -m "feat(ui): show Invoiced link on overview tasks, materials, loose expenses

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Wizard pool — render greyed `not_billable` atoms

**Files:**
- Modify: `frontend/src/components/invoices/WizardSourcePool.svelte` (`:26-35`) and its atom child component
- Test: `frontend/tests/WizardSourcePool.test.js` (new or extended)

**Interfaces:**
- Consumes: `atom.state === 'not_billable'` and `atom.not_billable_reason` from Task 5.

- [ ] **Step 1: Write the failing test**

```javascript
// frontend/tests/WizardSourcePool.test.js
import { render } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import WizardSourcePool from '../src/components/invoices/WizardSourcePool.svelte';

const pool = {
  tasks: [{
    task_id: 1, name: 'Cut', has_billable_atoms: true,
    atoms: [{ type: 'task', id: 1, description: 'Cut (Hourly)', state: 'not_billable',
              not_billable_reason: 'task_incomplete', amount: '0.00' }],
  }],
  loose_materials: [],
};

describe('WizardSourcePool not_billable', () => {
  it('renders a non-selectable reason for not_billable atoms', () => {
    const { getByText, container } = render(WizardSourcePool, { props: { sourcePool: pool } });
    expect(getByText(/not complete/i)).toBeTruthy();
    const checkbox = container.querySelector('input[type="checkbox"]');
    expect(checkbox === null || checkbox.disabled).toBe(true);
  });
});
```

> Mirror the actual pool shape `WizardSourcePool` consumes (check the `{#each}` keys at `:26-35` and the atom child's props). Adjust the fixture to match real field names.

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test:run -- WizardSourcePool`
Expected: FAIL.

- [ ] **Step 3: Implement the greyed state in the atom component**

In the atom child component (the one rendered at `WizardSourcePool.svelte:32`), handle `state === 'not_billable'` like the existing `claimed_by_other` disabled rendering: render the checkbox disabled and show a reason label:

```svelte
{#if atom.state === 'not_billable'}
  <span class="atom-disabled">
    {atom.description} — {atom.not_billable_reason === 'task_incomplete'
      ? 'task not complete' : 'not consumed'}
  </span>
{:else if atom.state === 'claimed_by_other'}
  <!-- existing claimed rendering -->
{:else}
  <!-- existing selectable rendering -->
{/if}
```

Add a muted style mirroring the existing disabled/claimed style.

> Open the atom child component first and follow its exact existing branch structure for `claimed_by_other`; add `not_billable` as a sibling branch so selection logic (`onToggle`) is never wired for it.

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm run test:run -- WizardSourcePool`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/invoices/ frontend/tests/WizardSourcePool.test.js
git commit -m "feat(ui): grey out not-billable atoms in the invoice wizard pool

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Line item table — stacked per-source list

**Files:**
- Modify: `frontend/src/components/LineItemTable.svelte` (`sourceLabel` `:23-26`, source cell `:61`)
- Test: `frontend/tests/LineItemTable.test.js` (new or extended)

**Interfaces:**
- Consumes: `li.sources[*]` = `{source_type, source_pk, description, computed_amount}` (already serialized for both invoices and estimates).

- [ ] **Step 1: Write the failing test**

```javascript
// frontend/tests/LineItemTable.test.js
import { render } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import LineItemTable from '../src/components/LineItemTable.svelte';

const lineItems = [{
  line_item_id: 1, line_number: 1, description: 'Bundle', qty: 1, price: '30.00',
  units: 'none', accounting_category: null,
  sources: [
    { source_type: 'task', source_pk: 5, description: 'Cut (Hourly)', computed_amount: '20.00' },
    { source_type: 'material', source_pk: 9, description: 'Steel sheet', computed_amount: '10.00' },
  ],
}];

describe('LineItemTable source detail', () => {
  it('lists each source description and amount when showSource', () => {
    const { getByText } = render(LineItemTable, { props: { lineItems, showSource: true } });
    expect(getByText(/Cut \(Hourly\)/)).toBeTruthy();
    expect(getByText(/Steel sheet/)).toBeTruthy();
    expect(getByText(/\$10\.00/)).toBeTruthy();
  });

  it('shows "No source" for a line with no sources', () => {
    const bare = [{ ...lineItems[0], sources: [], inventory_item: null }];
    const { getByText } = render(LineItemTable, { props: { lineItems: bare, showSource: true } });
    expect(getByText('No source')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test:run -- LineItemTable`
Expected: FAIL — only "2 atoms" rendered.

- [ ] **Step 3: Implement the stacked list**

In `frontend/src/components/LineItemTable.svelte`, replace the `sourceLabel` count usage in the Source cell (`:61`) with a stacked list, keeping the `inventory_item` / `No source` fallbacks:

```svelte
{#if showSource}
  <td>
    {#if li.sources?.length}
      <ul class="source-list">
        {#each li.sources as s (s.source_type + ':' + s.source_pk)}
          <li>{s.description} <span class="src-amt">{fmtMoney(s.computed_amount)}</span></li>
        {/each}
      </ul>
    {:else if li.inventory_item}
      PLI #{li.inventory_item}
    {:else}
      No source
    {/if}
  </td>
{/if}
```

Add styles:

```svelte
<style>
  .source-list { margin: 0; padding-left: 1em; list-style: disc; }
  .source-list li { font-size: 0.9em; }
  .src-amt { color: #555; }
</style>
```

> Keep `sourceLabel` only if still used elsewhere; otherwise remove it. `fmtMoney` already exists in this file (`:15`).

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm run test:run -- LineItemTable`
Expected: PASS. Then run the full frontend suite for regressions (invoice + estimate detail render this component):
Run (from `frontend/`): `npm run test:run`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/LineItemTable.svelte frontend/tests/LineItemTable.test.js
git commit -m "feat(ui): show stacked per-source list on invoice/estimate line items

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Docs + LATER note

**Files:**
- Modify: `docs/designs/invoicing-and-expenses.md`, `docs/designs/estimates-and-prices.md`, `docs/designs/jobs-tasks-and-worksheets.md`, `docs/designs/materials-inventory-and-purchasing.md`
- Modify: `docs/designs/LATER.md`

- [ ] **Step 1: Update the design docs**

Document, in the relevant doc each: the `InvoiceClaimService` predicate and the binary "invoiced" indicator; task freeze-on-complete (incl. no bleps, `sort_order` exempt); material invoice freeze (sell_price, unconsume); wizard billability gates (task complete / material consumed / expense always); the stacked per-source line-item display.

- [ ] **Step 2: Add the expense-freeze symmetry note to LATER**

Append to `docs/designs/LATER.md`:

```markdown
- Expense atoms have an invoice-freeze (ExpenseService) but no separate
  billability-readiness gate (they bill on submission, by design). Revisit only
  if a "not ready to bill" expense state is ever needed.
```

> (Per the design, expenses are fully in scope and already frozen; this note records the deliberate absence of a readiness gate, not missing work.)

- [ ] **Step 3: Run the whole backend + frontend suite once**

Run: `python manage.py test` (single process)
Run (from `frontend/`): `npm run test:run`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add docs/designs/
git commit -m "docs: invoiced-atom visibility + freeze across design docs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Part 1 (centralized predicate) → Task 1.
- Part 2 (freeze: task / material / expense) → Tasks 2, 3, 4 (expense already done; refactor in Task 1).
- Part 3 (wizard billability gates) → Task 5.
- Part 4 (indicator API) → Tasks 6, 7.
- Part 5 (overview UI) → Task 8.
- Part 6 (stacked per-source list) → Task 10.
- Wizard greyed state (from Part 3 UI) → Task 9.
- Docs + LATER → Task 11.

**Type consistency:** context key `invoice_claims` and tuple key `(source_type, source_pk)` used identically in Tasks 1, 6, 7. `invoice` field shape `{id, number}` identical across task/material/expense serializers and the frontend (`inv.id`, `inv.number`). `not_billable` / `not_billable_reason` (`'task_incomplete'`/`'material_unconsumed'`) consistent between Task 5 (backend) and Task 9 (frontend).

**Known verification points for the implementer** (resolve by reading the cited code, not by guessing):
- Reuse each test module's existing builders/helpers; do not invent model fields (esp. how `Invoice`/`InvoiceLineItem`/`Task`/`Material` are constructed in `tests/test_api_invoicing.py`).
- Confirm `ValidationError` imports already present in each service module before adding code.
- Confirm `svelte-spa-router`'s `link` import in `JobDetail.svelte`; confirm the atom child component path used by `WizardSourcePool`.
- Pin the N+1 query count (Task 6 Step 6) empirically.
