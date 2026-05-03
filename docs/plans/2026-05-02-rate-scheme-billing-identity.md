# RateScheme as Billing Identity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `RateScheme` to the unit of billing identity for labor (owns AC + version lineage + immutability), drop billing fields from work items, force every Task to have a TaskCharge, and rebuild the invoice wizard around per-task atoms via `TaskCharge.compute()`.

**Architecture:** Two phases with a deliberate manual data-fix pause between them. Phase A is purely additive: new columns nullable, new code paths added with old-shape tolerance, no constraints tightened. Pause: developer runs the `check_billing_data` diagnostic and fixes any rows that won't survive Phase B. Phase B tightens `NOT NULL`s, drops legacy columns, removes tolerance branches, and enforces immutability.

**Tech Stack:** Django 5.2, DRF, MySQL, Python 3.12, Svelte 5 (Vite). Tests via Django `TestCase` with fixtures from `tests/base.py`.

**Spec:** `docs/designs/2026-05-02-rate-scheme-billing-identity-design.md`

**Important constraints:**
- `python manage.py migrate` is **never** run by an agent. Only the human applies migrations. Tests create their own test DB automatically.
- Custom `db_table` names: do NOT assume Django defaults.
- Project pattern: services in `apps/*/services.py` hold business logic, viewsets are thin wrappers.
- All DELETE responses return 200 with a JSON body, never 204.
- TDD: failing test first, see it fail, then minimal implementation.

---

## File Structure

### Files to create

