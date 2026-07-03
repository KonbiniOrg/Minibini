# Implementation Plan — Part 1: Deferred service-pick crystallization (atom-on-approval)

> **TDD implementation plan.** Second of three sequenced plans
> (Plan 1 = `is_material` marker + provisional-Material branch → **THIS** → Plan 3 = unified picker).
> Authoritative design: `docs/plans/2026-07-02-add-line-crystallization-and-unified-picker.md`
> **Part 1** (Background, the service descriptor, symmetric three-way crystallization,
> "How a deferred service line behaves — snapshot at instantiation", "Price changes are a
> human event — no software guards", Settled decisions). Part 2 of that doc is Plan 3, out of scope here.
>
> Branch: `feature/unification`. Do NOT branch/worktree/commit at the end — the human reviews and commits.

## Goal

Make the estimate **service pick deferred** (atom-on-approval), matching the already-deferred
inventory + hand paths. Today an estimate service pick (`AddServiceItemModal` →
`add-from-template` → `line-items-from-atoms`) creates a **Task on the Job immediately**. After this
plan, the pick mints only a **document line** carrying a `service_item` descriptor plus snapshotted
priced values (`price`, `accounting_category`, `units`, editable `description`), and the **Task is
crystallized only at acceptance** by `on_accept`. The estimate stays a pure document until accepted.

## Architecture

- **Descriptor field.** `EstimateLineItem.service_item` FK (→ `estimates.ServiceItem`, `PROTECT`,
  nullable), parallel to the existing `BaseLineItem.inventory_item` descriptor. Scoped to
  `EstimateLineItem` (not `BaseLineItem`) — only estimates crystallize a service pick into a `Task`;
  invoices bill actuals and never generate work.
- **Snapshot at instantiation.** `EstimateService.add_line_item_from_service(estimate_pk,
  service_item_pk, qty)` mirrors `add_line_item_from_pli`: it snapshots `price =
  rate_scheme.effective_rate(default_active_modifiers)`, `accounting_category =
  service_item.effective_accounting_category`, `units = rate_scheme.unit_label or 'none'`, and an
  **editable** `description` prefilled from `service_item.template_name`. The line's amount is plain
  `qty × price`; the `service_item` FK stays on the line purely as the **crystallization target**, not
  a live price source.
- **Symmetric three-way (four-branch) crystallization.** `EstimateAcceptanceService.on_accept` gains a
  `service_item → Task` branch placed **first**, above the inventory / `is_material` / fee branches:
  `service_item.generate_task(job, est_qty=li.qty, description=li.description,
  allow_superseded_scheme=True)`, then source-link `EstimateLineItemSource(SOURCE_TASK)`.
  `Task.name` = ServiceItem template name (fresh from the FK); `Task.description` = the line's
  (editable) description.
- **No price-change guards.** Deriving `price` at instantiation *is* the freeze. A superseded scheme is
  handled only by passing `allow_superseded_scheme=True` so acceptance does not abort with
  `SchemeSupersededError`. No soft-flag, no honor/block decision, no re-pick prompt — divergence
  surfaces on the Task and at invoice (billed actuals), where a human is already looking.
- **API + UI.** A dedicated `line-items-from-service` action on `EstimateViewSet` (parallel to
  `line-items-from-atoms`). `AddServiceItemModal.svelte` repoints to it (interim, until Plan 3's
  unified picker replaces the modal). The **job task-list** surface's immediate `add-from-template`
  stays untouched.

## Tech Stack

- Backend: Django 5.2, DRF, MySQL, Python 3.12. Service-layer business logic; thin DRF viewsets.
- Frontend: Svelte 5 SPA (runes), Vitest for component tests.
- Tests: Django `TestCase` in `tests/`; Vitest in `frontend/tests/`.

## Global Constraints

- **TDD**: write a failing test first, run it, confirm it fails for the expected reason, then write the
  minimal implementation, run it green, commit. Real test + impl code below — no placeholders.
- **Test commands**: run e.g. `python manage.py test tests.test_deferred_service_crystallization`.
  **NEVER** pipe test output to `tail`; **NEVER** use `--keepdb`. Read the `OK` / `FAILED (...)`
  summary line and the `Ran N tests` count directly.
- **Never write the dev DB**: `python manage.py makemigrations` is OK; **never** run `migrate`,
  `loaddata`, or shell/`python -c` ORM writes. Tests build and tear down their own test DB.
- **Model constants, not string literals** (e.g. `EstimateLineItemSource.SOURCE_TASK`,
  `Estimate.STATUS_DRAFT`).
- **Document numbers** only generated for new instances (`if not instance.pk:`) — not touched here.
- **DELETE responses** return 200 with a JSON body — not relevant to the new endpoints (all POST), but
  keep in mind if you touch any destroy path.
- **Line-item deletes** go through `LineItemService.delete_line_item_with_renumber` — not touched here.
- After the feature lands, update `docs/designs/estimates-and-prices.md` (deferred service pick +
  three-way crystallization) in the same session.

## Dependency on Plan 1 (assumed landed)

This plan assumes Plan 1 has already added `EstimateLineItem.is_material` and the **provisional-Material**
branch to `on_accept`. Your `service_item → Task` branch sits **above** that `is_material` bare branch.
If Plan 1 has **not** actually landed when you start (see Assumptions in the closing note — the working
tree at authoring time had no `is_material`), Task 5's `on_accept` edit still applies, but the final
discriminator order becomes `service_item → inventory_item → Fee` (three branches) and the `is_material`
branch is inserted by Plan 1 between inventory and Fee. Either way, **place the service branch first**.

## File Structure

```
apps/estimates/models.py                          # + service_item FK on EstimateLineItem (Task 1)
                                                  # + allow_superseded_scheme param on ServiceItem.generate_task (Task 3)
apps/estimates/migrations/0039_*.py               # makemigrations output (Task 1) — do NOT migrate
apps/estimates/services.py                        # + EstimateService.add_line_item_from_service (Task 2)
apps/estimates/acceptance.py                      # + service_item → Task branch, placed first (Task 5)
apps/api/estimates/views.py                       # + line-items-from-service action (Task 4)
apps/api/estimates/serializers.py                 # + service_item field + service_item_detail (Task 6)
frontend/src/components/estimates/AddServiceItemModal.svelte   # repoint to new endpoint (Task 8)

tests/test_deferred_service_crystallization.py    # new backend test module (Tasks 2–7)
frontend/tests/components/estimates/AddServiceItemModal.test.js  # rewritten (Task 8)
```

---

## Task 1 — Add the `service_item` descriptor FK to `EstimateLineItem`

**Files**
- `apps/estimates/models.py` (`EstimateLineItem`, ~471)
- `apps/estimates/migrations/0039_*.py` (generated)

**Interface**
```python
service_item = models.ForeignKey(
    'estimates.ServiceItem',
    null=True, blank=True,
    on_delete=models.PROTECT,
    related_name='+',
    help_text='Deferred service descriptor: crystallizes to a Task at acceptance.',
)
```

**TDD steps**

- [ ] **Failing test** — add to a new module `tests/test_deferred_service_crystallization.py`. This
  first test just proves the field exists and defaults to null:
  ```python
  from decimal import Decimal
  from django.test import TestCase

  from apps.contacts.models import Contact
  from apps.core.models import AccountingCategory, Configuration, AppState
  from apps.estimates.models import Estimate, EstimateLineItem, ServiceItem
  from apps.jobs.models import Job, RateScheme


  class DeferredServiceBase(TestCase):
      def setUp(self):
          Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
          Configuration.objects.create(key='estimate_counter', value='0')
          Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
          AppState.objects.create(key='job_counter', value='0')

          self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
          self.contact = Contact.objects.create(
              first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
          )
          self.job = Job.objects.create(
              contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
          )
          self.scheme = RateScheme.objects.create(
              name='Hourly', algorithm=RateScheme.ENTERED_QTY,
              rate=Decimal('40'), unit_label='hour', accounting_category=self.cat,
          )
          self.service_item = ServiceItem.objects.create(
              template_name='CAM coding', description='tmpl desc',
              rate_scheme=self.scheme, default_active_modifiers=[],
          )
          self.estimate = Estimate.objects.create(
              job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT,
          )


  class ServiceItemFieldTest(DeferredServiceBase):
      def test_line_can_carry_service_item_and_defaults_null(self):
          bare = EstimateLineItem.objects.create(
              estimate=self.estimate, line_number=1, description='x',
              qty=Decimal('1'), price=Decimal('0'), accounting_category=self.cat,
          )
          self.assertIsNone(bare.service_item)
          line = EstimateLineItem.objects.create(
              estimate=self.estimate, line_number=2, description='CAM coding',
              qty=Decimal('1'), price=Decimal('40'), accounting_category=self.cat,
              service_item=self.service_item,
          )
          line.refresh_from_db()
          self.assertEqual(line.service_item_id, self.service_item.pk)
  ```
- [ ] **Run, expect FAIL** — `python manage.py test tests.test_deferred_service_crystallization`.
  Expected failure: `TypeError`/`FieldError` — `EstimateLineItem` has no `service_item`.
- [ ] **Implement** — add the FK (above `class Meta`) in `EstimateLineItem`:
  ```python
  service_item = models.ForeignKey(
      'estimates.ServiceItem',
      null=True, blank=True,
      on_delete=models.PROTECT,
      related_name='+',
      help_text='Deferred service descriptor: crystallizes to a Task at acceptance.',
  )
  ```
- [ ] **Migration** — `python manage.py makemigrations estimates` (creates `0039_*`). **Do NOT run
  `migrate`.** Verify the migration adds `service_item` as a nullable `PROTECT` FK.
- [ ] **Run, expect PASS** — `python manage.py test tests.test_deferred_service_crystallization`.
  The test DB is built fresh from migrations; confirm `OK`, `Ran 1 test`.
- [ ] **Commit** — `feat(estimates): add deferred service_item descriptor to EstimateLineItem`.

---

## Task 2 — `EstimateService.add_line_item_from_service` (snapshot at instantiation)

**Files**
- `apps/estimates/services.py` (mirror `add_line_item_from_pli`, ~289)
- `tests/test_deferred_service_crystallization.py`

**Interface**
```python
@staticmethod
def add_line_item_from_service(estimate_pk, service_item_pk, qty):
    """Add a deferred service line to a draft estimate. Snapshots priced values
    from the ServiceItem at instantiation; mints NO Task (that happens at accept)."""
    # returns the saved EstimateLineItem
```
Snapshot rules:
- `price = service_item.rate_scheme.effective_rate(service_item.default_active_modifiers)`
- `accounting_category = service_item.effective_accounting_category`
- `units = service_item.rate_scheme.unit_label or 'none'`
- `description = service_item.template_name` (editable afterward)
- `qty` carries `est_qty`; amount is `qty × price` (no live scheme lookup).

**TDD steps**

- [ ] **Failing test** — append to `tests/test_deferred_service_crystallization.py`:
  ```python
  from apps.estimates.services import EstimateService
  from apps.core.services import NotFoundError
  from django.core.exceptions import ValidationError


  class AddLineFromServiceTest(DeferredServiceBase):
      def test_snapshots_priced_values_and_creates_no_task(self):
          from apps.jobs.models import Task
          # base 40 + 10% modifier -> 44.00 effective unit rate
          self.scheme.modifiers = [{'key': 'rush', 'percent': 10}]
          self.scheme.save()
          self.service_item.default_active_modifiers = ['rush']
          self.service_item.save()

          line = EstimateService.add_line_item_from_service(
              self.estimate.pk, self.service_item.pk, Decimal('2'),
          )
          line.refresh_from_db()
          self.assertEqual(line.service_item_id, self.service_item.pk)
          self.assertEqual(line.price, Decimal('44.00'))          # effective_rate snapshot
          self.assertEqual(line.qty, Decimal('2'))
          self.assertEqual(line.accounting_category_id, self.cat.pk)
          self.assertEqual(line.units, 'hour')
          self.assertEqual(line.description, 'CAM coding')         # from template_name, editable
          # No Task minted on the job — deferral, not immediate atom.
          self.assertFalse(Task.objects.filter(job=self.job).exists())
          # No source row yet (crystallizes at acceptance).
          self.assertFalse(line.sources.exists())

      def test_rejects_non_draft_estimate(self):
          self.estimate.status = Estimate.STATUS_OPEN
          self.estimate.save()
          with self.assertRaises(ValidationError):
              EstimateService.add_line_item_from_service(
                  self.estimate.pk, self.service_item.pk, Decimal('1'),
              )

      def test_missing_service_item_raises_not_found(self):
          with self.assertRaises(NotFoundError):
              EstimateService.add_line_item_from_service(
                  self.estimate.pk, 999999, Decimal('1'),
              )
  ```
- [ ] **Run, expect FAIL** — `python manage.py test tests.test_deferred_service_crystallization`.
  Expected: `AttributeError: type object 'EstimateService' has no attribute
  'add_line_item_from_service'`.
- [ ] **Implement** — add to `EstimateService`, directly beneath `add_line_item_from_pli`:
  ```python
  @staticmethod
  def add_line_item_from_service(estimate_pk, service_item_pk, qty):
      """Add a deferred service line to a draft estimate.

      Mirrors add_line_item_from_pli: snapshots the priced values off the
      ServiceItem at instantiation (price/accounting_category/units/description)
      and keeps `service_item` on the line purely as the crystallization target.
      Mints NO Task — the Task is created at acceptance (on_accept)."""
      from apps.estimates.models import ServiceItem
      try:
          estimate = Estimate.objects.get(pk=estimate_pk)
      except Estimate.DoesNotExist:
          raise NotFoundError(f'Estimate {estimate_pk} not found')
      if estimate.status != Estimate.STATUS_DRAFT:
          raise ValidationError('Can only add line items to draft estimates.')
      try:
          service_item = ServiceItem.objects.get(pk=service_item_pk)
      except ServiceItem.DoesNotExist:
          raise NotFoundError(f'ServiceItem {service_item_pk} not found')
      from apps.core.services import LineItemService
      scheme = service_item.rate_scheme
      li = EstimateLineItem(
          estimate=estimate,
          service_item=service_item,
          description=service_item.template_name,
          qty=qty,
          units=scheme.unit_label or 'none',
          price=scheme.effective_rate(service_item.default_active_modifiers),
          accounting_category=service_item.effective_accounting_category,
      )
      li.full_clean()
      LineItemService.save_line_item(li)
      return li
  ```
  (Import `ServiceItem` lazily inside the method to avoid a models import cycle, matching the file's
  existing lazy-import style.)
- [ ] **Run, expect PASS** — `python manage.py test tests.test_deferred_service_crystallization`.
  Confirm `OK`.
- [ ] **Commit** — `feat(estimates): add_line_item_from_service snapshots priced values, no Task`.

---

## Task 3 — `ServiceItem.generate_task` accepts `allow_superseded_scheme`

The current `generate_task` (`apps/estimates/models.py:423`) **unconditionally** raises
`SchemeSupersededError` when `rate_scheme.replaced_by_id is not None`. Acceptance must be able to
crystallize a superseded service line without aborting, so add the bypass parameter (parity with
`TaskService.create_direct(..., allow_superseded_scheme=...)` at `apps/jobs/services.py:761`).

**Files**
- `apps/estimates/models.py` (`ServiceItem.generate_task`)
- `tests/test_deferred_service_crystallization.py`

**Interface**
```python
def generate_task(self, container, est_qty, bundle_identifier=None, product_instance=None,
                  assignee=None, sort_order=None, name=None, description=None,
                  active_modifiers=None, est_worker_time=None,
                  allow_superseded_scheme=False):
```

**TDD steps**

- [ ] **Failing test** — append:
  ```python
  from apps.core.services import SchemeSupersededError


  class GenerateTaskSupersededBypassTest(DeferredServiceBase):
      def _supersede(self):
          # Point the scheme at a replacement so replaced_by_id is set.
          new = RateScheme.objects.create(
              name='Hourly v2', algorithm=RateScheme.ENTERED_QTY,
              rate=Decimal('45'), unit_label='hour', accounting_category=self.cat,
          )
          self.scheme.replaced_by = new
          self.scheme.save()

      def test_superseded_scheme_aborts_by_default(self):
          self._supersede()
          with self.assertRaises(SchemeSupersededError):
              self.service_item.generate_task(self.job, est_qty=Decimal('1'))

      def test_allow_superseded_scheme_bypasses_and_builds_task(self):
          self._supersede()
          task = self.service_item.generate_task(
              self.job, est_qty=Decimal('1'),
              description='desc from line', allow_superseded_scheme=True,
          )
          self.assertEqual(task.name, 'CAM coding')          # from template_name
          self.assertEqual(task.description, 'desc from line')
          self.assertEqual(task.rate_scheme_id, self.scheme.pk)
  ```
  (`RateScheme.save()` runs `full_clean()`; setting only `replaced_by` is an allowed mutation — the
  `FROZEN_FIELDS` guard exempts `replaced_by`/`replaced_at`.)
- [ ] **Run, expect FAIL** — `python manage.py test tests.test_deferred_service_crystallization`.
  Expected: `test_allow_superseded_scheme_bypasses_and_builds_task` raises `SchemeSupersededError`
  (bypass not honored — `generate_task` has no such param).
- [ ] **Implement** — add the parameter and gate the raise:
  ```python
  def generate_task(self, container, est_qty, bundle_identifier=None, product_instance=None,
                    assignee=None, sort_order=None,
                    name=None, description=None,
                    active_modifiers=None, est_worker_time=None,
                    allow_superseded_scheme=False):
      ...
      if (self.rate_scheme_id and self.rate_scheme.replaced_by_id is not None
              and not allow_superseded_scheme):
          raise SchemeSupersededError(
              f'Template "{self.template_name}" references a superseded '
              f'RateScheme. Update the template before adding tasks from it.'
          )
      ...
  ```
  Update the docstring's "Optional overrides" block to mention `allow_superseded_scheme`.
- [ ] **Run, expect PASS** — confirm `OK`.
- [ ] **Regression** — `python manage.py test tests.test_estimates_services` to confirm existing
  `generate_task` callers are unaffected. Confirm `OK`.
- [ ] **Commit** — `feat(estimates): ServiceItem.generate_task gains allow_superseded_scheme bypass`.

---

## Task 4 — API action `line-items-from-service`

Add a dedicated POST action on `EstimateViewSet`, parallel to `line-items-from-atoms`. (The
`LineItemMixin.line_items` POST auto-detects `inventory_item`; the service pick needs its own explicit
route so the deferred-descriptor semantics are unambiguous.)

**Files**
- `apps/api/estimates/views.py` (`EstimateViewSet`)
- `tests/test_deferred_service_crystallization.py`

**Interface**
- `POST /api/estimates/{pk}/line-items-from-service/`
- Body: `{ "service_item": <id>, "qty": "<decimal>" }`
- 201 with the serialized line; 404 if the ServiceItem/estimate is missing; 400 on validation error
  (non-draft, etc.). Permission: `IsAuthenticated` + `CanManageJobOrPM` (falls through
  `get_permissions`' default branch — not a read/mixed action).

**TDD steps**

- [ ] **Failing test** — append an APITestCase-style test. Reuse a request factory or DRF
  `APIClient`; mirror `tests/test_estimate_wizard_api.py` for auth setup:
  ```python
  from rest_framework.test import APIClient
  from apps.core.models import User


  class LineItemsFromServiceApiTest(DeferredServiceBase):
      def setUp(self):
          super().setUp()
          self.user = User.objects.create_user(
              username='mgr', password='pw', email='mgr@x.com',
          )
          # can_manage_jobs atom so CanManageJobOrPM passes for a non-PM job.
          from django.contrib.auth.models import Permission
          perm = Permission.objects.get(codename='can_manage_jobs')
          self.user.user_permissions.add(perm)
          self.client = APIClient()
          self.client.force_authenticate(self.user)

      def test_posts_a_deferred_service_line(self):
          from apps.jobs.models import Task
          resp = self.client.post(
              f'/api/estimates/{self.estimate.pk}/line-items-from-service/',
              {'service_item': self.service_item.pk, 'qty': '3'}, format='json',
          )
          self.assertEqual(resp.status_code, 201, resp.data)
          self.assertEqual(resp.data['service_item'], self.service_item.pk)
          self.assertEqual(resp.data['description'], 'CAM coding')
          self.assertEqual(Decimal(resp.data['price']), Decimal('40.00'))
          self.assertEqual(Decimal(resp.data['qty']), Decimal('3'))
          # Still deferred: no Task minted.
          self.assertFalse(Task.objects.filter(job=self.job).exists())

      def test_missing_service_item_is_404(self):
          resp = self.client.post(
              f'/api/estimates/{self.estimate.pk}/line-items-from-service/',
              {'service_item': 999999, 'qty': '1'}, format='json',
          )
          self.assertEqual(resp.status_code, 404)
  ```
  (Confirm the `can_manage_jobs` permission codename against `apps/api/permissions.py`; if the atom is
  a boolean field rather than a Django `Permission`, set it directly on the user instead.)
- [ ] **Run, expect FAIL** — the URL 404s (action not registered) → assertion on 201/404 mismatch.
- [ ] **Implement** — add to `EstimateViewSet`, next to `line_items_from_atoms`:
  ```python
  @action(detail=True, methods=['post'], url_path='line-items-from-service')
  def line_items_from_service(self, request, pk=None):
      """Create a deferred service line (service_item descriptor + snapshot).

      Mints NO Task; the Task crystallizes at acceptance (on_accept)."""
      estimate = self.get_object()
      try:
          line_item = EstimateService.add_line_item_from_service(
              estimate.pk,
              request.data.get('service_item'),
              request.data.get('qty'),
          )
      except NotFoundError as e:
          return Response({'detail': str(e)}, status=status.HTTP_404_NOT_FOUND)
      except DjangoValidationError as e:
          msg = e.messages[0] if hasattr(e, 'messages') else str(e)
          return Response({'detail': msg}, status=status.HTTP_400_BAD_REQUEST)
      serializer = EstimateLineItemSerializer(line_item)
      return Response(serializer.data, status=status.HTTP_201_CREATED)
  ```
  (`NotFoundError` and `DjangoValidationError` are already imported in this module.)
- [ ] **Run, expect PASS** — confirm `OK`. Note: this test asserts `resp.data['service_item']` and
  `resp.data['price']`, which depends on Task 6's serializer field. Sequence Task 6 **before** running
  this test green, or split: run only the 404 assertion first, then the full body assertion after
  Task 6. Simplest: implement Task 6 immediately after this, then run both green together.
- [ ] **Commit** — `feat(api): line-items-from-service action for deferred service picks`.

---

## Task 5 — Extend `on_accept` with the `service_item → Task` branch (placed first)

**Files**
- `apps/estimates/acceptance.py` (`EstimateAcceptanceService.on_accept`)
- `tests/test_deferred_service_crystallization.py`

**Interface** — inside the per-line loop, after the `sources.exists()` and `adjustment_service_id`
skips, **before** the `inventory_item` branch:
```python
if li.service_item_id is not None:
    task = li.service_item.generate_task(
        job, est_qty=li.qty or Decimal('1'),
        description=li.description or '',
        allow_superseded_scheme=True,
    )
    EstimateLineItemSource.objects.create(
        estimate_line_item=li,
        source_type=EstimateLineItemSource.SOURCE_TASK,
        source_pk=task.pk,
    )
    tasks_created += 1
    continue
```
`Task.name` comes from `service_item.template_name` (inside `generate_task`); `Task.description` =
the line's editable description. Return dict grows a `tasks_created` count.

**Discriminator order (final):** `service_item → Task` (this), `inventory_item → Material`,
`is_material` bare → provisional Material (Plan 1), else → Fee.

**TDD steps**

- [ ] **Failing test** — append:
  ```python
  from apps.estimates.acceptance import EstimateAcceptanceService
  from apps.estimates.models import EstimateLineItemSource


  class OnAcceptCrystallizesServiceTest(DeferredServiceBase):
      def setUp(self):
          super().setUp()
          self.estimate.status = Estimate.STATUS_OPEN
          self.estimate.save()

      def test_service_line_becomes_a_task_and_source_links(self):
          from apps.jobs.models import Task, Fee
          line = EstimateService.add_line_item_from_service(
              self.estimate.pk, self.service_item.pk, Decimal('2'),
          )
          # Edit the description as a user would; it becomes the Task description.
          line.description = 'CAM coding for panel A'
          line.save()

          result = EstimateAcceptanceService.on_accept(self.estimate)

          task = Task.objects.get(job=self.job)
          self.assertEqual(task.name, 'CAM coding')                  # ServiceItem name
          self.assertEqual(task.description, 'CAM coding for panel A')  # line description
          self.assertEqual(task.rate_scheme_id, self.scheme.pk)
          self.assertEqual(task.est_qty, Decimal('2'))
          self.assertEqual(result['tasks_created'], 1)
          # It did NOT become a Fee.
          self.assertFalse(Fee.objects.filter(job=self.job).exists())
          # Source-linked to the Task.
          src = EstimateLineItemSource.objects.get(estimate_line_item=line)
          self.assertEqual(src.source_type, EstimateLineItemSource.SOURCE_TASK)
          self.assertEqual(src.source_pk, task.pk)

      def test_superseded_scheme_does_not_abort_acceptance(self):
          from apps.jobs.models import Task
          line = EstimateService.add_line_item_from_service(
              self.estimate.pk, self.service_item.pk, Decimal('1'),
          )
          new = RateScheme.objects.create(
              name='Hourly v2', algorithm=RateScheme.ENTERED_QTY,
              rate=Decimal('45'), unit_label='hour', accounting_category=self.cat,
          )
          self.scheme.replaced_by = new
          self.scheme.save()

          # Does NOT raise SchemeSupersededError.
          EstimateAcceptanceService.on_accept(self.estimate)
          self.assertTrue(Task.objects.filter(job=self.job).exists())
  ```
- [ ] **Run, expect FAIL** — `test_service_line_becomes_a_task_and_source_links` fails: the service
  line hits the Fee branch (or `KeyError: 'tasks_created'`), no Task created.
- [ ] **Implement** — in `on_accept`: initialize `tasks_created = 0` alongside the other counters,
  insert the `service_item` branch first in the loop (see Interface), and add `'tasks_created':
  tasks_created` to the returned dict. Keep `from decimal import Decimal` (already imported).
- [ ] **Run, expect PASS** — confirm `OK`.
- [ ] **Regression** — `python manage.py test tests.test_acceptance_fees` (existing crystallization
  behavior for hand/inventory/adjustment lines must stay green — the new branch is `continue`-guarded
  and only fires on `service_item_id`). Confirm `OK`. Note `test_acceptance_fees` asserts on
  `result['fees_created']`/`materials_created`; adding a `tasks_created` key does not break those.
- [ ] **Commit** — `feat(estimates): on_accept crystallizes service lines into Tasks (first branch)`.

---

## Task 6 — Serializer exposes `service_item` (+ detail) and renders `qty × price`

**Files**
- `apps/api/estimates/serializers.py` (`EstimateLineItemSerializer`)
- `tests/test_deferred_service_crystallization.py`

**Interface**
- Add `'service_item'` to `EstimateLineItemSerializer.Meta.fields`.
- Add a read-only `service_item_detail` `SerializerMethodField` (name + template_id) for display
  parity with `adjustment_service_detail`.
- **Amount projection.** A bare service line (no `sources`) has `qty` and `price`; the SPA computes
  `qty × price` from those two fields (the estimate line table already renders bare-line amount from
  `qty`/`price` — the `sources` path is only for atom-backed lines). Verify no server-side `amount`
  field is required; the existing fields suffice.

**TDD steps**

- [ ] **Failing test** — append (a serializer-level unit test, no HTTP):
  ```python
  from apps.api.estimates.serializers import EstimateLineItemSerializer


  class ServiceLineSerializerTest(DeferredServiceBase):
      def test_exposes_service_item_and_detail_and_price(self):
          line = EstimateService.add_line_item_from_service(
              self.estimate.pk, self.service_item.pk, Decimal('2'),
          )
          data = EstimateLineItemSerializer(line).data
          self.assertEqual(data['service_item'], self.service_item.pk)
          self.assertEqual(data['service_item_detail']['name'], 'CAM coding')
          self.assertEqual(Decimal(data['price']), Decimal('40.00'))
          self.assertEqual(Decimal(data['qty']), Decimal('2'))
          # Amount is qty x price (self-contained snapshot): 2 x 40 = 80.
          self.assertEqual(
              Decimal(data['qty']) * Decimal(data['price']), Decimal('80.00'),
          )
  ```
- [ ] **Run, expect FAIL** — `KeyError: 'service_item'` (field not in `Meta.fields`) or
  `service_item_detail`.
- [ ] **Implement** —
  ```python
  class EstimateLineItemSerializer(serializers.ModelSerializer):
      units = UnitsField()
      sources = EstimateLineItemSourceSerializer(many=True, read_only=True)
      adjustment_service_detail = serializers.SerializerMethodField()
      service_item_detail = serializers.SerializerMethodField()

      class Meta:
          model = EstimateLineItem
          fields = [
              'line_item_id', 'line_number', 'inventory_item', 'service_item',
              'qty', 'units', 'description', 'price',
              'accounting_category', 'taxable_override', 'tax_rate_override',
              'adjustment_service', 'adjustment_target_categories',
              'adjustment_service_detail', 'service_item_detail',
              'sources',
          ]
          read_only_fields = ['line_item_id']

      def get_service_item_detail(self, obj):
          if obj.service_item_id is None:
              return None
          si = obj.service_item
          return {'template_id': si.template_id, 'name': si.template_name}
  ```
- [ ] **Run, expect PASS** — confirm `OK`. Now re-run Task 4's API test
  (`LineItemsFromServiceApiTest`) — `resp.data['service_item']` resolves; confirm `OK`.
- [ ] **Commit** — `feat(api): serialize service_item + service_item_detail on estimate lines`.

---

## Task 7 — Send-gate confirmation: service lines pass `mark_open`

Per Part 1, the send gate requires a **sell price** on material/service lines and keeps the AC rule.
Service lines always snapshot both `price` and `accounting_category`, so **no new gate code is needed**
for them — this task is a regression test proving a draft estimate carrying only a service line sends
cleanly (passes `assert_all_hand_lines_have_ac` and has a price). (A general "sell price required"
gate, if introduced at all, belongs to the freeform-material procurement plan, not here — service
lines already satisfy it.)

**Files**
- `tests/test_deferred_service_crystallization.py`

**TDD steps**

- [ ] **Test (documents behavior; passes once Tasks 1–2 land)** — a service line has an AC from the
  snapshot, so `assert_all_hand_lines_have_ac` does not flag it. `mark_open` also requires a
  Deliverable, so seed one:
  ```python
  from apps.deliverables.models import Deliverable


  class ServiceLineSendGateTest(DeferredServiceBase):
      def test_draft_with_only_a_service_line_can_be_marked_open(self):
          EstimateService.add_line_item_from_service(
              self.estimate.pk, self.service_item.pk, Decimal('1'),
          )
          Deliverable.objects.create(job=self.job, description='widget')

          estimate = EstimateService.mark_open(self.estimate.pk)
          self.assertEqual(estimate.status, Estimate.STATUS_OPEN)

      def test_assert_all_hand_lines_have_ac_passes_for_service_line(self):
          EstimateService.add_line_item_from_service(
              self.estimate.pk, self.service_item.pk, Decimal('1'),
          )
          # Snapshot populated the AC → no ValidationError raised.
          EstimateService.assert_all_hand_lines_have_ac(self.estimate)
  ```
  (Confirm `Deliverable`'s required fields against `apps/deliverables/models.py` before relying on the
  `description`-only create; adjust the create kwargs if more are required.)
- [ ] **Run, expect PASS** — `python manage.py test tests.test_deferred_service_crystallization`.
  This confirms no code change is needed. If `mark_open` unexpectedly raises, the service line lacks an
  AC or price — trace back to Task 2's snapshot.
- [ ] **Commit** — `test(estimates): service lines pass the estimate send-gate`.

---

## Task 8 — Repoint `AddServiceItemModal.svelte` to the deferred endpoint

Replace the two-call `add-from-template` → `line-items-from-atoms` chain with a single call to
`line-items-from-service`. Interim only — Plan 3's unified picker later replaces this modal. The job
task-list surface's `add-from-template` is untouched.

**Files**
- `frontend/src/components/estimates/AddServiceItemModal.svelte`
- `frontend/tests/components/estimates/AddServiceItemModal.test.js`

**Interface** — on save: `POST /api/estimates/{estimateId}/line-items-from-service/` with body
`{ service_item: Number(selectedId), qty: estQty || '1' }`. `jobId` is no longer needed for the call
(keep the prop for now to avoid churn in `EstimateDetailPage`, or drop it and its usage — see step).

**TDD steps**

- [ ] **Failing test** — rewrite `AddServiceItemModal.test.js` to assert the single deferred call:
  ```javascript
  import { describe, it, expect, vi, beforeEach } from 'vitest';
  import { render, fireEvent } from '@testing-library/svelte';

  vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

  import { api } from '@/lib/api.js';
  import AddServiceItemModal from '@/components/estimates/AddServiceItemModal.svelte';

  const SERVICE_ITEMS = [
    { template_id: 7, template_name: 'CAM coding' },
    { template_id: 8, template_name: 'V-Carve' },
  ];

  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.get.mockResolvedValue({ results: SERVICE_ITEMS });
  });

  describe('AddServiceItemModal', () => {
    it('creates a deferred service line (no Task), one API call', async () => {
      api.post.mockResolvedValueOnce({ line_item_id: 1, service_item: 7 });
      const onSaved = vi.fn();
      const { getByRole, findByText } = render(AddServiceItemModal, {
        props: { open: true, jobId: 9, estimateId: 3, onSaved },
      });

      await findByText('CAM coding');
      await fireEvent.change(getByRole('combobox'), { target: { value: '7' } });
      await fireEvent.input(getByRole('spinbutton'), { target: { value: '2' } });
      await fireEvent.click(getByRole('button', { name: 'Add' }));

      await vi.waitFor(() => expect(onSaved).toHaveBeenCalled());
      expect(api.post).toHaveBeenCalledTimes(1);
      expect(api.post).toHaveBeenCalledWith(
        '/api/estimates/3/line-items-from-service/',
        { service_item: 7, qty: '2' },
      );
    });

    it('does not call the API when no service item is selected', async () => {
      const { getByRole, findByText } = render(AddServiceItemModal, {
        props: { open: true, jobId: 9, estimateId: 3 },
      });
      await findByText('CAM coding');
      await fireEvent.click(getByRole('button', { name: 'Add' }));
      expect(api.post).not.toHaveBeenCalled();
    });
  });
  ```
- [ ] **Run, expect FAIL** — from `frontend/`: `npm run test:run --
  tests/components/estimates/AddServiceItemModal.test.js`. Expected: still calls
  `add-from-template` (two `post` calls), assertion on `toHaveBeenCalledTimes(1)` fails.
- [ ] **Implement** — replace the `save()` body and update the header comment:
  ```javascript
  async function save() {
    if (!selectedId) {
      error = 'Select a service.';
      return;
    }
    busy = true;
    error = '';
    try {
      await api.post(`/api/estimates/${estimateId}/line-items-from-service/`, {
        service_item: Number(selectedId),
        qty: estQty || '1',
      });
      onSaved();
    } catch (e) {
      error = e.message || 'Could not add the service.';
    } finally {
      busy = false;
    }
  }
  ```
  Update the top-of-file comment to describe the deferred descriptor (no immediate Task). `jobId` is
  now unused in the call; leave the prop declared (still passed by `EstimateDetailPage`) or remove it
  along with its `jobId={estimate.job}` binding — either is fine, keep the diff minimal.
- [ ] **Run, expect PASS** — `npm run test:run -- tests/components/estimates/AddServiceItemModal.test.js`.
  Confirm the file's tests pass. (Do NOT use watch mode.)
- [ ] **Commit** — `feat(estimates/ui): AddServiceItemModal posts deferred service line`.

---

## Wrap-up (not a commit step — human reviews)

- [ ] Full backend module green: `python manage.py test tests.test_deferred_service_crystallization`
  (no pipe, no `--keepdb`) — read the `OK` / `Ran N tests` line.
- [ ] Broader regression: `python manage.py test tests.test_acceptance_fees tests.test_estimates_services`.
- [ ] Frontend: `npm run test:run` from `frontend/` (whole suite) — confirm no collateral breakage.
- [ ] Update `docs/designs/estimates-and-prices.md`: document the deferred service pick
  (`service_item` descriptor + snapshot), the three-/four-way `on_accept` discriminator order, and the
  `line-items-from-service` endpoint; note the no-price-guard decision.
- [ ] Leave the branch as-is for human review. **Do NOT** merge/push/PR.