- `apps/jobs/migrations/00XX_ratescheme_replaced_by.py` — adds `replaced_by` (self-FK, nullable) and `replaced_at` (DateTimeField, nullable). Phase A.
- `apps/jobs/migrations/00XX_planTask_rename_estimated_billable_qty.py` — renames `PlanTask.estimated_billable_qty` → `PlanTask.est_qty`. Phase B.
- `apps/jobs/migrations/00XX_drop_legacy_billing_fields.py` — drops `Task.rate`, `Task.units`, `Task.est_qty`, and `accounting_category` from `PlanTask` / `Task` / `TaskTemplate` (TaskTemplate's AC lives in `apps/estimates`). Phase B.
- `apps/estimates/migrations/00XX_drop_tasktemplate_ac_and_legacy.py` — drops `TaskTemplate.accounting_category`, `TaskTemplate.units`, `TaskTemplate.rate`; tightens `rate_scheme` and `default_billable_qty` to `NOT NULL`. Phase B.
- `apps/jobs/migrations/00XX_tighten_billing_constraints.py` — tightens `RateScheme.accounting_category`, `PlanTask.rate_scheme`, `PlanTask.est_qty` to `NOT NULL`. Phase B.
- `apps/jobs/management/__init__.py` (if not present) and `apps/jobs/management/commands/__init__.py` (if not present), plus `apps/jobs/management/commands/check_billing_data.py` — read-only diagnostic. Pause phase.
- `frontend/src/components/RateSchemeFieldset.svelte` — shared subcomponent for picker + modifier checkboxes + est_qty input. Phase A.
- `tests/test_rate_scheme_supersession.py` — new tests for `replaced_by`/`replaced_at`, edit-block, picker filtering. Phase A.
- `tests/test_task_charge_required.py` — new tests covering every Task creation path produces a TaskCharge. Phase A.
- `tests/test_template_superseded_guard.py` — new tests for the template-using-superseded-scheme 409 guard. Phase A.
- `tests/test_invoice_wizard_per_task_atoms.py` — new tests for per-task atom rendering and pricing through `task.charge.compute()`. Phase A.
- `tests/test_check_billing_data.py` — tests for the diagnostic command. Pause phase.
- `tests/test_planTask_est_qty_rename.py` — short test that asserts `PlanTask.est_qty` field exists post-Phase B.

### Files to modify

**Backend:**
- `apps/jobs/models.py` — RateScheme (add `replaced_by`, `replaced_at`, lock helpers, `clean()`), Task (drop legacy fields in Phase B, add `clean()` requiring TaskCharge), PlanTask (rename `estimated_billable_qty` in Phase B, drop AC field in Phase B), TaskBase (drop AC field in Phase B).
- `apps/estimates/models.py` — TaskTemplate.generate_task (propagate `rate_scheme` to PlanTask branch in Phase A, drop AC + units + rate fields in Phase B), TaskTemplate (drop AC field in Phase B).
- `apps/jobs/services.py` — TaskService.create_from_template (require rate_scheme, create TaskCharge), TaskService.create_direct (same), update propagation through `WorkTemplate.generate_tasks_for_worksheet`.
- `apps/estimates/services.py` — `add_task_from_template` (drop AC pass-through), `add_task_manual` (require rate_scheme), template-superseded guards.
- `apps/invoicing/services.py` — `InvoiceWizardService.get_source_pool` (per-task atoms), `_resolve_atom`, `_atom_computed_amount`, `_atom_category`, `_atom_source_type` for the new task atom type.
- `apps/invoicing/models.py` — add `SOURCE_TASK` to `InvoiceLineItemSource.SOURCE_CHOICES`.
- `apps/invoicing/migrations/00XX_add_source_task.py` — adds the new source_type choice (no schema change since `source_type` is a CharField with choices).
- `apps/api/rate_schemes/views.py` — add `supersede` action, edit-block on referenced schemes, list filter for active/superseded, permission preserved.
- `apps/api/rate_schemes/serializers.py` — add `replaced_by`, `replaced_at`, `superseded`, reference counts; validate `unit_label` via `validate_unit`; `accounting_category` becomes required in Phase B.
- `apps/api/plan_tasks/serializers.py` — drop `accounting_category` (Phase B), rename `estimated_billable_qty` → `est_qty` (Phase B).
- `apps/api/tasks/serializers.py` — drop `units`, `rate`, `est_qty`, `accounting_category` from TaskSerializer/TaskDetailSerializer (Phase B); ensure `charge` always present (Phase A).
- `apps/api/tasks/views.py` — task creation path requires rate_scheme + creates TaskCharge.
- `apps/api/templates_config/serializers.py` — drop `units`, `rate`, `accounting_category` from TaskTemplate fields list (Phase B).
- `apps/api/worksheets/views.py` and `apps/api/worksheets/serializers.py` — same drops on the nested PlanTask path.
- `apps/jobs/forms.py` and any HTML form for Task — drop AC field (Phase B).
- `apps/estimates/forms.py` (if any TaskTemplate form) — drop AC field (Phase B).

**Frontend:**
- `frontend/src/components/RateSchemeManager.svelte` — outdated-schemes tab, supersede flow, AC required, `unit_label` dropdown.
- `frontend/src/components/TaskTemplateManager.svelte` — drop AC field; show warning if scheme is superseded.
- `frontend/src/components/PlanTaskModal.svelte` — drop AC field; embed `RateSchemeFieldset`.
- `frontend/src/components/TaskModal.svelte` — drop AC field; embed `RateSchemeFieldset`.
- `frontend/src/components/SubtaskModal.svelte` — same as TaskModal.
- `frontend/src/routes/jobs/TaskDetailPage.svelte` — remove AC display.
- `frontend/src/components/invoices/InvoiceDetail.svelte` (and any wizard sub-component) — render per-task atoms, drop per-blep atom rendering.

### Test strategy

- **Per-task TDD**: every step that introduces behavior change starts with a failing test. Migration steps don't need test-first per se but are followed by a small assertion test (e.g., "field exists with this default") immediately after.
- Tests live in `/tests/`. Use `BaseTestCase` (loads `unit_test_data.json` fixture). For tests that need a clean slate, override `fixtures = []` in the class.
- Existing `tests/test_rate_scheme.py`, `tests/test_rate_scheme_api.py`, `tests/test_task_charge.py`, `tests/test_task_charge_api.py`, `tests/test_estimate_charge.py` are extended in place where appropriate.
- **Run tests serially** — never spawn parallel test runners (CLAUDE.md warning about MySQL deadlock).

---

## Phase A — additive, no constraint tightening

> **Phase A goal:** new code paths exist and are exercised; old shape still tolerated; no schema constraints changed beyond adding nullable columns.

### Task A1: Add `replaced_by` and `replaced_at` to RateScheme model

**Files:**
- Modify: `apps/jobs/models.py:316-340` (RateScheme class)
- Create: `apps/jobs/migrations/00XX_ratescheme_replaced_by.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_rate_scheme.py`:

```python
class RateSchemeSupersessionFieldsTest(BaseTestCase):
    def test_scheme_has_replaced_by_and_replaced_at_fields(self):
        from apps.jobs.models import RateScheme
        ac = AccountingCategory.objects.first()
        scheme = RateScheme.objects.create(
            name='X', algorithm='flat_fee', rate=Decimal('10'),
            unit_label='ea', accounting_category=ac,
        )
        # New nullable fields exist with sensible defaults
        self.assertIsNone(scheme.replaced_by)
        self.assertIsNone(scheme.replaced_at)
```

(`AccountingCategory` is already imported in the test file's existing tests; if not, add `from apps.core.models import AccountingCategory`.)

- [ ] **Step 2: Run test, expect FAIL**

```
python manage.py test tests.test_rate_scheme.RateSchemeSupersessionFieldsTest -v 2
```
Expected: AttributeError on `replaced_by` or migration error indicating the field does not exist.

- [ ] **Step 3: Add fields to model**

In `apps/jobs/models.py`, inside `class RateScheme`, after the `accounting_category` field:

```python
    replaced_by = models.ForeignKey(
        'self', on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='replaces',
    )
    replaced_at = models.DateTimeField(null=True, blank=True)
```

- [ ] **Step 4: Generate migration**

```
python manage.py makemigrations jobs --name ratescheme_replaced_by
```

- [ ] **Step 5: Run test, expect PASS**

```
python manage.py test tests.test_rate_scheme.RateSchemeSupersessionFieldsTest -v 2
```
Expected: 1 test passes.

- [ ] **Step 6: Commit**

```
git add apps/jobs/models.py apps/jobs/migrations/ tests/test_rate_scheme.py
git commit -m "feat: add replaced_by and replaced_at to RateScheme"
```

---

### Task A2: Reference-detection helper on RateScheme

**Files:**
- Modify: `apps/jobs/models.py` (RateScheme class)

- [ ] **Step 1: Write failing test**

Append to `tests/test_rate_scheme.py`:

```python
class RateSchemeIsReferencedTest(BaseTestCase):
    fixtures = []  # clean slate

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        self.ac = AccountingCategory.objects.create(code='X', name='X')

    def test_unreferenced_scheme_is_not_referenced(self):
        from apps.jobs.models import RateScheme
        s = RateScheme.objects.create(
            name='unref', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.assertFalse(s.is_referenced())

    def test_scheme_with_planTask_is_referenced(self):
        from apps.jobs.models import RateScheme, PlanTask
        from apps.estimates.models import EstWorksheet
        from apps.contacts.models import Contact, Business
        from apps.jobs.models import Job
        biz = Business.objects.create(name='B')
        contact = Contact.objects.create(first_name='F', last_name='L', business=biz)
        job = Job.objects.create(job_number='J1', contact=contact)
        ws = EstWorksheet.objects.create(job=job)
        s = RateScheme.objects.create(
            name='ref', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        PlanTask.objects.create(
            est_worksheet=ws, name='t', rate_scheme=s,
            estimated_billable_qty=Decimal('1'),
        )
        self.assertTrue(s.is_referenced())
```

(Add similar tests for TaskCharge and TaskTemplate references — same shape.)

- [ ] **Step 2: Run test, expect FAIL**

```
python manage.py test tests.test_rate_scheme.RateSchemeIsReferencedTest -v 2
```
Expected: AttributeError, `is_referenced` not defined.

- [ ] **Step 3: Add helper method to RateScheme**

In `apps/jobs/models.py`, inside `class RateScheme`, add:

```python
    def is_referenced(self):
        """True if any PlanTask, TaskCharge, or TaskTemplate points at this scheme."""
        from apps.estimates.models import TaskTemplate
        if PlanTask.objects.filter(rate_scheme=self).exists():
            return True
        if TaskCharge.objects.filter(rate_scheme=self).exists():
            return True
        if TaskTemplate.objects.filter(rate_scheme=self).exists():
            return True
        return False

    def reference_counts(self):
        """Return reference counts for the outdated-schemes UI."""
        from apps.estimates.models import TaskTemplate
        return {
            'plan_task_count': PlanTask.objects.filter(rate_scheme=self).count(),
            'task_charge_count': TaskCharge.objects.filter(rate_scheme=self).count(),
            'task_template_count': TaskTemplate.objects.filter(rate_scheme=self).count(),
        }
```

- [ ] **Step 4: Run test, expect PASS**

```
python manage.py test tests.test_rate_scheme.RateSchemeIsReferencedTest -v 2
```

- [ ] **Step 5: Commit**

```
git add apps/jobs/models.py tests/test_rate_scheme.py
git commit -m "feat: add is_referenced and reference_counts helpers to RateScheme"
```

---

### Task A3: `supersede()` model method on RateScheme

**Files:**
- Modify: `apps/jobs/models.py` (RateScheme class)

- [ ] **Step 1: Write failing test**

Append to `tests/test_rate_scheme.py`:

```python
class RateSchemeSupersedeMethodTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        self.ac = AccountingCategory.objects.create(code='X', name='X')

    def test_supersede_creates_new_scheme_and_links_old(self):
        from apps.jobs.models import RateScheme
        from django.utils import timezone
        old = RateScheme.objects.create(
            name='Old', algorithm='flat_fee', rate=Decimal('10'),
            unit_label='ea', accounting_category=self.ac,
        )
        before = timezone.now()
        new = old.supersede(name='New', rate=Decimal('15'))
        old.refresh_from_db()
        self.assertEqual(old.replaced_by, new)
        self.assertGreaterEqual(old.replaced_at, before)
        self.assertEqual(new.name, 'New')
        self.assertEqual(new.rate, Decimal('15'))
        # New scheme inherits non-overridden fields
        self.assertEqual(new.algorithm, 'flat_fee')
        self.assertEqual(new.unit_label, 'ea')
        self.assertEqual(new.accounting_category, self.ac)
        self.assertIsNone(new.replaced_by)
        self.assertIsNone(new.replaced_at)
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_rate_scheme.RateSchemeSupersedeMethodTest -v 2
```

- [ ] **Step 3: Implement**

In `apps/jobs/models.py`, inside `class RateScheme`, add:

```python
    def supersede(self, **overrides):
        """Create a new RateScheme inheriting this one's fields, set replaced_by/at."""
        from django.db import transaction
        from django.utils import timezone

        if self.replaced_by is not None:
            raise ValueError('Cannot supersede an already-superseded scheme.')

        defaults = {
            'name': self.name,
            'description': self.description,
            'algorithm': self.algorithm,
            'rate': self.rate,
            'unit_label': self.unit_label,
            'minimum_charge': self.minimum_charge,
            'modifiers': list(self.modifiers),
            'accounting_category': self.accounting_category,
        }
        defaults.update(overrides)

        with transaction.atomic():
            new = RateScheme.objects.create(**defaults)
            self.replaced_by = new
            self.replaced_at = timezone.now()
            # Save *only* replaced_by/at — bypass the freeze check that's coming
            # in Task A4 by using update() rather than save(). For now, save() works.
            RateScheme.objects.filter(pk=self.pk).update(
                replaced_by=new, replaced_at=self.replaced_at,
            )
        return new
```

(The `update()` rather than `save()` is deliberate — once the freeze check lands in Task A4, `save()` on a referenced scheme will reject the change; `update()` bypasses model `save()` and is the right primitive for this state transition.)

- [ ] **Step 4: Run test, expect PASS**

```
python manage.py test tests.test_rate_scheme.RateSchemeSupersedeMethodTest -v 2
```

- [ ] **Step 5: Commit**

```
git add apps/jobs/models.py tests/test_rate_scheme.py
git commit -m "feat: RateScheme.supersede() creates new version and links old"
```

---

### Task A4: Freeze referenced schemes via `clean()` / `save()`

**Files:**
- Modify: `apps/jobs/models.py` (RateScheme class)

- [ ] **Step 1: Write failing test**

Append to `tests/test_rate_scheme.py`:

```python
class RateSchemeFreezeOnReferenceTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        self.ac = AccountingCategory.objects.create(code='X', name='X')

    def _make_referenced_scheme(self):
        from apps.jobs.models import RateScheme, PlanTask, Job
        from apps.estimates.models import EstWorksheet
        from apps.contacts.models import Contact, Business
        biz = Business.objects.create(name='B')
        contact = Contact.objects.create(first_name='F', last_name='L', business=biz)
        job = Job.objects.create(job_number='J', contact=contact)
        ws = EstWorksheet.objects.create(job=job)
        s = RateScheme.objects.create(
            name='S', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        PlanTask.objects.create(
            est_worksheet=ws, name='t', rate_scheme=s,
            estimated_billable_qty=Decimal('1'),
        )
        return s

    def test_unreferenced_scheme_can_be_edited(self):
        from apps.jobs.models import RateScheme
        s = RateScheme.objects.create(
            name='U', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        s.rate = Decimal('2')
        s.save()  # no exception
        s.refresh_from_db()
        self.assertEqual(s.rate, Decimal('2'))

    def test_referenced_scheme_rejects_edits(self):
        from django.core.exceptions import ValidationError
        s = self._make_referenced_scheme()
        s.rate = Decimal('99')
        with self.assertRaises(ValidationError):
            s.full_clean()

    def test_supersede_still_works_on_referenced_scheme(self):
        s = self._make_referenced_scheme()
        new = s.supersede(rate=Decimal('99'))
        s.refresh_from_db()
        self.assertEqual(s.replaced_by, new)
```

- [ ] **Step 2: Run, expect 2 fails (referenced edit + freeze pass)**

```
python manage.py test tests.test_rate_scheme.RateSchemeFreezeOnReferenceTest -v 2
```

- [ ] **Step 3: Implement freeze in `clean()`**

In `apps/jobs/models.py`, inside `class RateScheme`, add:

```python
    # Fields that, once any reference exists, may not be changed
    # (replaced_by and replaced_at are the only allowed mutations).
    FROZEN_FIELDS = (
        'name', 'description', 'algorithm', 'rate', 'unit_label',
        'minimum_charge', 'modifiers', 'accounting_category',
    )

    def clean(self):
        super().clean()
        if self.pk and self.is_referenced():
            old = RateScheme.objects.get(pk=self.pk)
            changed = [
                f for f in self.FROZEN_FIELDS
                if getattr(self, f) != getattr(old, f)
            ]
            if changed:
                from django.core.exceptions import ValidationError
                raise ValidationError({
                    f: 'Scheme is referenced; create a new version instead of editing.'
                    for f in changed
                })

    def save(self, *args, **kwargs):
        # Belt-and-braces: ensure clean() runs even on bare .save() calls.
        if self.pk:
            self.full_clean()
        super().save(*args, **kwargs)
```

Note: this means callers that previously did `scheme.rate = X; scheme.save()` directly will now hit the freeze check. The `supersede()` method already uses `update()` to bypass `save()` for its own bookkeeping write, so the supersede path is unaffected.

- [ ] **Step 4: Run test, expect PASS**

```
python manage.py test tests.test_rate_scheme.RateSchemeFreezeOnReferenceTest -v 2
```

- [ ] **Step 5: Run the full RateScheme test module to catch regressions**

```
python manage.py test tests.test_rate_scheme tests.test_rate_scheme_api -v 2
```
Fix any pre-existing tests that mutate scheme fields after creating references — they need to switch to `supersede()`.

- [ ] **Step 6: Commit**

```
git add apps/jobs/models.py tests/test_rate_scheme.py
git commit -m "feat: freeze referenced RateSchemes; only supersede() may mutate"
```

---

### Task A4b: TaskTemplate.generate_task EstWorksheet branch propagates rate_scheme

**Files:**
- Modify: `apps/estimates/models.py:438-470` (`TaskTemplate.generate_task`)

> **Why:** The current EstWorksheet branch creates a PlanTask without `rate_scheme`, `active_modifiers`, or `estimated_billable_qty`. This is a known gap from the spec (`docs/plans/charge-thinking.md` thread D). Phase B will add `NOT NULL` to these PlanTask fields; this code path must populate them or it will break.

- [ ] **Step 1: Write failing test**

Append to `tests/test_estimate_charge.py`:

```python
class GenerateTaskEstWorksheetBranchTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Job
        from apps.estimates.models import TaskTemplate, EstWorksheet
        from apps.contacts.models import Business, Contact
        ac = AccountingCategory.objects.create(code='X', name='X')
        self.scheme = RateScheme.objects.create(
            name='S', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        self.template = TaskTemplate.objects.create(
            template_name='T', rate_scheme=self.scheme,
            default_active_modifiers=['m1'],
            default_billable_qty=Decimal('5'),
        )
        biz = Business.objects.create(name='B')
        c = Contact.objects.create(first_name='F', last_name='L', business=biz)
        job = Job.objects.create(job_number='J', contact=c)
        self.ws = EstWorksheet.objects.create(job=job)

    def test_generate_task_for_worksheet_propagates_scheme(self):
        pt = self.template.generate_task(self.ws, est_qty=Decimal('5'))
        self.assertEqual(pt.rate_scheme, self.scheme)
        self.assertEqual(pt.active_modifiers, ['m1'])
        self.assertEqual(pt.estimated_billable_qty, Decimal('5'))
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_estimate_charge.GenerateTaskEstWorksheetBranchTest -v 2
```

- [ ] **Step 3: Update the EstWorksheet branch**

In `apps/estimates/models.py`, in `TaskTemplate.generate_task`, replace the `else` branch:

```python
        else:  # EstWorksheet
            return PlanTask.objects.create(
                est_worksheet=container,
                name=self.template_name,
                description=self.description,
                accounting_category=self.accounting_category,  # legacy, dropped Phase B
                rate_scheme=self.rate_scheme,
                active_modifiers=list(self.default_active_modifiers or []),
                estimated_billable_qty=est_qty,
                sort_order=sort_order,
            )
```

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_estimate_charge.GenerateTaskEstWorksheetBranchTest -v 2
```

- [ ] **Step 5: Commit**

```
git add apps/estimates/models.py tests/test_estimate_charge.py
git commit -m "fix: TaskTemplate.generate_task EstWorksheet branch propagates rate_scheme"
```

---

### Task A5: API edit-block returns HTTP 409 with structured payload

**Files:**
- Modify: `apps/api/rate_schemes/views.py`
- Modify: `apps/api/rate_schemes/serializers.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_rate_scheme_api.py`:

```python
class RateSchemeEditBlockTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.core.models import User
        self.user = User.objects.create_user('admin', 'admin@x', 'pw')
        self.user.can_manage_config = True
        self.user.save()
        self.client.force_login(self.user)

    def _make_referenced_scheme(self):
        from apps.jobs.models import RateScheme, PlanTask, Job
        from apps.estimates.models import EstWorksheet
        from apps.contacts.models import Contact, Business
        from apps.core.models import AccountingCategory
        ac = AccountingCategory.objects.create(code='Z', name='Z')
        biz = Business.objects.create(name='B')
        contact = Contact.objects.create(first_name='F', last_name='L', business=biz)
        job = Job.objects.create(job_number='J-edit', contact=contact)
        ws = EstWorksheet.objects.create(job=job)
        s = RateScheme.objects.create(
            name='S-edit', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        PlanTask.objects.create(
            est_worksheet=ws, name='t', rate_scheme=s,
            estimated_billable_qty=Decimal('1'),
        )
        return s

    def test_patch_referenced_scheme_returns_409(self):
        s = self._make_referenced_scheme()
        resp = self.client.patch(
            f'/api/rate-schemes/{s.pk}/',
            {'rate': '99'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)
        body = resp.json()
        self.assertIn('supersede_url', body)
        self.assertIn('reference_counts', body)
        self.assertEqual(body['reference_counts']['plan_task_count'], 1)
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_rate_scheme_api.RateSchemeEditBlockTest -v 2
```

- [ ] **Step 3: Implement in viewset**

In `apps/api/rate_schemes/views.py`, override `update()` and `partial_update()`:

```python
from rest_framework import status

class RateSchemeViewSet(viewsets.ModelViewSet):
    # ... existing code ...

    def _block_if_referenced(self, instance, request):
        if instance.is_referenced():
            return Response(
                {
                    'detail': 'Scheme is referenced; create a new version instead of editing.',
                    'supersede_url': request.build_absolute_uri(
                        f'/api/rate-schemes/{instance.pk}/supersede/'
                    ),
                    'reference_counts': instance.reference_counts(),
                },
                status=status.HTTP_409_CONFLICT,
            )
        return None

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        blocked = self._block_if_referenced(instance, request)
        if blocked:
            return blocked
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        blocked = self._block_if_referenced(instance, request)
        if blocked:
            return blocked
        return super().partial_update(request, *args, **kwargs)
```

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_rate_scheme_api.RateSchemeEditBlockTest -v 2
```

- [ ] **Step 5: Commit**

```
git add apps/api/rate_schemes/views.py tests/test_rate_scheme_api.py
git commit -m "feat: API blocks edits to referenced RateSchemes with HTTP 409"
```

---

### Task A6: `supersede` API endpoint

**Files:**
- Modify: `apps/api/rate_schemes/views.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_rate_scheme_api.py`:

```python
class RateSchemeSupersedeEndpointTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.core.models import User, AccountingCategory
        self.user = User.objects.create_user('admin', 'a@x', 'pw')
        self.user.can_manage_config = True
        self.user.save()
        self.client.force_login(self.user)
        self.ac = AccountingCategory.objects.create(code='Y', name='Y')

    def test_supersede_creates_new_and_links_old(self):
        from apps.jobs.models import RateScheme
        old = RateScheme.objects.create(
            name='O', algorithm='flat_fee', rate=Decimal('5'),
            unit_label='ea', accounting_category=self.ac,
        )
        resp = self.client.post(
            f'/api/rate-schemes/{old.pk}/supersede/',
            {
                'name': 'O v2', 'rate': '7', 'algorithm': 'flat_fee',
                'unit_label': 'ea', 'accounting_category': self.ac.pk,
                'modifiers': [], 'description': '',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        new_id = resp.json()['rate_scheme_id']
        old.refresh_from_db()
        self.assertEqual(old.replaced_by_id, new_id)
        self.assertIsNotNone(old.replaced_at)

    def test_supersede_requires_can_manage_config(self):
        from apps.jobs.models import RateScheme
        from apps.core.models import User
        plain = User.objects.create_user('plain', 'p@x', 'pw')
        self.client.force_login(plain)
        old = RateScheme.objects.create(
            name='O', algorithm='flat_fee', rate=Decimal('5'),
            unit_label='ea', accounting_category=self.ac,
        )
        resp = self.client.post(f'/api/rate-schemes/{old.pk}/supersede/', {})
        self.assertEqual(resp.status_code, 403)
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_rate_scheme_api.RateSchemeSupersedeEndpointTest -v 2
```

- [ ] **Step 3: Implement action**

In `apps/api/rate_schemes/views.py`, add:

```python
from rest_framework.decorators import action
from .serializers import RateSchemeSerializer

class RateSchemeViewSet(viewsets.ModelViewSet):
    # ... existing code ...

    @action(detail=True, methods=['post'], url_path='supersede',
            permission_classes=[IsAuthenticated, CanManageConfig])
    def supersede(self, request, pk=None):
        old = self.get_object()
        if old.replaced_by_id is not None:
            return Response(
                {'detail': 'Scheme is already superseded.'},
                status=status.HTTP_409_CONFLICT,
            )
        # Validate the new scheme's payload using the standard serializer,
        # but treat input as the supersede overrides.
        serializer = RateSchemeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Use only fields actually provided as overrides.
        overrides = {k: v for k, v in serializer.validated_data.items()}
        new = old.supersede(**overrides)
        return Response(
            RateSchemeSerializer(new).data,
            status=status.HTTP_201_CREATED,
        )
```

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_rate_scheme_api.RateSchemeSupersedeEndpointTest -v 2
```

- [ ] **Step 5: Commit**

```
git add apps/api/rate_schemes/views.py tests/test_rate_scheme_api.py
git commit -m "feat: POST /api/rate-schemes/{id}/supersede/ endpoint"
```

---

### Task A7: List endpoint filters to active schemes; `?include_superseded` flag

**Files:**
- Modify: `apps/api/rate_schemes/views.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_rate_scheme_api.py`:

```python
class RateSchemeListFilterTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.core.models import User, AccountingCategory
        from apps.jobs.models import RateScheme
        self.user = User.objects.create_user('u', 'u@x', 'pw')
        self.client.force_login(self.user)
        self.ac = AccountingCategory.objects.create(code='Z', name='Z')
        self.active = RateScheme.objects.create(
            name='A', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.old = RateScheme.objects.create(
            name='O', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.new = self.old.supersede(name='N')

    def test_default_list_excludes_superseded(self):
        resp = self.client.get('/api/rate-schemes/')
        ids = [r['rate_scheme_id'] for r in resp.json()['results']]
        self.assertIn(self.active.pk, ids)
        self.assertIn(self.new.pk, ids)
        self.assertNotIn(self.old.pk, ids)

    def test_include_superseded_returns_all(self):
        resp = self.client.get('/api/rate-schemes/?include_superseded=true')
        ids = [r['rate_scheme_id'] for r in resp.json()['results']]
        self.assertIn(self.old.pk, ids)
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_rate_scheme_api.RateSchemeListFilterTest -v 2
```

- [ ] **Step 3: Implement**

In `apps/api/rate_schemes/views.py`, override `get_queryset`:

```python
class RateSchemeViewSet(viewsets.ModelViewSet):
    # remove the class-level queryset = ... line if present, or keep as base
    queryset = RateScheme.objects.all().order_by('name')

    def get_queryset(self):
        qs = RateScheme.objects.all().order_by('name')
        if self.action == 'list':
            include = self.request.query_params.get('include_superseded') == 'true'
            only = self.request.query_params.get('only_superseded') == 'true'
            if only:
                qs = qs.filter(replaced_by__isnull=False)
            elif not include:
                qs = qs.filter(replaced_by__isnull=True)
        return qs
```

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_rate_scheme_api.RateSchemeListFilterTest -v 2
```

- [ ] **Step 5: Commit**

```
git add apps/api/rate_schemes/views.py tests/test_rate_scheme_api.py
git commit -m "feat: rate-scheme list filters to active by default; include/only flags"
```

---

### Task A8: Serializer additions (replaced_by, replaced_at, superseded, reference counts) and `unit_label` validation

**Files:**
- Modify: `apps/api/rate_schemes/serializers.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_rate_scheme_api.py`:

```python
class RateSchemeSerializerExtraFieldsTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.core.models import User, AccountingCategory
        from apps.jobs.models import RateScheme
        self.user = User.objects.create_user('u', 'u@x', 'pw')
        self.client.force_login(self.user)
        self.ac = AccountingCategory.objects.create(code='X', name='X')
        self.s = RateScheme.objects.create(
            name='S', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )

    def test_serializer_includes_replaced_fields_and_counts(self):
        resp = self.client.get(f'/api/rate-schemes/{self.s.pk}/')
        body = resp.json()
        self.assertIn('replaced_by', body)
        self.assertIn('replaced_at', body)
        self.assertIn('superseded', body)
        self.assertFalse(body['superseded'])
        self.assertEqual(body['reference_counts']['plan_task_count'], 0)

    def test_unit_label_must_be_in_configured_units(self):
        from apps.core.models import User
        admin = User.objects.create_user('a', 'a@x', 'pw')
        admin.can_manage_config = True
        admin.save()
        self.client.force_login(admin)
        resp = self.client.post('/api/rate-schemes/', {
            'name': 'BadUnits', 'algorithm': 'flat_fee', 'rate': '1',
            'unit_label': 'frobnitz', 'accounting_category': self.ac.pk,
            'modifiers': [], 'description': '',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('unit_label', resp.json())
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_rate_scheme_api.RateSchemeSerializerExtraFieldsTest -v 2
```

- [ ] **Step 3: Update serializer**

Replace `apps/api/rate_schemes/serializers.py` with:

```python
from rest_framework import serializers
from apps.jobs.models import RateScheme
from apps.core.units import get_units_list


class RateSchemeSerializer(serializers.ModelSerializer):
    superseded = serializers.SerializerMethodField()
    reference_counts = serializers.SerializerMethodField()

    class Meta:
        model = RateScheme
        fields = [
            'rate_scheme_id', 'name', 'description', 'algorithm',
            'rate', 'unit_label', 'minimum_charge',
            'modifiers', 'accounting_category',
            'replaced_by', 'replaced_at', 'superseded', 'reference_counts',
        ]
        read_only_fields = [
            'rate_scheme_id', 'replaced_by', 'replaced_at',
            'superseded', 'reference_counts',
        ]

    def get_superseded(self, obj):
        return obj.replaced_by_id is not None

    def get_reference_counts(self, obj):
        return obj.reference_counts()

    def validate_unit_label(self, value):
        allowed = get_units_list()
        if value not in allowed:
            raise serializers.ValidationError(
                f'"{value}" is not a configured unit.'
            )
        return value
```

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_rate_scheme_api.RateSchemeSerializerExtraFieldsTest -v 2
```

- [ ] **Step 5: Commit**

```
git add apps/api/rate_schemes/serializers.py tests/test_rate_scheme_api.py
git commit -m "feat: RateScheme serializer exposes supersession fields and validates unit_label"
```

---

### Task A9: Make `accounting_category` required on RateScheme model (Phase A: validation only, not NOT NULL)

**Files:**
- Modify: `apps/jobs/models.py` (RateScheme.clean())

> **Why now in Phase A:** the spec says NOT NULL is Phase B, but we want the validation rule active during Phase A so new schemes always get an AC. The DB column stays nullable until Phase B's migration tightens it.

- [ ] **Step 1: Write failing test**

Append to `tests/test_rate_scheme.py`:

```python
class RateSchemeRequiresACTest(BaseTestCase):
    fixtures = []

    def test_full_clean_rejects_missing_ac(self):
        from django.core.exceptions import ValidationError
        from apps.jobs.models import RateScheme
        s = RateScheme(
            name='NoAC', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea',
        )
        with self.assertRaises(ValidationError) as cm:
            s.full_clean()
        self.assertIn('accounting_category', cm.exception.message_dict)
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_rate_scheme.RateSchemeRequiresACTest -v 2
```

- [ ] **Step 3: Tighten clean()**

In `apps/jobs/models.py`, in `RateScheme.clean()`, prepend:

```python
    def clean(self):
        super().clean()
        if self.accounting_category_id is None:
            from django.core.exceptions import ValidationError
            raise ValidationError({
                'accounting_category': 'Required: every RateScheme must have an AccountingCategory.',
            })
        # ...existing freeze check follows...
```

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_rate_scheme -v 2
```
Fix any existing tests that create RateSchemes without an AC.

- [ ] **Step 5: Commit**

```
git add apps/jobs/models.py tests/test_rate_scheme.py
git commit -m "feat: require AccountingCategory on RateScheme via clean()"
```

---

### Task A10: AC pass-through helper properties on PlanTask, Task, TaskTemplate

**Files:**
- Modify: `apps/jobs/models.py` (PlanTask, Task, TaskBase)
- Modify: `apps/estimates/models.py` (TaskTemplate)

> **Why:** Phase A introduces the read path (`work_item.effective_accounting_category`) without removing the legacy field. Frontend and downstream code switch to the new property; the old field stays for the duration of the pause to keep dev data viable.

- [ ] **Step 1: Write failing test**

Append to `tests/test_estimate_charge.py`:

```python
class EffectiveACPropertyTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme
        self.scheme_ac = AccountingCategory.objects.create(code='S', name='Scheme AC')
        self.scheme = RateScheme.objects.create(
            name='S', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.scheme_ac,
        )

    def test_planTask_effective_ac_comes_from_scheme(self):
        from apps.jobs.models import PlanTask, Job
        from apps.estimates.models import EstWorksheet
        from apps.contacts.models import Business, Contact
        biz = Business.objects.create(name='B')
        c = Contact.objects.create(first_name='F', last_name='L', business=biz)
        job = Job.objects.create(job_number='J', contact=c)
        ws = EstWorksheet.objects.create(job=job)
        pt = PlanTask.objects.create(
            est_worksheet=ws, name='t',
            rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('1'),
        )
        self.assertEqual(pt.effective_accounting_category, self.scheme_ac)

    def test_task_effective_ac_comes_from_charge_scheme(self):
        from apps.jobs.models import Task, TaskCharge, Job
        from apps.contacts.models import Business, Contact
        biz = Business.objects.create(name='B')
        c = Contact.objects.create(first_name='F', last_name='L', business=biz)
        job = Job.objects.create(job_number='J', contact=c)
        t = Task.objects.create(job=job, name='t')
        TaskCharge.objects.create(task=t, rate_scheme=self.scheme)
        t.refresh_from_db()
        self.assertEqual(t.effective_accounting_category, self.scheme_ac)
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_estimate_charge.EffectiveACPropertyTest -v 2
```

- [ ] **Step 3: Add properties**

In `apps/jobs/models.py`, inside `class PlanTask`:

```python
    @property
    def effective_accounting_category(self):
        if self.rate_scheme_id:
            return self.rate_scheme.accounting_category
        return self.accounting_category  # Phase A fallback to legacy field
```

Inside `class Task`:

```python
    @property
    def effective_accounting_category(self):
        try:
            charge = self.charge
        except TaskCharge.DoesNotExist:
            return self.accounting_category  # Phase A fallback
        if charge.rate_scheme_id:
            return charge.rate_scheme.accounting_category
        return self.accounting_category
```

In `apps/estimates/models.py`, inside `class TaskTemplate`:

```python
    @property
    def effective_accounting_category(self):
        if self.rate_scheme_id:
            return self.rate_scheme.accounting_category
        return self.accounting_category  # Phase A fallback
```

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_estimate_charge.EffectiveACPropertyTest -v 2
```

- [ ] **Step 5: Commit**

```
git add apps/jobs/models.py apps/estimates/models.py tests/test_estimate_charge.py
git commit -m "feat: effective_accounting_category property on PlanTask/Task/TaskTemplate"
```

---

### Task A11: Require RateScheme on PlanTask creation services

**Files:**
- Modify: `apps/estimates/services.py:391-405` (`add_task_manual`)
- Modify: `apps/estimates/services.py:358-389` (`add_task_from_template`) — drop AC pass-through; require rate_scheme

- [ ] **Step 1: Write failing test**

Append to `tests/test_estimate_charge.py`:

```python
class AddTaskManualRequiresSchemeTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Job
        from apps.estimates.models import EstWorksheet
        from apps.contacts.models import Business, Contact
        self.ac = AccountingCategory.objects.create(code='X', name='X')
        self.scheme = RateScheme.objects.create(
            name='S', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        biz = Business.objects.create(name='B')
        c = Contact.objects.create(first_name='F', last_name='L', business=biz)
        job = Job.objects.create(job_number='J', contact=c)
        self.ws = EstWorksheet.objects.create(job=job)

    def test_add_task_manual_without_scheme_raises(self):
        from apps.estimates.services import WorksheetService
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            WorksheetService.add_task_manual(
                self.ws.pk, name='no scheme',
                estimated_billable_qty=Decimal('1'),
            )

    def test_add_task_manual_with_scheme_succeeds(self):
        from apps.estimates.services import WorksheetService
        pt = WorksheetService.add_task_manual(
            self.ws.pk, name='ok',
            rate_scheme_id=self.scheme.pk,
            estimated_billable_qty=Decimal('1'),
        )
        self.assertEqual(pt.rate_scheme_id, self.scheme.pk)
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_estimate_charge.AddTaskManualRequiresSchemeTest -v 2
```

- [ ] **Step 3: Update service**

In `apps/estimates/services.py`, modify `add_task_manual`:

```python
    @staticmethod
    def add_task_manual(worksheet_pk, **kwargs):
        """Add a PlanTask manually to a draft worksheet."""
        from apps.jobs.models import PlanTask
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            raise NotFoundError(f'EstWorksheet {worksheet_pk} not found')
        if ws.status != EstWorksheet.STATUS_DRAFT:
            raise ValidationError(
                f'Cannot add tasks to a {ws.get_status_display().lower()} worksheet.'
            )
        if not kwargs.get('rate_scheme_id') and not kwargs.get('rate_scheme'):
            raise ValidationError(
                {'rate_scheme': 'A RateScheme is required to add a task.'}
            )
        task = PlanTask(est_worksheet=ws, **kwargs)
        task.full_clean()
        task.save()
        return task
```

In `add_task_from_template`, drop the `accounting_category=tt.accounting_category` line (AC now flows through scheme):

```python
        task = PlanTask.objects.create(
            name=tt.template_name,
            description=tt.description,
            est_worksheet=ws,
            rate_scheme_id=rate_scheme_id if rate_scheme_id is not None else tt.rate_scheme_id,
            active_modifiers=active_modifiers if active_modifiers is not None else (tt.default_active_modifiers or []),
            estimated_billable_qty=estimated_billable_qty if estimated_billable_qty is not None else tt.default_billable_qty,
        )
```

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_estimate_charge -v 2
```

- [ ] **Step 5: Commit**

```
git add apps/estimates/services.py tests/test_estimate_charge.py
git commit -m "feat: PlanTask creation requires rate_scheme; AC no longer set from template"
```

---

### Task A12: Template-superseded guard (service + API 409)

**Files:**
- Modify: `apps/estimates/models.py:438-470` (`TaskTemplate.generate_task`)
- Modify: `apps/estimates/services.py` (`WorksheetService.add_task_from_template`)
- Modify: `apps/jobs/services.py:374-401` (`TaskService.create_from_template`)

- [ ] **Step 1: Write failing test**

Create `tests/test_template_superseded_guard.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from tests.base import BaseTestCase


class TemplateSupersededGuardTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Job
        from apps.estimates.models import TaskTemplate, EstWorksheet
        from apps.contacts.models import Business, Contact
        self.ac = AccountingCategory.objects.create(code='X', name='X')
        self.old_scheme = RateScheme.objects.create(
            name='O', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.template = TaskTemplate.objects.create(
            template_name='T', rate_scheme=self.old_scheme,
            default_billable_qty=Decimal('1'),
        )
        self.new_scheme = self.old_scheme.supersede(name='N')
        biz = Business.objects.create(name='B')
        c = Contact.objects.create(first_name='F', last_name='L', business=biz)
        self.job = Job.objects.create(job_number='J', contact=c)
        self.ws = EstWorksheet.objects.create(job=self.job)

    def test_generate_task_for_planTask_branch_raises(self):
        with self.assertRaises(ValidationError) as cm:
            self.template.generate_task(self.ws, est_qty=Decimal('1'))
        self.assertIn('superseded', str(cm.exception).lower())

    def test_generate_task_for_task_branch_raises(self):
        with self.assertRaises(ValidationError) as cm:
            self.template.generate_task(self.job, est_qty=Decimal('1'))
        self.assertIn('superseded', str(cm.exception).lower())
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_template_superseded_guard -v 2
```

- [ ] **Step 3: Implement guard in `generate_task`**

In `apps/estimates/models.py`, at the top of `TaskTemplate.generate_task`:

```python
    def generate_task(self, container, est_qty, bundle_identifier=None,
                      product_instance=None, assignee=None, sort_order=None):
        from django.core.exceptions import ValidationError
        from apps.jobs.models import Job, Task, PlanTask, TaskCharge

        if self.rate_scheme_id and self.rate_scheme.replaced_by_id is not None:
            raise ValidationError(
                f'Template "{self.template_name}" references a superseded '
                f'RateScheme. Update the template before adding tasks from it.'
            )

        # ...existing code...
```

- [ ] **Step 4: Add a dedicated exception type**

In `apps/core/services.py`, add:

```python
class SchemeSupersededError(ServiceError):
    """Raised when a template referencing a superseded RateScheme is used."""
```

Update `apps/estimates/models.py` `TaskTemplate.generate_task` to raise this instead of `ValidationError`:

```python
    def generate_task(self, container, est_qty, bundle_identifier=None,
                      product_instance=None, assignee=None, sort_order=None):
        from apps.jobs.models import Job, Task, PlanTask, TaskCharge
        from apps.core.services import SchemeSupersededError

        if self.rate_scheme_id and self.rate_scheme.replaced_by_id is not None:
            raise SchemeSupersededError(
                f'Template "{self.template_name}" references a superseded '
                f'RateScheme. Update the template before adding tasks from it.'
            )
        # ...existing code...
```

- [ ] **Step 5: Update the test to expect `SchemeSupersededError`**

Replace both `assertRaises(ValidationError)` blocks in `tests/test_template_superseded_guard.py` with:

```python
    def test_generate_task_for_planTask_branch_raises(self):
        from apps.core.services import SchemeSupersededError
        with self.assertRaises(SchemeSupersededError) as cm:
            self.template.generate_task(self.ws, est_qty=Decimal('1'))
        self.assertIn('superseded', str(cm.exception).lower())

    def test_generate_task_for_task_branch_raises(self):
        from apps.core.services import SchemeSupersededError
        with self.assertRaises(SchemeSupersededError) as cm:
            self.template.generate_task(self.job, est_qty=Decimal('1'))
        self.assertIn('superseded', str(cm.exception).lower())
```

- [ ] **Step 6: Map the exception to HTTP 409 in API views**

The endpoints that go through `generate_task` or call `TaskService.create_from_template` are at minimum:
- `POST /api/jobs/{id}/add-from-template/` — handler in `apps/api/jobs/views.py`
- `POST /api/jobs/{id}/populate-from-template/` — handler in `apps/api/jobs/views.py`

In each handler, wrap the call:

```python
from apps.core.services import SchemeSupersededError

try:
    # existing call to the service / generate_task
    ...
except SchemeSupersededError as e:
    return Response({'detail': str(e)}, status=status.HTTP_409_CONFLICT)
```

Add an integration test that hits the API endpoint and asserts 409:

```python
class TemplateSupersededAPITest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        # Same setup as TemplateSupersededGuardTest, plus client.force_login a user
        # with can_manage_jobs permission.
        ...

    def test_add_from_template_with_superseded_scheme_returns_409(self):
        resp = self.client.post(
            f'/api/jobs/{self.job.pk}/add-from-template/',
            {'template_id': self.template.pk, 'est_qty': '1'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 409)
        self.assertIn('superseded', resp.json()['detail'].lower())
```

- [ ] **Step 5: Run, expect PASS**

```
python manage.py test tests.test_template_superseded_guard -v 2
```

- [ ] **Step 6: Commit**

```
git add apps/estimates/models.py apps/core/services.py apps/api/jobs/views.py tests/test_template_superseded_guard.py
git commit -m "feat: block use of templates whose RateScheme is superseded (HTTP 409)"
```

---

### Task A13: TaskService creates TaskCharge in same transaction; require rate_scheme

**Files:**
- Modify: `apps/jobs/services.py:374-401` (`TaskService.create_from_template`, `create_direct`)
- Modify: `apps/estimates/models.py:438-470` (`TaskTemplate.generate_task` Job branch)

- [ ] **Step 1: Write failing test**

Create `tests/test_task_charge_required.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from tests.base import BaseTestCase


class TaskCreationProducesChargeTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Job
        from apps.estimates.models import TaskTemplate
        from apps.contacts.models import Business, Contact
        self.ac = AccountingCategory.objects.create(code='X', name='X')
        self.scheme = RateScheme.objects.create(
            name='S', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )
        self.template = TaskTemplate.objects.create(
            template_name='T', rate_scheme=self.scheme,
            default_billable_qty=Decimal('1'),
        )
        biz = Business.objects.create(name='B')
        c = Contact.objects.create(first_name='F', last_name='L', business=biz)
        self.job = Job.objects.create(job_number='J', contact=c)

    def test_create_from_template_creates_charge(self):
        from apps.jobs.services import TaskService
        task = TaskService.create_from_template(self.template, self.job)
        self.assertTrue(hasattr(task, 'charge'))
        self.assertEqual(task.charge.rate_scheme, self.scheme)

    def test_create_direct_without_scheme_raises(self):
        from apps.jobs.services import TaskService
        with self.assertRaises(ValidationError):
            TaskService.create_direct(self.job, name='no scheme')

    def test_create_direct_with_scheme_creates_charge(self):
        from apps.jobs.services import TaskService
        task = TaskService.create_direct(
            self.job, name='ok', rate_scheme_id=self.scheme.pk,
        )
        self.assertTrue(hasattr(task, 'charge'))
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_task_charge_required -v 2
```

- [ ] **Step 3: Update services**

In `apps/jobs/services.py`, replace `TaskService.create_from_template` and `create_direct`:

```python
class TaskService:
    @staticmethod
    def create_from_template(template, job, assignee=None):
        from django.db import transaction
        if not template.is_active:
            raise ValidationError(f"Template {template.template_name} is not active.")
        if template.rate_scheme_id and template.rate_scheme.replaced_by_id is not None:
            from apps.core.services import SchemeSupersededError
            raise SchemeSupersededError(
                f'Template "{template.template_name}" references a superseded RateScheme.'
            )
        if not template.rate_scheme_id:
            raise ValidationError(
                f'Template "{template.template_name}" has no rate_scheme.'
            )
        with transaction.atomic():
            task = Task.objects.create(
                job=job,
                name=template.template_name,
                assignee=assignee,
            )
            TaskCharge.objects.create(
                task=task,
                rate_scheme=template.rate_scheme,
                active_modifiers=template.default_active_modifiers or [],
            )
        return task

    @staticmethod
    def create_direct(job, name, rate_scheme_id=None, active_modifiers=None,
                      actuals=None, **task_fields):
        from django.db import transaction
        if not rate_scheme_id:
            raise ValidationError({'rate_scheme': 'Required.'})
        scheme = RateScheme.objects.get(pk=rate_scheme_id)
        if scheme.replaced_by_id is not None:
            raise ValidationError(
                {'rate_scheme': 'Selected RateScheme is superseded.'}
            )
        with transaction.atomic():
            task = Task.objects.create(job=job, name=name, **task_fields)
            TaskCharge.objects.create(
                task=task, rate_scheme=scheme,
                active_modifiers=active_modifiers or [],
                actuals=actuals or {},
            )
        return task
```

Add at top of `apps/jobs/services.py` if missing: `from apps.jobs.models import RateScheme, TaskCharge`.

In `apps/estimates/models.py`, in `TaskTemplate.generate_task`'s Job branch, wrap with the same TaskCharge creation:

```python
        if isinstance(container, Job):
            from django.db import transaction
            with transaction.atomic():
                task = Task.objects.create(
                    job=container,
                    name=self.template_name,
                    description=self.description,
                    units=self.units,                # legacy, still in DB Phase A
                    rate=self.rate,
                    est_qty=est_qty,
                    accounting_category=self.accounting_category,  # legacy, Phase A
                    assignee=assignee,
                    sort_order=sort_order,
                )
                if self.rate_scheme_id:
                    TaskCharge.objects.create(
                        task=task, rate_scheme=self.rate_scheme,
                        active_modifiers=self.default_active_modifiers or [],
                    )
            return task
```

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_task_charge_required -v 2
```

- [ ] **Step 5: Run full test suite, fix regressions**

```
python manage.py test tests -v 2 2>&1 | tail -50
```
Existing tests that called `TaskService.create_from_template` or `create_direct` without a scheme will need updates. Provide the test fixture's existing scheme.

- [ ] **Step 6: Commit**

```
git add apps/jobs/services.py apps/estimates/models.py tests/test_task_charge_required.py
git commit -m "feat: TaskService creates TaskCharge transactionally and requires rate_scheme"
```

---

### Task A14: `Task.clean()` defensive check that TaskCharge exists

**Files:**
- Modify: `apps/jobs/models.py` (Task class)

> Phase A note: this is a soft warning during Phase A (does not raise) so existing tasks without charges are tolerated. Phase B promotes to a hard `ValidationError`.

- [ ] **Step 1: Write failing test (Phase B-targeted; Phase A skip)**

Skip this step in Phase A. Add a TODO comment in the Task class noting the Phase B promotion:

```python
    def clean(self):
        super().clean()
        # Phase B: enable hard requirement that every Task has a TaskCharge.
        # Phase A keeps this soft to tolerate legacy data during the manual-fix window.
        # if self.pk and not hasattr(self, 'charge'):
        #     raise ValidationError({'charge': 'Required: every Task must have a TaskCharge.'})
```

- [ ] **Step 2: Commit**

```
git add apps/jobs/models.py
git commit -m "chore: Task.clean() placeholder for Phase B charge-required check"
```

---

### Task A15: Per-task atom infrastructure in invoice wizard — add SOURCE_TASK choice

**Files:**
- Modify: `apps/invoicing/models.py`
- Create: `apps/invoicing/migrations/00XX_add_source_task.py`

- [ ] **Step 1: Inspect current source choices**

```
grep -n "SOURCE_BLEP\|SOURCE_MATERIAL\|SOURCE_CHOICES" apps/invoicing/models.py
```
Expected: `SOURCE_BLEP`, `SOURCE_MATERIAL` constants in `InvoiceLineItemSource`.

- [ ] **Step 2: Add the new choice**

In `apps/invoicing/models.py`:

```python
class InvoiceLineItemSource(models.Model):
    SOURCE_BLEP = 'blep'
    SOURCE_MATERIAL = 'material'
    SOURCE_TASK = 'task'  # NEW: a whole task as one billing atom
    SOURCE_CHOICES = [
        (SOURCE_BLEP, 'Blep'),
        (SOURCE_MATERIAL, 'Material'),
        (SOURCE_TASK, 'Task'),
    ]
    # ...rest unchanged...
```

- [ ] **Step 3: Generate migration**

```
python manage.py makemigrations invoicing --name add_source_task
```

- [ ] **Step 4: Confirm migration is choice-only**

The migration should only `AlterField` the `source_type` choices; no real schema change since `source_type` is a CharField.

- [ ] **Step 5: Commit**

```
git add apps/invoicing/models.py apps/invoicing/migrations/
git commit -m "feat: add SOURCE_TASK choice to InvoiceLineItemSource"
```

---

### Task A16: Invoice wizard `get_source_pool` switches to per-task atoms

**Files:**
- Modify: `apps/invoicing/services.py:185-336` (`get_source_pool`)

- [ ] **Step 1: Write failing test**

Create `tests/test_invoice_wizard_per_task_atoms.py`:

```python
from decimal import Decimal
from tests.base import BaseTestCase


class WizardPerTaskAtomsTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory
        from apps.jobs.models import RateScheme, Job, Task, TaskCharge, Blep
        from apps.invoicing.models import Invoice
        from apps.contacts.models import Business, Contact
        from datetime import datetime, timedelta
        from django.utils import timezone

        self.ac = AccountingCategory.objects.create(code='X', name='X')
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm='elapsed_time', rate=Decimal('60'),
            unit_label='hours', accounting_category=self.ac,
        )
        biz = Business.objects.create(name='B')
        c = Contact.objects.create(first_name='F', last_name='L', business=biz)
        self.job = Job.objects.create(job_number='J', contact=c)
        self.task = Task.objects.create(job=self.job, name='Build')
        TaskCharge.objects.create(task=self.task, rate_scheme=self.scheme)
        # 30 minutes of work = $30
        now = timezone.now()
        Blep.objects.create(
            task=self.task,
            start_time=now - timedelta(minutes=30),
            end_time=now,
        )
        self.invoice = Invoice.objects.create(
            invoice_number='INV-1', job=self.job,
            status=Invoice.STATUS_DRAFT,
        )

    def test_pool_exposes_one_atom_per_task_with_charge_total(self):
        from apps.invoicing.services import InvoiceWizardService
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        # The Build task appears as a single 'task' atom with computed amount $30.00
        task_entries = [t for t in pool['tasks'] if t['task_id'] == self.task.pk]
        self.assertEqual(len(task_entries), 1)
        atoms = task_entries[0]['atoms']
        self.assertEqual(len(atoms), 1)
        atom = atoms[0]
        self.assertEqual(atom['atom_type'], 'task')
        self.assertEqual(atom['atom_id'], self.task.pk)
        self.assertEqual(atom['computed_amount'], Decimal('30.00'))

    def test_blep_visible_as_read_only_detail(self):
        from apps.invoicing.services import InvoiceWizardService
        pool = InvoiceWizardService.get_source_pool(self.invoice)
        task_entries = [t for t in pool['tasks'] if t['task_id'] == self.task.pk]
        # Bleps appear as detail metadata, not as atoms
        self.assertIn('bleps', task_entries[0])
        self.assertEqual(len(task_entries[0]['bleps']), 1)
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_invoice_wizard_per_task_atoms -v 2
```

- [ ] **Step 3: Refactor `get_source_pool`**

Replace the per-blep iteration in `apps/invoicing/services.py` `get_source_pool` with per-task atoms:

```python
    @staticmethod
    def get_source_pool(invoice):
        from apps.jobs.models import Task, Blep, TaskCharge
        from apps.inventory.models import Material
        from apps.invoicing.models import InvoiceLineItemSource

        job = invoice.job

        # Build claim lookup as before
        claimed_sources = (
            InvoiceLineItemSource.objects
            .filter(invoice_line_item__invoice__job=job)
            .exclude(invoice_line_item__invoice__status=Invoice.STATUS_CANCELLED)
            .select_related('invoice_line_item', 'invoice_line_item__invoice')
        )
        claims = {}
        for src in claimed_sources:
            li = src.invoice_line_item
            inv = li.invoice
            key = (src.source_type, src.source_pk)
            if inv.pk == invoice.pk:
                claims[key] = {
                    'state': 'claimed_by_current',
                    'claiming_line_item_id': li.pk,
                    'claiming_line_number': li.line_number,
                    'claiming_invoice_id': None,
                    'claiming_invoice_number': None,
                }
            else:
                claims[key] = {
                    'state': 'claimed_by_other',
                    'claiming_line_item_id': None,
                    'claiming_line_number': None,
                    'claiming_invoice_id': inv.pk,
                    'claiming_invoice_number': inv.invoice_number,
                }
        default_state = {
            'state': 'available',
            'claiming_line_item_id': None,
            'claiming_line_number': None,
            'claiming_invoice_id': None,
            'claiming_invoice_number': None,
        }

        tasks = (
            Task.objects.filter(job=job)
            .exclude(status=Task.STATUS_CANCELLED)
            .order_by('sort_order', 'pk')
            .select_related('charge', 'charge__rate_scheme')
        )
        task_list = []
        for task in tasks:
            atoms = []

            # The task itself is the atom (if it has a charge)
            try:
                charge = task.charge
            except TaskCharge.DoesNotExist:
                charge = None  # Phase A tolerance; Phase B will guarantee charge

            if charge is not None:
                amount = charge.compute().quantize(Decimal('0.01'))
                key = (InvoiceLineItemSource.SOURCE_TASK, task.pk)
                state_info = claims.get(key, default_state)
                atoms.append({
                    'atom_type': 'task',
                    'atom_id': task.pk,
                    'description': f'{task.name} ({charge.rate_scheme.name})',
                    'sub_info': WizardAtomLabels.qty_source_label(charge),
                    'computed_amount': amount,
                    **state_info,
                })

            # Material atoms still per-material
            materials = (
                Material.objects.filter(task=task, quantity__gt=0)
                .order_by('pk')
            )
            for mat in materials:
                amount = (mat.quantity * mat.sell_price).quantize(Decimal('0.01'))
                key = (InvoiceLineItemSource.SOURCE_MATERIAL, mat.pk)
                state_info = claims.get(key, default_state)
                atoms.append({
                    'atom_type': 'material',
                    'atom_id': mat.pk,
                    'description': mat.description,
                    'sub_info': '',
                    'computed_amount': amount,
                    **state_info,
                })

            # Bleps as read-only detail under each task
            bleps_detail = []
            for blep in Blep.objects.filter(task=task).exclude(end_time__isnull=True).order_by('start_time', 'pk'):
                elapsed = blep.end_time - blep.start_time
                hours = (Decimal(str(elapsed.total_seconds())) / Decimal('3600')).quantize(Decimal('0.01'))
                bleps_detail.append({
                    'blep_id': blep.pk,
                    'hours': hours,
                    'when': blep.start_time.strftime('%m/%d'),
                    'user': blep.user.username if blep.user else None,
                })

            task_list.append({
                'task_id': task.pk,
                'name': task.name,
                'has_billable_atoms': len(atoms) > 0,
                'atoms': atoms,
                'bleps': bleps_detail,
            })

        # "Materials (no task)" group as before
        loose = (
            Material.objects.filter(job=job, task__isnull=True, quantity__gt=0)
            .order_by('pk')
        )
        loose_atoms = []
        for mat in loose:
            amount = (mat.quantity * mat.sell_price).quantize(Decimal('0.01'))
            key = (InvoiceLineItemSource.SOURCE_MATERIAL, mat.pk)
            state_info = claims.get(key, default_state)
            loose_atoms.append({
                'atom_type': 'material',
                'atom_id': mat.pk,
                'description': mat.description,
                'sub_info': '',
                'computed_amount': amount,
                **state_info,
            })
        task_list.append({
            'task_id': None,
            'name': 'Materials (no task)',
            'has_billable_atoms': len(loose_atoms) > 0,
            'atoms': loose_atoms,
            'bleps': [],
        })

        return {'tasks': task_list}
```

Add helper class for the qty-source label:

```python
class WizardAtomLabels:
    @staticmethod
    def qty_source_label(charge):
        scheme = charge.rate_scheme
        if scheme.algorithm == 'elapsed_time':
            qty = scheme.get_actual_qty(charge.task)
            return f'{qty:.2f} {scheme.unit_label} from bleps'
        if scheme.algorithm == 'entered_qty':
            qty = scheme.get_actual_qty(charge.task)
            return f'{qty} {scheme.unit_label} entered'
        return 'flat fee'
```

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_invoice_wizard_per_task_atoms -v 2
```

- [ ] **Step 5: Update existing wizard tests that asserted blep atoms**

```
python manage.py test apps.invoicing tests.test_invoice -v 2 2>&1 | tail -30
```
Update any tests that asserted `atom_type == 'blep'` for billing atoms — they're now `'task'`.

- [ ] **Step 6: Commit**

```
git add apps/invoicing/services.py tests/test_invoice_wizard_per_task_atoms.py
git commit -m "feat: invoice wizard exposes per-task atoms via TaskCharge.compute()"
```

---

### Task A17: Wizard atom helpers (`_resolve_atom`, `_atom_computed_amount`, `_atom_category`, `_atom_source_type`) handle task atoms

**Files:**
- Modify: `apps/invoicing/services.py:342-390`

- [ ] **Step 1: Write failing test**

Append to `tests/test_invoice_wizard_per_task_atoms.py`:

```python
class WizardTaskAtomHelpersTest(WizardPerTaskAtomsTest):
    def test_resolve_task_atom(self):
        from apps.invoicing.services import InvoiceWizardService
        atom = InvoiceWizardService._resolve_atom({'type': 'task', 'id': self.task.pk})
        self.assertEqual(atom, self.task)

    def test_task_atom_computed_amount_uses_charge(self):
        from apps.invoicing.services import InvoiceWizardService
        amount = InvoiceWizardService._atom_computed_amount(self.task)
        self.assertEqual(amount, Decimal('30.00'))

    def test_task_atom_category_walks_through_charge_scheme(self):
        from apps.invoicing.services import InvoiceWizardService
        cat = InvoiceWizardService._atom_category(self.task)
        self.assertEqual(cat, self.ac)
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_invoice_wizard_per_task_atoms.WizardTaskAtomHelpersTest -v 2
```

- [ ] **Step 3: Update helpers**

In `apps/invoicing/services.py`:

```python
    @staticmethod
    def _resolve_atom(atom_ref):
        from apps.jobs.models import Blep, Task
        from apps.inventory.models import Material
        if atom_ref['type'] == 'blep':
            return Blep.objects.get(pk=atom_ref['id'])
        if atom_ref['type'] == 'material':
            return Material.objects.get(pk=atom_ref['id'])
        if atom_ref['type'] == 'task':
            return Task.objects.get(pk=atom_ref['id'])
        raise ValueError(f"Unknown atom type: {atom_ref['type']}")

    @staticmethod
    def _atom_computed_amount(atom_instance):
        from apps.jobs.models import Blep, Task, TaskCharge
        from apps.inventory.models import Material
        if isinstance(atom_instance, Task):
            try:
                return atom_instance.charge.compute().quantize(Decimal('0.01'))
            except TaskCharge.DoesNotExist:
                return Decimal('0.00')  # Phase A tolerance
        if isinstance(atom_instance, Blep):
            # Legacy path retained for any remaining InvoiceLineItemSource rows of type 'blep'
            if not atom_instance.end_time:
                return Decimal('0.00')
            elapsed = atom_instance.end_time - atom_instance.start_time
            hours = Decimal(str(elapsed.total_seconds())) / Decimal('3600')
            try:
                rate = atom_instance.task.charge.rate_scheme.rate
            except (TaskCharge.DoesNotExist, AttributeError):
                rate = atom_instance.task.rate or Decimal('0.00')  # Phase A fallback
            return (hours * rate).quantize(Decimal('0.01'))
        if isinstance(atom_instance, Material):
            return (atom_instance.quantity * atom_instance.sell_price).quantize(Decimal('0.01'))
        raise ValueError(f"Unknown atom instance type: {type(atom_instance)}")

    @staticmethod
    def _atom_category(atom_instance):
        from apps.jobs.models import Blep, Task
        from apps.inventory.models import Material
        if isinstance(atom_instance, Task):
            return atom_instance.effective_accounting_category
        if isinstance(atom_instance, Blep):
            return atom_instance.task.effective_accounting_category
        if isinstance(atom_instance, Material):
            return atom_instance.accounting_category
        return None

    @staticmethod
    def _atom_source_type(atom_instance):
        from apps.jobs.models import Blep, Task
        from apps.inventory.models import Material
        from apps.invoicing.models import InvoiceLineItemSource
        if isinstance(atom_instance, Task):
            return InvoiceLineItemSource.SOURCE_TASK
        if isinstance(atom_instance, Blep):
            return InvoiceLineItemSource.SOURCE_BLEP
        if isinstance(atom_instance, Material):
            return InvoiceLineItemSource.SOURCE_MATERIAL
        raise ValueError(f"Unknown atom instance type: {type(atom_instance)}")
```

- [ ] **Step 4: Update `InvoiceLineItemSource.resolve()` if it has type-dispatch**

```
grep -n "def resolve" apps/invoicing/models.py
```
If `resolve` has a type dispatch, add the `SOURCE_TASK → Task` case.

- [ ] **Step 5: Run, expect PASS**

```
python manage.py test tests.test_invoice_wizard_per_task_atoms -v 2
```

- [ ] **Step 6: Commit**

```
git add apps/invoicing/services.py apps/invoicing/models.py tests/test_invoice_wizard_per_task_atoms.py
git commit -m "feat: wizard atom helpers handle task atoms and use TaskCharge for category"
```

---

### Task A18: PlanTask serializer drops `accounting_category`

**Files:**
- Modify: `apps/api/plan_tasks/serializers.py`
- Modify: `apps/api/worksheets/serializers.py` (any nested PlanTask payload)

> **Phase A note:** drops the field from the *write* serializer so frontend stops sending it. The legacy DB column remains until Phase B.

- [ ] **Step 1: Write failing test**

Append to `tests/test_estimate_charge.py`:

```python
class PlanTaskSerializerNoACTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory, User
        from apps.jobs.models import RateScheme
        self.user = User.objects.create_user('u', 'u@x', 'pw')
        self.client.force_login(self.user)
        self.ac = AccountingCategory.objects.create(code='X', name='X')
        self.scheme = RateScheme.objects.create(
            name='S', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=self.ac,
        )

    def test_plan_task_detail_omits_accounting_category(self):
        from apps.jobs.models import Job, PlanTask
        from apps.estimates.models import EstWorksheet
        from apps.contacts.models import Business, Contact
        biz = Business.objects.create(name='B')
        c = Contact.objects.create(first_name='F', last_name='L', business=biz)
        job = Job.objects.create(job_number='J', contact=c)
        ws = EstWorksheet.objects.create(job=job)
        pt = PlanTask.objects.create(
            est_worksheet=ws, name='t',
            rate_scheme=self.scheme,
            estimated_billable_qty=Decimal('1'),
        )
        resp = self.client.get(f'/api/plan-tasks/{pt.pk}/')
        body = resp.json()
        self.assertNotIn('accounting_category', body)
        self.assertIn('rate_scheme', body)
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_estimate_charge.PlanTaskSerializerNoACTest -v 2
```

- [ ] **Step 3: Drop field**

In `apps/api/plan_tasks/serializers.py`, remove `'accounting_category'` from `PlanTaskDetailSerializer.Meta.fields`.

In `apps/api/worksheets/serializers.py`, find any PlanTask nested fields list and remove `accounting_category`.

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_estimate_charge.PlanTaskSerializerNoACTest -v 2
```

- [ ] **Step 5: Commit**

```
git add apps/api/plan_tasks/serializers.py apps/api/worksheets/serializers.py tests/test_estimate_charge.py
git commit -m "feat: drop accounting_category from PlanTask serializer payloads"
```

---

### Task A19: Task serializer drops AC + legacy fields from API output

**Files:**
- Modify: `apps/api/tasks/serializers.py`

> Drops `units`, `rate`, `est_qty`, `accounting_category` from the serializer Meta.fields. Frontend already gets `charge` nested for billing display.

- [ ] **Step 1: Write failing test**

Append to `tests/test_task_charge_api.py`:

```python
class TaskSerializerNoLegacyFieldsTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory, User
        from apps.jobs.models import RateScheme, Job, Task, TaskCharge
        from apps.contacts.models import Business, Contact
        self.user = User.objects.create_user('u', 'u@x', 'pw')
        self.client.force_login(self.user)
        ac = AccountingCategory.objects.create(code='X', name='X')
        scheme = RateScheme.objects.create(
            name='S', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        biz = Business.objects.create(name='B')
        c = Contact.objects.create(first_name='F', last_name='L', business=biz)
        self.job = Job.objects.create(job_number='J', contact=c)
        self.task = Task.objects.create(job=self.job, name='T')
        TaskCharge.objects.create(task=self.task, rate_scheme=scheme)

    def test_task_list_omits_legacy_fields(self):
        resp = self.client.get(f'/api/jobs/{self.job.pk}/tasks/')
        body = resp.json()
        first = body['results'][0] if 'results' in body else body[0]
        for legacy in ('units', 'rate', 'est_qty', 'accounting_category'):
            self.assertNotIn(legacy, first)
        self.assertIn('charge', first)
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_task_charge_api.TaskSerializerNoLegacyFieldsTest -v 2
```

- [ ] **Step 3: Update serializers**

In `apps/api/tasks/serializers.py`, in both `TaskSerializer` and `TaskDetailSerializer`, remove `units`, `rate`, `est_qty`, `accounting_category` from `fields`. Drop the `units = UnitsField()` declarations. Add `charge = serializers.SerializerMethodField()` to `TaskSerializer` (it's already in `TaskDetailSerializer`):

```python
class TaskSerializer(serializers.ModelSerializer):
    assignee_name = serializers.SerializerMethodField()
    charge = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'sort_order', 'status',
            'blocked_reason',
            'parent_task', 'assignee', 'assignee_name', 'worker_queue',
            'charge',
        ]
        read_only_fields = ['task_id', 'sort_order', 'status']

    def get_assignee_name(self, obj):
        if obj.assignee:
            name = obj.assignee.get_full_name()
            return name if name else obj.assignee.username
        return None

    def get_charge(self, obj):
        try:
            charge = obj.charge
        except TaskCharge.DoesNotExist:
            return None
        return TaskChargeReadSerializer(charge).data
```

`TaskDetailSerializer.Meta.fields` similarly drops the four legacy fields.

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_task_charge_api.TaskSerializerNoLegacyFieldsTest -v 2
```

- [ ] **Step 5: Update Task creation endpoint to accept rate_scheme + create TaskCharge**

In `apps/api/tasks/views.py`, find the POST `tasks/` handler. The create path should:
1. Accept `rate_scheme`, `active_modifiers`, optionally `actuals` from request data.
2. Delegate to `TaskService.create_direct(job, name, rate_scheme_id=..., active_modifiers=..., **other_fields)`.

Wire the validation error → API 400 mapping if not already in place.

- [ ] **Step 6: Commit**

```
git add apps/api/tasks/serializers.py apps/api/tasks/views.py tests/test_task_charge_api.py
git commit -m "feat: drop legacy billing fields from Task serializer; require rate_scheme on create"
```

---

### Task A20: TaskTemplate serializer drops `accounting_category`

**Files:**
- Modify: `apps/api/templates_config/serializers.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_task_charge_api.py`:

```python
class TaskTemplateSerializerNoACTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.core.models import AccountingCategory, User
        from apps.jobs.models import RateScheme
        from apps.estimates.models import TaskTemplate
        self.user = User.objects.create_user('u', 'u@x', 'pw')
        self.client.force_login(self.user)
        ac = AccountingCategory.objects.create(code='X', name='X')
        scheme = RateScheme.objects.create(
            name='S', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea', accounting_category=ac,
        )
        self.template = TaskTemplate.objects.create(
            template_name='T', rate_scheme=scheme,
            default_billable_qty=Decimal('1'),
        )

    def test_template_payload_omits_accounting_category(self):
        resp = self.client.get(f'/api/task-templates/{self.template.pk}/')
        body = resp.json()
        self.assertNotIn('accounting_category', body)
        self.assertIn('rate_scheme', body)
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_task_charge_api.TaskTemplateSerializerNoACTest -v 2
```

- [ ] **Step 3: Drop AC field**

In `apps/api/templates_config/serializers.py`, remove `'accounting_category'` from the TaskTemplate serializer's `Meta.fields`.

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_task_charge_api.TaskTemplateSerializerNoACTest -v 2
```

- [ ] **Step 5: Commit**

```
git add apps/api/templates_config/serializers.py tests/test_task_charge_api.py
git commit -m "feat: drop accounting_category from TaskTemplate serializer"
```

---

### Task A21: Frontend `RateSchemeFieldset.svelte` shared subcomponent

**Files:**
- Create: `frontend/src/components/RateSchemeFieldset.svelte`

- [ ] **Step 1: Create the component**

Write `frontend/src/components/RateSchemeFieldset.svelte`:

```svelte
<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';

  let { rateSchemeId = $bindable(''), activeModifiers = $bindable([]), estQty = $bindable('') } = $props();

  let schemes = $state([]);
  let loading = $state(true);
  let error = $state('');

  onMount(async () => {
    try {
      const resp = await api.get('/api/rate-schemes/');
      schemes = resp.results || resp;
    } catch (e) {
      error = e.message || 'Could not load rate schemes.';
    } finally {
      loading = false;
    }
  });

  let selectedScheme = $derived(
    schemes.find(s => s.rate_scheme_id === Number(rateSchemeId)) || null
  );

  function toggleModifier(key, checked) {
    if (checked) {
      if (!activeModifiers.includes(key)) {
        activeModifiers = [...activeModifiers, key];
      }
    } else {
      activeModifiers = activeModifiers.filter(k => k !== key);
    }
  }
</script>

{#if loading}
  <p>Loading rate schemes…</p>
{:else if error}
  <p style="color: red;">{error}</p>
{:else}
  <p>
    <label for="rate-scheme"><strong>Rate scheme *</strong></label><br>
    <select id="rate-scheme" bind:value={rateSchemeId} required>
      <option value="">-- select --</option>
      {#each schemes as s (s.rate_scheme_id)}
        <option value={s.rate_scheme_id}>{s.name}</option>
      {/each}
    </select>
  </p>

  {#if selectedScheme}
    <p>
      <strong>{selectedScheme.name}</strong> — ${selectedScheme.rate}/{selectedScheme.unit_label}
    </p>

    {#if selectedScheme.modifiers && selectedScheme.modifiers.length > 0}
      <fieldset>
        <legend><strong>Modifiers</strong></legend>
        {#each selectedScheme.modifiers as m (m.key)}
          <p>
            <label>
              <input
                type="checkbox"
                checked={activeModifiers.includes(m.key)}
                onchange={(e) => toggleModifier(m.key, e.target.checked)}
              />
              {m.label} (+{m.percent}%)
            </label>
          </p>
        {/each}
      </fieldset>
    {/if}

    <p>
      <label for="est-qty"><strong>Estimated qty *</strong></label><br>
      <input
        id="est-qty"
        type="number"
        step="0.01"
        bind:value={estQty}
        required
      />
    </p>
  {/if}
{/if}
```

- [ ] **Step 2: Manually verify in dev**

```
cd frontend && npm run dev
```
Browse to a route that hosts the component (will be wired in next tasks). For now, verify the file builds without error.

- [ ] **Step 3: Commit**

```
git add frontend/src/components/RateSchemeFieldset.svelte
git commit -m "feat: add RateSchemeFieldset shared subcomponent"
```

---

### Task A22: PlanTaskModal embeds RateSchemeFieldset and drops AC

**Files:**
- Modify: `frontend/src/components/PlanTaskModal.svelte`

> **Phase A naming note:** the model field is still called `estimated_billable_qty` during Phase A; it gets renamed to `est_qty` in Task B1. The `RateSchemeFieldset` exposes `estQty` as a prop name (a local Svelte variable), but the modal's API payload key during Phase A must be `estimated_billable_qty`. Phase B's B1 step 3 includes the Svelte payload-key rename.

- [ ] **Step 1: Replace the inline rate_scheme/AC/qty UI with RateSchemeFieldset**

Open `frontend/src/components/PlanTaskModal.svelte`. Remove:
- Local state for `accountingCategory`
- The accounting_category `<select>` block
- The inline rate_scheme `<select>` and modifier checkboxes and qty input

Import the new fieldset:

```svelte
<script>
  import RateSchemeFieldset from './RateSchemeFieldset.svelte';
  // remove accounting_category state
  let rateSchemeId = $state(task?.rate_scheme ?? '');
  let activeModifiers = $state(task?.active_modifiers ?? []);
  let estQty = $state(task?.estimated_billable_qty ?? '');
  // ...
</script>
```

Add to the form body:

```svelte
<RateSchemeFieldset
  bind:rateSchemeId
  bind:activeModifiers
  bind:estQty
/>
```

Update the save-payload construction. During Phase A, send the still-named field:

```javascript
const payload = {
  name,
  description,
  rate_scheme: rateSchemeId,
  active_modifiers: activeModifiers,
  estimated_billable_qty: estQty,  // Phase A; becomes est_qty in Task B1
};
// no accounting_category key
```

- [ ] **Step 2: Manually verify**

Restart the dev server, open a worksheet, attempt to add a PlanTask. The form should require a rate_scheme; AC field is gone.

- [ ] **Step 3: Commit**

```
git add frontend/src/components/PlanTaskModal.svelte
git commit -m "feat: PlanTaskModal uses RateSchemeFieldset; drops AC field"
```

---

### Task A23: TaskModal embeds RateSchemeFieldset and drops AC

**Files:**
- Modify: `frontend/src/components/TaskModal.svelte`

- [ ] **Step 1: Same treatment as PlanTaskModal**

Drop the accountingCategory state and AC `<select>`. Add `RateSchemeFieldset` with bindings; include in save payload as `rate_scheme`, `active_modifiers`, `est_qty`.

- [ ] **Step 2: Manually verify**

Open job task list page; "Add task" should require a rate_scheme; AC field gone.

- [ ] **Step 3: Commit**

```
git add frontend/src/components/TaskModal.svelte
git commit -m "feat: TaskModal uses RateSchemeFieldset; drops AC field"
```

---

### Task A24: SubtaskModal embeds RateSchemeFieldset

**Files:**
- Modify: `frontend/src/components/SubtaskModal.svelte`

- [ ] **Step 1: Same treatment**

- [ ] **Step 2: Manually verify on job task list**

- [ ] **Step 3: Commit**

```
git add frontend/src/components/SubtaskModal.svelte
git commit -m "feat: SubtaskModal uses RateSchemeFieldset"
```

---

### Task A25: TaskDetailPage removes AC display

**Files:**
- Modify: `frontend/src/routes/jobs/TaskDetailPage.svelte`

- [ ] **Step 1: Remove the AC display element entirely**

```
grep -n "accounting_category" frontend/src/routes/jobs/TaskDetailPage.svelte
```
For each match, delete the surrounding label + value rendering.

- [ ] **Step 2: Manually verify**

Open a Task detail page. AC should not be visible anywhere.

- [ ] **Step 3: Commit**

```
git add frontend/src/routes/jobs/TaskDetailPage.svelte
git commit -m "feat: remove AC display from TaskDetailPage"
```

---

### Task A26: RateSchemeManager uses unit_label dropdown and requires AC

**Files:**
- Modify: `frontend/src/components/RateSchemeManager.svelte`

- [ ] **Step 1: Load units list on mount**

Add to `onMount`:

```javascript
const unitsResp = await api.get('/api/settings/units/');
unitsList = unitsResp;  // expect array of strings
```

Replace the `unit_label` text input in the create/edit form with:

```svelte
<select bind:value={form.unit_label} required>
  <option value="">-- select --</option>
  {#each unitsList as u}
    <option value={u}>{u}</option>
  {/each}
</select>
```

Make the `accounting_category` `<select>` required (`required` attribute).

- [ ] **Step 2: Manually verify**

Open Settings → RateSchemes. Try to create a scheme: unit_label is a dropdown; AC is required.

- [ ] **Step 3: Commit**

```
git add frontend/src/components/RateSchemeManager.svelte
git commit -m "feat: RateSchemeManager uses unit_label dropdown and requires AC"
```

---

### Task A27: RateSchemeManager outdated-schemes tab + supersede flow

**Files:**
- Modify: `frontend/src/components/RateSchemeManager.svelte`

- [ ] **Step 1: Add view toggle and supersede UI**

Add state for `showSuperseded = $state(false)` and a tab/toggle in the UI. When `showSuperseded`, fetch from `/api/rate-schemes/?only_superseded=true`.

For each row in the active list, if `scheme.reference_counts.plan_task_count + task_charge_count + task_template_count > 0`, render a "Create new version" button instead of "Edit". Wire its click to open the same modal in supersede mode; on save, POST to `/api/rate-schemes/{id}/supersede/`.

- [ ] **Step 2: Show `replaced_by` and `replaced_at` in the superseded view**

Each superseded scheme row shows:
- name, replaced_at (formatted), reference_counts, link to its `replaced_by` scheme.

- [ ] **Step 3: Manually verify**

Create a scheme, reference it from a worksheet, then attempt edit → should offer "Create new version" → save → original scheme appears in the Superseded tab with a `replaced_at` timestamp and link to the new version.

- [ ] **Step 4: Commit**

```
git add frontend/src/components/RateSchemeManager.svelte
git commit -m "feat: RateSchemeManager outdated-schemes tab and supersede flow"
```

---

### Task A28: TaskTemplateManager drops AC field; warns on superseded scheme

**Files:**
- Modify: `frontend/src/components/TaskTemplateManager.svelte`

- [ ] **Step 1: Remove AC field from form**

Delete the accounting_category `<select>` and related state. The template's AC will be derived from its scheme; no field to edit.

- [ ] **Step 2: Add superseded-scheme warning**

Each template row that points at a superseded scheme renders an inline warning: "Scheme is superseded — update before use." Computed by checking `template.rate_scheme_detail?.superseded` (the API may need to nest this; if not, fetch the scheme separately or extend the serializer in a follow-up).

- [ ] **Step 3: Manually verify**

Open Settings → TaskTemplates. AC field gone. Templates pointing at superseded schemes show warning.

- [ ] **Step 4: Commit**

```
git add frontend/src/components/TaskTemplateManager.svelte
git commit -m "feat: TaskTemplateManager drops AC; warns on superseded scheme"
```

---

### Task A29: Invoice wizard frontend renders per-task atoms with bleps as detail

**Files:**
- Modify: `frontend/src/components/invoices/InvoiceDetail.svelte` (or whichever component renders the wizard atoms)

- [ ] **Step 1: Locate wizard atom rendering**

```
grep -rn "atom_type\|atom_id\|computed_amount\|get_source_pool\|source_pool" frontend/src/
```

- [ ] **Step 2: Update rendering**

For each task in the source pool:
- Show the task's name and any 'task' atom with its computed amount.
- Below it, render `bleps` array as a small read-only detail list: hours, date, user.
- Material atoms remain rendered as before.

Remove any code that mapped `atom_type === 'blep'` to a billable line.

- [ ] **Step 3: Manually verify**

Open a draft invoice for a job with bleps. Each task appears as one selectable atom; bleps show beneath as info.

- [ ] **Step 4: Commit**

```
git add frontend/src/components/invoices/InvoiceDetail.svelte
git commit -m "feat: invoice wizard frontend renders per-task atoms; bleps as detail"
```

---

### Task A30: Phase A end checkpoint — full test suite

- [ ] **Step 1: Run all tests**

```
python manage.py test -v 2 2>&1 | tail -40
```
Fix any regressions. Phase A should leave: new code paths active, old shapes still tolerated, all tests green.

- [ ] **Step 2: Manually verify the system in browser end-to-end**

```
python manage.py runserver
cd frontend && npm run dev
```
Test:
- Create a new RateScheme with AC and unit_label dropdown
- Add a PlanTask via worksheet — RateSchemeFieldset shown, AC absent
- Add a Task via TaskModal — same
- Reference a scheme, attempt to edit → see error / "Create new version" affordance
- Generate invoice — per-task atoms render

- [ ] **Step 3: Commit any frontend tweaks discovered**

```
git status
# review and commit any small fixes
```

- [ ] **Step 4: Tag the Phase A end commit**

```
git tag phase-a-complete
```

---

## Pause Phase — manual data fix

> **Phase A is complete. Phase B will tighten constraints and drop columns. Before Phase B, the dev DB must be cleaned up so the constraint changes succeed.**

### Task P1: `check_billing_data` management command

**Files:**
- Create: `apps/jobs/management/__init__.py` (if absent)
- Create: `apps/jobs/management/commands/__init__.py` (if absent)
- Create: `apps/jobs/management/commands/check_billing_data.py`
- Create: `tests/test_check_billing_data.py`

- [ ] **Step 1: Write failing test**

`tests/test_check_billing_data.py`:

```python
from io import StringIO
from decimal import Decimal
from django.core.management import call_command
from tests.base import BaseTestCase


class CheckBillingDataTest(BaseTestCase):
    fixtures = []

    def test_clean_db_reports_all_clear(self):
        out = StringIO()
        call_command('check_billing_data', stdout=out)
        text = out.getvalue()
        self.assertIn('All clear', text)

    def test_reports_ratescheme_without_ac(self):
        from apps.jobs.models import RateScheme
        # bypass clean() because that's the very condition we're checking
        RateScheme.objects.create(
            name='NoAC', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea',
        )
        out = StringIO()
        call_command('check_billing_data', stdout=out)
        self.assertIn('RateScheme', out.getvalue())
        self.assertIn('without accounting_category', out.getvalue())

    def test_reports_planTask_without_scheme(self):
        from apps.jobs.models import PlanTask, Job
        from apps.estimates.models import EstWorksheet
        from apps.contacts.models import Business, Contact
        biz = Business.objects.create(name='B')
        c = Contact.objects.create(first_name='F', last_name='L', business=biz)
        job = Job.objects.create(job_number='J', contact=c)
        ws = EstWorksheet.objects.create(job=job)
        PlanTask.objects.create(est_worksheet=ws, name='no scheme')
        out = StringIO()
        call_command('check_billing_data', stdout=out)
        self.assertIn('PlanTask', out.getvalue())
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_check_billing_data -v 2
```

- [ ] **Step 3: Implement**

`apps/jobs/management/commands/check_billing_data.py`:

```python
from django.core.management.base import BaseCommand
from apps.jobs.models import RateScheme, PlanTask, Task, TaskCharge
from apps.estimates.models import TaskTemplate


class Command(BaseCommand):
    help = 'Read-only diagnostic: report rows that will not survive Phase B constraints.'

    def handle(self, *args, **options):
        issues = []

        # RateScheme.accounting_category will become NOT NULL
        ratescheme_no_ac = RateScheme.objects.filter(accounting_category__isnull=True)
        if ratescheme_no_ac.exists():
            issues.append(
                f'{ratescheme_no_ac.count()} RateScheme(s) without accounting_category: '
                f'{list(ratescheme_no_ac.values_list("rate_scheme_id", "name"))}'
            )

        # PlanTask.rate_scheme will become NOT NULL
        planTask_no_scheme = PlanTask.objects.filter(rate_scheme__isnull=True)
        if planTask_no_scheme.exists():
            issues.append(
                f'{planTask_no_scheme.count()} PlanTask(s) without rate_scheme: '
                f'{list(planTask_no_scheme.values_list("plan_task_id", "name"))}'
            )

        # PlanTask.estimated_billable_qty will be renamed to est_qty (NOT NULL)
        planTask_no_qty = PlanTask.objects.filter(estimated_billable_qty__isnull=True)
        if planTask_no_qty.exists():
            issues.append(
                f'{planTask_no_qty.count()} PlanTask(s) without estimated_billable_qty: '
                f'{list(planTask_no_qty.values_list("plan_task_id", "name"))}'
            )

        # TaskTemplate.rate_scheme + default_billable_qty NOT NULL
        tt_no_scheme = TaskTemplate.objects.filter(rate_scheme__isnull=True)
        if tt_no_scheme.exists():
            issues.append(
                f'{tt_no_scheme.count()} TaskTemplate(s) without rate_scheme: '
                f'{list(tt_no_scheme.values_list("template_id", "template_name"))}'
            )
        tt_no_qty = TaskTemplate.objects.filter(default_billable_qty__isnull=True)
        if tt_no_qty.exists():
            issues.append(
                f'{tt_no_qty.count()} TaskTemplate(s) without default_billable_qty: '
                f'{list(tt_no_qty.values_list("template_id", "template_name"))}'
            )

        # Every Task must have a TaskCharge
        tasks_no_charge = Task.objects.filter(charge__isnull=True)
        if tasks_no_charge.exists():
            issues.append(
                f'{tasks_no_charge.count()} Task(s) without TaskCharge: '
                f'{list(tasks_no_charge.values_list("task_id", "name")[:20])}'
                f'{"..." if tasks_no_charge.count() > 20 else ""}'
            )

        # AC mismatches between work item and scheme (informational)
        for pt in PlanTask.objects.filter(rate_scheme__isnull=False):
            if pt.accounting_category_id and pt.accounting_category_id != pt.rate_scheme.accounting_category_id:
                issues.append(
                    f'PlanTask {pt.pk} ({pt.name}): AC differs from scheme — '
                    f'pt.AC={pt.accounting_category_id}, scheme.AC={pt.rate_scheme.accounting_category_id}'
                )

        if not issues:
            self.stdout.write(self.style.SUCCESS('All clear — dev DB is ready for Phase B.'))
        else:
            self.stdout.write(self.style.WARNING('Issues found — fix before Phase B:'))
            for issue in issues:
                self.stdout.write(f'  - {issue}')
```

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_check_billing_data -v 2
```

- [ ] **Step 5: Commit**

```
git add apps/jobs/management/ tests/test_check_billing_data.py
git commit -m "feat: check_billing_data diagnostic command for pre-Phase-B validation"
```

---

### Task P2: Developer pause — fix dev data

> **THIS TASK IS NOT AUTOMATED.** It is a checkpoint requiring human action.

- [ ] **Step 1: Run the diagnostic**

```
python manage.py check_billing_data
```

- [ ] **Step 2: Fix any reported issues**

For each issue, the developer chooses one of:
- Edit the row in Django admin or via the SPA Settings UI
- Hand-write a small fixture-augmenting script
- If there are too many: re-seed from `fixtures/large_datasets/nealseed.json` (the user has already updated it for this work)

- [ ] **Step 3: Re-run the diagnostic until clean**

```
python manage.py check_billing_data
```
Expected: `All clear — dev DB is ready for Phase B.`

- [ ] **Step 4: Commit any fixture or script that resulted from this**

```
git status
# commit any fixture/script work
```

---

## Phase B — constraint tightening, column drops, immutability enforcement

> **Phase B prerequisites:** Phase A is committed and merged; Pause phase complete; `check_billing_data` reports All clear.

### Task B1: Migration — rename `PlanTask.estimated_billable_qty` → `est_qty`

**Files:**
- Modify: `apps/jobs/models.py` (PlanTask.estimated_billable_qty → est_qty)
- Create: `apps/jobs/migrations/00XX_planTask_rename_est_qty.py`

- [ ] **Step 1: Rename field in model**

In `apps/jobs/models.py`, in `class PlanTask`, change:

```python
    estimated_billable_qty = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )
```

to:

```python
    est_qty = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
    )
```

- [ ] **Step 2: Generate migration**

```
python manage.py makemigrations jobs --name planTask_rename_est_qty
```
Django should auto-detect the rename. Confirm with `python manage.py makemigrations --dry-run`.

- [ ] **Step 3: Update every reader of `estimated_billable_qty`**

```
grep -rn "estimated_billable_qty" apps/ frontend/src/ tests/ scripts/
```
Replace with `est_qty` in every Python and Svelte location:
- `apps/jobs/models.py` (any methods)
- `apps/estimates/services.py` (`add_task_from_template`, `add_task_manual` callers)
- `apps/api/plan_tasks/serializers.py`
- `apps/api/worksheets/serializers.py`
- `frontend/src/components/PlanTaskModal.svelte`
- `frontend/src/components/RateSchemeFieldset.svelte` (the bound prop name)
- All tests

- [ ] **Step 4: Run all tests**

```
python manage.py test -v 2 2>&1 | tail -30
```

- [ ] **Step 5: Commit**

```
git add apps/jobs/models.py apps/jobs/migrations/ apps/estimates/services.py apps/api/ frontend/src/ tests/
git commit -m "refactor: rename PlanTask.estimated_billable_qty to est_qty"
```

---

### Task B2: Migration — tighten NOT NULL on `RateScheme.accounting_category`

**Files:**
- Modify: `apps/jobs/models.py`

- [ ] **Step 1: Update model**

```python
    accounting_category = models.ForeignKey(
        'core.AccountingCategory', on_delete=models.PROTECT,
    )
```
(Remove `null=True, blank=True`.)

- [ ] **Step 2: Generate migration**

```
python manage.py makemigrations jobs --name ratescheme_ac_required
```

- [ ] **Step 3: Run tests**

```
python manage.py test -v 2 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

```
git add apps/jobs/models.py apps/jobs/migrations/
git commit -m "feat: RateScheme.accounting_category NOT NULL"
```

---

### Task B3: Migration — tighten NOT NULL on `PlanTask.rate_scheme` and `est_qty`

**Files:**
- Modify: `apps/jobs/models.py`

- [ ] **Step 1: Update model**

```python
    rate_scheme = models.ForeignKey(
        'jobs.RateScheme', on_delete=models.PROTECT,
    )
    # ...
    est_qty = models.DecimalField(max_digits=10, decimal_places=2)
```
(Remove `null=True, blank=True` from both.)

- [ ] **Step 2: Generate migration**

```
python manage.py makemigrations jobs --name planTask_billing_required
```

- [ ] **Step 3: Run tests**

```
python manage.py test -v 2 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

```
git add apps/jobs/models.py apps/jobs/migrations/
git commit -m "feat: PlanTask.rate_scheme and est_qty NOT NULL"
```

---

### Task B4: Migration — tighten NOT NULL on `TaskTemplate.rate_scheme` and `default_billable_qty`

**Files:**
- Modify: `apps/estimates/models.py`

- [ ] **Step 1: Update model**

```python
    rate_scheme = models.ForeignKey(
        'jobs.RateScheme', on_delete=models.PROTECT,
    )
    # ...
    default_billable_qty = models.DecimalField(max_digits=10, decimal_places=2)
```

- [ ] **Step 2: Generate migration**

```
python manage.py makemigrations estimates --name tasktemplate_billing_required
```

- [ ] **Step 3: Run tests**

```
python manage.py test -v 2 2>&1 | tail -20
```

- [ ] **Step 4: Commit**

```
git add apps/estimates/models.py apps/estimates/migrations/
git commit -m "feat: TaskTemplate.rate_scheme and default_billable_qty NOT NULL"
```

---

### Task B5: Migration — drop `Task.rate`, `Task.units`, `Task.est_qty`

**Files:**
- Modify: `apps/jobs/models.py` (Task class)

- [ ] **Step 1: Remove fields from model**

In `apps/jobs/models.py`, in `class Task`, delete:

```python
    units = models.CharField(max_length=50, default='none')
    rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    est_qty = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
```

- [ ] **Step 2: Find and remove every reader of these fields**

```
grep -rn "task\.rate\|task\.units\|task\.est_qty\|\.rate \|\.units \|\.est_qty" apps/ frontend/src/ tests/ scripts/
```
Address each match. Notably:
- `apps/invoicing/services.py` `_atom_computed_amount` Phase-A fallback for blep — remove the `task.rate` fallback branch
- `apps/estimates/models.py` `TaskTemplate.generate_task` Job branch — remove `units=self.units`, `rate=self.rate`, `est_qty=est_qty` from the `Task.objects.create()` call
- `apps/jobs/services.py` any reader

- [ ] **Step 3: Generate migration**

```
python manage.py makemigrations jobs --name drop_task_legacy_billing_fields
```

- [ ] **Step 4: Run all tests**

```
python manage.py test -v 2 2>&1 | tail -30
```

- [ ] **Step 5: Commit**

```
git add apps/jobs/models.py apps/jobs/migrations/ apps/invoicing/services.py apps/estimates/models.py apps/jobs/services.py
git commit -m "refactor: drop Task.rate/units/est_qty; remove all readers"
```

---

### Task B6: Migration — drop `accounting_category` from PlanTask, Task, TaskTemplate

**Files:**
- Modify: `apps/jobs/models.py` (TaskBase)
- Modify: `apps/estimates/models.py` (TaskTemplate)

- [ ] **Step 1: Remove field from TaskBase**

In `apps/jobs/models.py`, in `class TaskBase`, delete:

```python
    accounting_category = models.ForeignKey(
        'core.AccountingCategory', ...
    )
```

- [ ] **Step 2: Remove field from TaskTemplate**

In `apps/estimates/models.py`, in `class TaskTemplate`, delete the `accounting_category` field. Also drop `units` and `rate` if still present:

```python
    # delete: units = models.CharField(max_length=50, default='none')
    # delete: rate = models.DecimalField(...)
    # delete: accounting_category = models.ForeignKey(...)
```

- [ ] **Step 3: Update `effective_accounting_category` properties to drop the Phase A fallback**

In `apps/jobs/models.py`:

```python
    # PlanTask
    @property
    def effective_accounting_category(self):
        return self.rate_scheme.accounting_category

    # Task
    @property
    def effective_accounting_category(self):
        return self.charge.rate_scheme.accounting_category
```

In `apps/estimates/models.py`:

```python
    # TaskTemplate
    @property
    def effective_accounting_category(self):
        return self.rate_scheme.accounting_category
```

- [ ] **Step 4: Drop AC writes from any service**

```
grep -rn "accounting_category=" apps/jobs/services.py apps/estimates/services.py apps/estimates/models.py
```
Remove any `accounting_category=...` from `Task.objects.create(...)` and `PlanTask.objects.create(...)` calls.

- [ ] **Step 5: Drop AC from forms (if any HTML form references it on Task/PlanTask/TaskTemplate)**

```
grep -rn "accounting_category" apps/jobs/forms.py apps/estimates/forms.py 2>/dev/null
```

- [ ] **Step 6: Generate migrations**

```
python manage.py makemigrations jobs estimates --name drop_workitem_ac_fields
```
Two migrations may be generated (one per app); confirm.

- [ ] **Step 7: Run all tests**

```
python manage.py test -v 2 2>&1 | tail -30
```

- [ ] **Step 8: Commit**

```
git add apps/jobs/models.py apps/estimates/models.py apps/jobs/migrations/ apps/estimates/migrations/ apps/jobs/services.py apps/estimates/services.py apps/jobs/forms.py apps/estimates/forms.py
git commit -m "refactor: drop accounting_category from PlanTask, Task, TaskTemplate"
```

---

### Task B7: Promote `Task.clean()` charge-required check

**Files:**
- Modify: `apps/jobs/models.py` (Task class)

- [ ] **Step 1: Write failing test**

Append to `tests/test_task_charge_required.py`:

```python
class TaskCleanRequiresChargeTest(BaseTestCase):
    fixtures = []

    def setUp(self):
        super().setUp()
        from apps.jobs.models import Job
        from apps.contacts.models import Business, Contact
        biz = Business.objects.create(name='B')
        c = Contact.objects.create(first_name='F', last_name='L', business=biz)
        self.job = Job.objects.create(job_number='J', contact=c)

    def test_task_full_clean_raises_when_no_charge(self):
        from django.core.exceptions import ValidationError
        from apps.jobs.models import Task
        t = Task.objects.create(job=self.job, name='no charge')
        with self.assertRaises(ValidationError):
            t.full_clean()
```

- [ ] **Step 2: Run, expect FAIL**

```
python manage.py test tests.test_task_charge_required.TaskCleanRequiresChargeTest -v 2
```

- [ ] **Step 3: Promote the placeholder**

In `apps/jobs/models.py`, in `class Task`, replace the commented-out Phase B block with:

```python
    def clean(self):
        super().clean()
        if self.pk and not hasattr(self, 'charge'):
            from django.core.exceptions import ValidationError
            raise ValidationError(
                {'charge': 'Required: every Task must have a TaskCharge.'}
            )
```

- [ ] **Step 4: Run, expect PASS**

```
python manage.py test tests.test_task_charge_required.TaskCleanRequiresChargeTest -v 2
```

- [ ] **Step 5: Run full test suite, fix regressions**

```
python manage.py test -v 2 2>&1 | tail -30
```
Any test that creates a Task without a TaskCharge is now broken — fix by also creating the TaskCharge in the test.

- [ ] **Step 6: Commit**

```
git add apps/jobs/models.py tests/test_task_charge_required.py
git commit -m "feat: Task.clean() requires TaskCharge"
```

---

### Task B8: Remove Phase A tolerance branches from invoice wizard

**Files:**
- Modify: `apps/invoicing/services.py`

- [ ] **Step 1: Find and remove tolerance branches**

In `apps/invoicing/services.py`:

```python
# In get_source_pool, the "if charge is not None" guard:
# Was: try: charge = task.charge; except TaskCharge.DoesNotExist: charge = None
# Phase B: charge always exists (Task.clean() requires it)
charge = task.charge  # raises if missing — that's a bug to investigate, not tolerate

# In _atom_computed_amount, the Blep branch's task.rate fallback already removed in Task B5.
# The Task branch's TaskCharge.DoesNotExist fallback should be removed:
if isinstance(atom_instance, Task):
    return atom_instance.charge.compute().quantize(Decimal('0.01'))
```

- [ ] **Step 2: Run all tests**

```
python manage.py test -v 2 2>&1 | tail -20
```

- [ ] **Step 3: Commit**

```
git add apps/invoicing/services.py
git commit -m "refactor: remove Phase A tolerance branches from invoice wizard"
```

---

### Task B9: Remove `effective_accounting_category` Phase A fallback verification

**Files:**
- Modify: `apps/jobs/models.py`, `apps/estimates/models.py`

Already done in Task B6 — this task is a verification pass.

- [ ] **Step 1: Verify no `accounting_category` legacy references survive**

```
grep -rn "self\.accounting_category\b" apps/jobs/models.py apps/estimates/models.py
```
Should return only references on Material, PriceListItem, Expense, BillLineItem — work-item models should have none.

- [ ] **Step 2: Commit (if any cleanup needed)**

If the grep found stragglers, fix and commit:

```
git add apps/jobs/models.py apps/estimates/models.py
git commit -m "refactor: scrub remaining work-item AC fallback references"
```

---

### Task B10: Phase B end checkpoint — full test suite + manual verification

- [ ] **Step 1: Run all tests**

```
python manage.py test -v 2 2>&1 | tail -40
```

- [ ] **Step 2: Manually verify in browser end-to-end**

```
python manage.py runserver
cd frontend && npm run dev
```

Test the same scenarios as Task A30, plus:
- Confirm no `accounting_category` field appears anywhere on a Task/PlanTask/TaskTemplate UI
- Confirm `Task.units`, `Task.rate`, `Task.est_qty` are nowhere referenced in the API responses
- Generate an invoice — wizard works with per-task atoms and `task.charge.compute()`
- Try editing a referenced scheme → API returns 409 with supersede URL
- Use `supersede` from the UI; original scheme appears in Superseded tab with `replaced_at`

- [ ] **Step 3: Tag**

```
git tag phase-b-complete
```

- [ ] **Step 4: Remove the now-stale prep doc**

```
git rm docs/plans/charge-thinking.md
git commit -m "chore: remove charge-thinking prep doc; superseded by design + plan"
```

---

## Notes for the executor

- The plan touches dozens of files. Prefer commits per step rather than per task — commits are cheap and a tight history helps when bisecting failures.
- Tests share one MySQL test database. Never run `python manage.py test` from multiple workers in parallel.
- Migrations are created (`makemigrations`) but never applied (`migrate`) by an agent — the human applies them.
- When in doubt about whether a Phase A change should also tighten a constraint, defer to Phase B. The whole point of the split is to keep Phase A non-breaking.
- The Pause Phase is human-driven. An agent stops at Task P2 and waits.
