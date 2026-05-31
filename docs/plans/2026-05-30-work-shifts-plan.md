# Work Shifts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add worker attendance tracking (clock in / clock out) to Minibini, with a shift↔blep enclosure invariant, worker self-edit + manager-approved change requests for both shifts and bleps, and a payroll shift-time report.

**Architecture:** A model-light addition centered on a new `Shift` model in `apps.core`. Two change-request models (`ShiftChangeRequest` in core, `BlepChangeRequest` in jobs) share an abstract `TimeChangeRequest` base. All mutation logic lives in services (`ShiftService`, `TimeChangeRequestService`) that enforce the enclosure invariant via shared helpers in `apps/core/time_integrity.py`. The frontend generalizes the existing `BlepEditModal` into a `TimeEditModal` and reuses the `BlepLogTable` / reimbursement-approval / sticky-band patterns.

**Tech Stack:** Django 5.2 + DRF (MySQL), Svelte 5 SPA (Vite, svelte-spa-router). Session auth. `@history` audit decorator. TDD with Django `TestCase` + `APIClient`.

---

## ⚠️ Ground rules for the executor

- **NEVER write to the dev DB.** Do **not** run `python manage.py migrate`, `shell`, `loaddata`, or any ORM write. `makemigrations` is allowed. Tests build their own DB and tear it down — run `python manage.py test` freely (but **never run tests from parallel agents** — one at a time, shared MySQL).
- After `makemigrations`, **the human runs `migrate`** in dev. Note in your hand-off when a migration needs applying.
- The **backfill script (Task 19) is run by the human, not the agent.**
- Source design spec: `docs/plans/2026-05-30-work-shifts-design.md`. Read it if a decision is unclear.
- Follow `CLAUDE.md` conventions: explicit `*_id` PKs, status constants, `transaction.atomic()` for multi-model writes, services hold all business logic, DELETE returns 200 + JSON.

---

## File Structure

**Backend — create:**
- `apps/core/time_integrity.py` — pure enclosure-invariant helpers (no DB writes).
- `apps/api/shifts/__init__.py`, `apps/api/shifts/views.py`, `apps/api/shifts/serializers.py`, `apps/api/shifts/urls.py` — Shift + change-request + report API.
- `apps/core/management/commands/backfill_shifts.py` — one-time enclosing-shift backfill (human-run).
- Test modules under `tests/` (one per task group).

**Backend — modify:**
- `apps/core/models.py` — add `Shift`, abstract `TimeChangeRequest`, `ShiftChangeRequest`.
- `apps/jobs/models.py` — add `BlepChangeRequest`.
- `apps/core/services.py` — add `ShiftService`, `TimeChangeRequestService`, `SELF_EDIT_WINDOW_HOURS`.
- `apps/jobs/services.py` — auto-clock-in hook in blep start/create; enclosure check in `BlepService.update`/`create_historical`.
- `apps/api/permissions.py` — add `CanManageTimeOrFinancials`.
- `apps/api/time_tracking/urls.py` — replace stubs with real clock-in/clock-out.
- `apps/api/urls.py` — register shift + change-request routers and include shift urls.

**Frontend — create:**
- `frontend/src/stores/shift.js` — current-shift state + change notifier.
- `frontend/src/components/time/TimeEditModal.svelte` — generalized from `BlepEditModal`.
- `frontend/src/components/time/ShiftLogTable.svelte` — mirrors `BlepLogTable`.
- `frontend/src/components/home/ClockBand.svelte` — clock in/out buttons + state.
- `frontend/src/components/home/MyShiftsList.svelte`, `frontend/src/components/home/MyChangeRequestsList.svelte`.
- `frontend/src/components/users/ShiftRequestQueue.svelte`, `frontend/src/components/users/PayrollReport.svelte`.

**Frontend — modify:**
- `frontend/src/stores/auth.js` (or `LoginPage.svelte`) — push to Home after login.
- `frontend/src/routes/Home.svelte` — mount `ClockBand`; add shift list + requests to Time tab.
- `frontend/src/components/home/RecentTimeList.svelte` — implement `requestEdit()`; `within24h`→`within30h`; use `TimeEditModal`.
- `frontend/src/components/tasks/BlepEditModal.svelte` — re-export or replace with `TimeEditModal` usage (keep the task-detail call site working).
- `frontend/src/routes/users/UserListPage.svelte` — add tabs (Users / Shifts) hosting the queue + report.

**Docs — modify (final task):** `data-constraints.md`, `users-and-permissions.md`, `architecture-and-conventions.md`, `jobs-tasks-and-worksheets.md`.

---

# Phase 1 — Backend data model & invariant

### Task 1: `Shift` model

**Files:**
- Modify: `apps/core/models.py`
- Test: `tests/test_shift_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shift_model.py
from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift


class ShiftModelTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='shift_model_u', password='x')

    def test_open_shift_has_null_end(self):
        s = Shift.objects.create(user=self.user, start_time=timezone.now())
        self.assertIsNone(s.end_time)
        self.assertTrue(Shift.objects.filter(user=self.user, end_time__isnull=True).exists())

    def test_str_and_table(self):
        s = Shift.objects.create(user=self.user, start_time=timezone.now())
        self.assertIn(self.user.username, str(s))
        self.assertEqual(Shift._meta.db_table, 'shifts')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_shift_model -v 2`
Expected: FAIL — `ImportError: cannot import name 'Shift'`.

- [ ] **Step 3: Add the model**

In `apps/core/models.py`, near the `User` class (ensure `from apps.core.history import history` is imported — add it if missing):

```python
@history(exclude=['shift_id'])
class Shift(models.Model):
    shift_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('core.User', on_delete=models.PROTECT, related_name='shifts')
    start_time = models.DateTimeField()                       # clock-in
    end_time = models.DateTimeField(null=True, blank=True)    # null = on the clock

    class Meta:
        db_table = 'shifts'
        ordering = ['-start_time']

    @property
    def is_open(self):
        return self.end_time is None

    def __str__(self):
        return f"Shift {self.pk} for {self.user.username}"
```

- [ ] **Step 4: Make the migration**

Run: `python manage.py makemigrations core`
Expected: a new migration adding `Shift`. (Do NOT run `migrate`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_shift_model -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/core/models.py apps/core/migrations/ tests/test_shift_model.py
git commit -m "feat(shifts): add Shift model with history tracking"
```

---

### Task 2: Enclosure-invariant helpers

Pure functions, no writes. The two directions of the invariant:
- Given a proposed **shift** span, find that user's bleps that should be enclosed but aren't.
- Given a proposed **blep** span, find an enclosing shift (or None).

**Files:**
- Create: `apps/core/time_integrity.py`
- Test: `tests/test_time_integrity.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_time_integrity.py
from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.jobs.models import Job, Task, Blep
from apps.core.time_integrity import unenclosed_bleps_for_shift, enclosing_shift_for_blep


class TimeIntegrityTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='integ_u', password='x')
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)
        self.t0 = timezone.now().replace(microsecond=0) - timedelta(hours=10)

    def _blep(self, start_h, end_h):
        return Blep.objects.create(
            task=self.task, user=self.user,
            start_time=self.t0 + timedelta(hours=start_h),
            end_time=self.t0 + timedelta(hours=end_h),
        )

    def test_shift_fully_encloses_blep_no_conflict(self):
        self._blep(1, 2)
        bad = unenclosed_bleps_for_shift(self.user, self.t0, self.t0 + timedelta(hours=8))
        self.assertEqual(list(bad), [])

    def test_blep_spilling_past_shift_end_is_conflict(self):
        b = self._blep(1, 5)
        bad = unenclosed_bleps_for_shift(self.user, self.t0, self.t0 + timedelta(hours=4))
        self.assertIn(b, list(bad))

    def test_blep_orphaned_by_shrunk_shift_is_conflict(self):
        # blep at 1–2h; shift shrunk to 6–8h leaves it un-enclosed (also_span = old span)
        b = self._blep(1, 2)
        bad = unenclosed_bleps_for_shift(
            self.user, self.t0 + timedelta(hours=6), self.t0 + timedelta(hours=8),
            also_span=(self.t0, self.t0 + timedelta(hours=8)),
        )
        self.assertIn(b, list(bad))

    def test_enclosing_shift_found(self):
        Shift.objects.create(user=self.user, start_time=self.t0,
                             end_time=self.t0 + timedelta(hours=8))
        s = enclosing_shift_for_blep(self.user, self.t0 + timedelta(hours=1),
                                     self.t0 + timedelta(hours=2))
        self.assertIsNotNone(s)

    def test_no_enclosing_shift_returns_none(self):
        s = enclosing_shift_for_blep(self.user, self.t0 + timedelta(hours=1),
                                     self.t0 + timedelta(hours=2))
        self.assertIsNone(s)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_time_integrity -v 2`
Expected: FAIL — module/functions not defined.

- [ ] **Step 3: Implement the helpers**

```python
# apps/core/time_integrity.py
"""Pure helpers enforcing the shift↔blep enclosure invariant.

Invariant: every Blep must be fully enclosed by a Shift of the same user
(shift.start <= blep.start and blep.end <= shift.end). Bleps and shifts are
related by time overlap, not an FK. No function here writes to the DB.
"""
from apps.jobs.models import Blep


def _candidate_bleps(user, span_start, span_end):
    """Closed bleps of `user` that overlap [span_start, span_end]."""
    return Blep.objects.filter(
        user=user,
        end_time__isnull=False,
        start_time__lt=span_end,
        end_time__gt=span_start,
    )


def unenclosed_bleps_for_shift(user, shift_start, shift_end, exclude_shift=None,
                               also_span=None):
    """Return this user's bleps that a shift spanning [shift_start, shift_end]
    would fail to enclose.

    Candidates are bleps overlapping the proposed span — plus, when editing an
    existing shift, the original span (`also_span`) so a blep shrunk *out* of the
    shift is still caught. A candidate conflicts unless fully inside the new span.
    """
    span_start, span_end = shift_start, shift_end
    if also_span:
        span_start = min(span_start, also_span[0])
        span_end = max(span_end, also_span[1])
    qs = _candidate_bleps(user, span_start, span_end)
    if exclude_shift is not None:
        pass  # shifts carry no blep FK; nothing to exclude
    return [b for b in qs if not (shift_start <= b.start_time and b.end_time <= shift_end)]


def enclosing_shift_for_blep(user, blep_start, blep_end, exclude_blep=None):
    """Return a Shift of `user` that fully encloses [blep_start, blep_end], or None.
    Only closed shifts can enclose (an open shift has no end yet)."""
    return (
        user.shifts.filter(
            end_time__isnull=False,
            start_time__lte=blep_start,
            end_time__gte=blep_end,
        )
        .order_by('start_time')
        .first()
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_time_integrity -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/core/time_integrity.py tests/test_time_integrity.py
git commit -m "feat(shifts): enclosure-invariant helpers"
```

---

### Task 3: `ShiftService.clock_in` / `clock_out` (+ closes open bleps)

**Files:**
- Modify: `apps/core/services.py`
- Test: `tests/test_shift_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shift_service.py
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.core.services import ShiftService
from apps.jobs.models import Job, Task, Blep


class ShiftClockTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='clock_u', password='x')
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)

    def test_clock_in_opens_shift(self):
        s = ShiftService.clock_in(self.user)
        self.assertTrue(s.is_open)

    def test_clock_in_twice_blocked(self):
        ShiftService.clock_in(self.user)
        with self.assertRaises(ValidationError):
            ShiftService.clock_in(self.user)

    def test_clock_out_closes_shift_and_open_bleps(self):
        s = ShiftService.clock_in(self.user)
        blep = Blep.objects.create(task=self.task, user=self.user,
                                   start_time=timezone.now())
        ShiftService.clock_out(self.user)
        s.refresh_from_db(); blep.refresh_from_db()
        self.assertIsNotNone(s.end_time)
        self.assertIsNotNone(blep.end_time)

    def test_clock_out_without_open_shift_blocked(self):
        with self.assertRaises(ValidationError):
            ShiftService.clock_out(self.user)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_shift_service -v 2`
Expected: FAIL — `ShiftService` undefined.

- [ ] **Step 3: Implement clock_in / clock_out / helpers**

Add to `apps/core/services.py` (imports at top: `from django.core.exceptions import ValidationError`, `from django.db import transaction`, `from django.utils import timezone`):

```python
SELF_EDIT_WINDOW_HOURS = 30


class ShiftService:
    @staticmethod
    def open_shift_for(user):
        return user.shifts.filter(end_time__isnull=True).first()

    @staticmethod
    def clock_in(user, start_time=None):
        if ShiftService.open_shift_for(user):
            raise ValidationError("You are already clocked in.")
        from apps.core.models import Shift
        return Shift.objects.create(user=user, start_time=start_time or timezone.now())

    @staticmethod
    def ensure_open_shift(user, start_time=None):
        """Open a shift if the user has none open (auto-clock-in on blep start)."""
        existing = ShiftService.open_shift_for(user)
        if existing:
            return existing
        return ShiftService.clock_in(user, start_time=start_time)

    @staticmethod
    def clock_out(user, end_time=None):
        shift = ShiftService.open_shift_for(user)
        if not shift:
            raise ValidationError("You are not clocked in.")
        now = end_time or timezone.now()
        with transaction.atomic():
            from apps.jobs.services import BlepService
            BlepService.close_user_open_bleps(user, now=now)
            shift.end_time = now
            shift.save()
        return shift
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_shift_service -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/core/services.py tests/test_shift_service.py
git commit -m "feat(shifts): ShiftService clock-in/clock-out closes open bleps"
```

---

### Task 4: `ShiftService.update` / `create` with window + invariant

**Files:**
- Modify: `apps/core/services.py`
- Test: `tests/test_shift_service_edit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shift_service_edit.py
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.core.services import ShiftService
from apps.jobs.models import Job, Task, Blep


class ShiftEditTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='edit_u', password='x')
        self.mgr = User.objects.create_user(username='edit_mgr', password='x', is_superuser=True)
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)
        self.now = timezone.now().replace(microsecond=0)

    def _recent_shift(self):
        return Shift.objects.create(user=self.user, start_time=self.now - timedelta(hours=3),
                                    end_time=self.now - timedelta(hours=1))

    def test_owner_edits_recent_shift(self):
        s = self._recent_shift()
        ShiftService.update(s, actor=self.user,
                            start_time=self.now - timedelta(hours=4),
                            end_time=self.now - timedelta(hours=1))
        s.refresh_from_db()
        self.assertEqual(s.start_time, self.now - timedelta(hours=4))

    def test_owner_cannot_edit_old_shift(self):
        old = Shift.objects.create(user=self.user, start_time=self.now - timedelta(hours=40),
                                   end_time=self.now - timedelta(hours=38))
        with self.assertRaises(ValidationError):
            ShiftService.update(old, actor=self.user,
                                start_time=self.now - timedelta(hours=41),
                                end_time=self.now - timedelta(hours=38))

    def test_manager_edits_old_shift(self):
        old = Shift.objects.create(user=self.user, start_time=self.now - timedelta(hours=40),
                                   end_time=self.now - timedelta(hours=38))
        ShiftService.update(old, actor=self.mgr,
                            start_time=self.now - timedelta(hours=41),
                            end_time=self.now - timedelta(hours=38))
        old.refresh_from_db()
        self.assertEqual(old.start_time, self.now - timedelta(hours=41))

    def test_edit_that_orphans_blep_blocked(self):
        s = self._recent_shift()
        Blep.objects.create(task=self.task, user=self.user,
                            start_time=self.now - timedelta(hours=2, minutes=30),
                            end_time=self.now - timedelta(hours=2))
        with self.assertRaises(ValidationError):
            ShiftService.update(s, actor=self.user,
                                start_time=self.now - timedelta(minutes=90),
                                end_time=self.now - timedelta(hours=1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_shift_service_edit -v 2`
Expected: FAIL — `ShiftService.update` undefined.

- [ ] **Step 3: Implement update / create / window check**

Add to `ShiftService` in `apps/core/services.py`:

```python
    @staticmethod
    def _has_manage_time(user):
        return user.is_superuser or user.has_perm('core.can_manage_time')

    @staticmethod
    def _within_window(start_time):
        return (timezone.now() - start_time) <= timedelta(hours=SELF_EDIT_WINDOW_HOURS)

    @staticmethod
    def _assert_can_edit(shift, actor):
        if ShiftService._has_manage_time(actor):
            return
        if shift.user_id != actor.id:
            raise ValidationError("You can only edit your own shifts.")
        if not ShiftService._within_window(shift.start_time):
            raise ValidationError(
                "This shift is older than the edit window — request a change instead."
            )

    @staticmethod
    def _assert_encloses(user, start_time, end_time, also_span=None):
        from apps.core.time_integrity import unenclosed_bleps_for_shift
        bad = unenclosed_bleps_for_shift(user, start_time, end_time, also_span=also_span)
        if bad:
            ids = ", ".join(str(b.pk) for b in bad)
            raise ValidationError(
                f"This shift would not enclose blep(s) {ids}; adjust the blep(s) first."
            )

    @staticmethod
    def update(shift, actor, start_time, end_time):
        ShiftService._assert_can_edit(shift, actor)
        if end_time is not None and start_time is not None and end_time < start_time:
            raise ValidationError("End must be after start.")
        old_span = (shift.start_time, shift.end_time or timezone.now())
        ShiftService._assert_encloses(shift.user, start_time, end_time, also_span=old_span)
        shift.start_time = start_time
        shift.end_time = end_time
        shift.save()
        return shift

    @staticmethod
    def create(user, actor, start_time, end_time):
        """Create a (usually historical) closed shift — used by manager edit and
        by approving a create-type change request."""
        if not (ShiftService._has_manage_time(actor) or actor.id == user.id):
            raise ValidationError("Not permitted.")
        if end_time is not None and start_time is not None and end_time < start_time:
            raise ValidationError("End must be after start.")
        ShiftService._assert_encloses(user, start_time, end_time)
        from apps.core.models import Shift
        return Shift.objects.create(user=user, start_time=start_time, end_time=end_time)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_shift_service_edit -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/core/services.py tests/test_shift_service_edit.py
git commit -m "feat(shifts): shift edit with window + enclosure invariant"
```

---

### Task 5: Auto-clock-in on blep start + enclosure check on blep edits

Hook the existing `BlepService` so starting/creating a blep ensures an open shift, and editing/creating a blep is blocked when no shift encloses it.

**Files:**
- Modify: `apps/jobs/services.py` (`BlepService.create_historical`, `BlepService.update`, and the live-start path — find `TaskLifecycleService.start_work`)
- Test: `tests/test_blep_shift_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_blep_shift_integration.py
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.core.services import ShiftService
from apps.jobs.models import Job, Task, Blep
from apps.jobs.services import BlepService, TaskLifecycleService


class BlepShiftIntegrationTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='bsi_u', password='x')
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1,
                                        assignee=self.user, est_worker_time=60)

    def test_live_start_auto_clocks_in(self):
        self.assertIsNone(ShiftService.open_shift_for(self.user))
        TaskLifecycleService.start_work(self.task, self.user)
        self.assertIsNotNone(ShiftService.open_shift_for(self.user))

    def test_create_historical_blep_requires_enclosing_shift(self):
        now = timezone.now().replace(microsecond=0)
        with self.assertRaises(ValidationError):
            BlepService.create_historical(
                actor=self.user, task=self.task,
                start_time=now - timedelta(hours=2),
                end_time=now - timedelta(hours=1),
                target_user=self.user,
            )

    def test_create_historical_blep_inside_shift_ok(self):
        now = timezone.now().replace(microsecond=0)
        Shift.objects.create(user=self.user, start_time=now - timedelta(hours=3),
                             end_time=now - timedelta(minutes=30))
        blep = BlepService.create_historical(
            actor=self.user, task=self.task,
            start_time=now - timedelta(hours=2),
            end_time=now - timedelta(hours=1),
            target_user=self.user,
        )
        self.assertIsNotNone(blep.pk)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_blep_shift_integration -v 2`
Expected: FAIL — no auto-clock-in / no enclosure check yet.

- [ ] **Step 3: Wire the hooks**

In `apps/jobs/services.py`:

(a) In the **live start path** (`TaskLifecycleService.start_work`, the method that opens a blep when a worker clicks Start), add at the top of the body, before creating the blep:

```python
        from apps.core.services import ShiftService
        ShiftService.ensure_open_shift(user, start_time=timezone.now())
```

(b) In `BlepService.create_historical`, after existing validation and before `BlepService._create(...)`, add the enclosure guard (skip when the target user is None — orphan/legacy):

```python
        if target_user is not None:
            from apps.core.time_integrity import enclosing_shift_for_blep
            if enclosing_shift_for_blep(target_user, start_time, end_time) is None:
                raise ValidationError(
                    "No shift encloses this time — clock in / add a shift covering it first."
                )
```

(c) In `BlepService.update`, after the editable fields are resolved into `start`/`end` (compute the post-edit start/end), add before `blep.save()`:

```python
        new_start = fields.get('start_time', blep.start_time)
        new_end = fields.get('end_time', blep.end_time)
        if blep.user_id is not None and new_end is not None:
            from apps.core.time_integrity import enclosing_shift_for_blep
            if enclosing_shift_for_blep(blep.user, new_start, new_end) is None:
                raise ValidationError(
                    "No shift encloses the edited time — widen the enclosing shift first."
                )
```

> If `start_work` has a different name/shape, search `apps/jobs/services.py` for where a live blep is created (`Blep.objects.create(... end_time=None ...)` or `BlepService._create(... )` with no end) and place the `ensure_open_shift` call there.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_blep_shift_integration -v 2`
Expected: PASS.

- [ ] **Step 5: Run the broader jobs/bleps suite for regressions**

Run: `python manage.py test tests.test_api_bleps -v 2`
Expected: PASS (existing blep tests still green; if a fixture-based blep now lacks an enclosing shift, that's expected behavior — adjust only test setup, not production logic).

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/services.py tests/test_blep_shift_integration.py
git commit -m "feat(shifts): auto-clock-in on blep start; enclosure guard on blep create/edit"
```

---

### Task 6: Change-request models (abstract base + two subclasses)

**Files:**
- Modify: `apps/core/models.py` (abstract `TimeChangeRequest`, `ShiftChangeRequest`)
- Modify: `apps/jobs/models.py` (`BlepChangeRequest`)
- Test: `tests/test_change_request_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_change_request_models.py
from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift, ShiftChangeRequest
from apps.jobs.models import Job, Task, Blep, BlepChangeRequest


class ChangeRequestModelTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='cr_u', password='x')
        self.now = timezone.now().replace(microsecond=0)

    def test_shift_change_request_defaults_pending(self):
        r = ShiftChangeRequest.objects.create(
            requester=self.user, requested_start=self.now, requested_end=self.now,
            reason='forgot to clock out',
        )
        self.assertEqual(r.status, ShiftChangeRequest.STATUS_PENDING)
        self.assertIsNone(r.shift)  # create-type
        self.assertEqual(ShiftChangeRequest._meta.db_table, 'shift_change_requests')

    def test_blep_change_request_carries_task(self):
        job = Job.objects.first()
        task = Task.objects.create(name='T', job=job, rate_scheme_id=1)
        r = BlepChangeRequest.objects.create(
            requester=self.user, requested_start=self.now, requested_end=self.now,
            reason='wrong end time', task=task,
        )
        self.assertEqual(r.task, task)
        self.assertEqual(BlepChangeRequest._meta.db_table, 'blep_change_requests')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_change_request_models -v 2`
Expected: FAIL — models undefined.

- [ ] **Step 3: Add the abstract base + ShiftChangeRequest (core)**

In `apps/core/models.py`:

```python
class TimeChangeRequest(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_DENIED = 'denied'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_DENIED, 'Denied'),
    ]

    requester = models.ForeignKey('core.User', on_delete=models.PROTECT, related_name='+')
    requested_start = models.DateTimeField()
    requested_end = models.DateTimeField(null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    has_known_conflict = models.BooleanField(default=False)
    reviewer = models.ForeignKey('core.User', on_delete=models.PROTECT,
                                 null=True, blank=True, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']


@history(exclude=['request_id'])
class ShiftChangeRequest(TimeChangeRequest):
    request_id = models.AutoField(primary_key=True)
    shift = models.ForeignKey('core.Shift', on_delete=models.PROTECT,
                              null=True, blank=True, related_name='change_requests')

    class Meta(TimeChangeRequest.Meta):
        abstract = False
        db_table = 'shift_change_requests'

    @property
    def target_user(self):
        return self.shift.user if self.shift_id else self.requester
```

- [ ] **Step 4: Add BlepChangeRequest (jobs)**

In `apps/jobs/models.py` (`from apps.core.models import TimeChangeRequest` near the other core imports):

```python
@history(exclude=['request_id'])
class BlepChangeRequest(TimeChangeRequest):
    request_id = models.AutoField(primary_key=True)
    blep = models.ForeignKey('jobs.Blep', on_delete=models.PROTECT,
                             null=True, blank=True, related_name='change_requests')
    task = models.ForeignKey('jobs.Task', on_delete=models.PROTECT,
                             null=True, blank=True, related_name='+')

    class Meta(TimeChangeRequest.Meta):
        abstract = False
        db_table = 'blep_change_requests'

    @property
    def target_user(self):
        return self.blep.user if self.blep_id else self.requester
```

- [ ] **Step 5: Make migrations**

Run: `python manage.py makemigrations core jobs`
Expected: migrations adding `ShiftChangeRequest` (core) and `BlepChangeRequest` (jobs). (Do NOT `migrate`.)

- [ ] **Step 6: Run test to verify it passes**

Run: `python manage.py test tests.test_change_request_models -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/core/models.py apps/jobs/models.py apps/core/migrations/ apps/jobs/migrations/ tests/test_change_request_models.py
git commit -m "feat(shifts): TimeChangeRequest base + Shift/Blep change-request models"
```

---

### Task 7: `TimeChangeRequestService` — submit / approve / deny

Generic service over any `TimeChangeRequest`. Each concrete model supplies `target_user` (Task 6) and an `apply_requested(reviewer)` method (added here) that creates/updates the real record through the right service. The generic service handles submit-conflict-flagging, approve (calls `apply_requested`, which enforces the invariant), and deny.

**Files:**
- Modify: `apps/core/services.py` (`TimeChangeRequestService`)
- Modify: `apps/core/models.py` (`ShiftChangeRequest.apply_requested`)
- Modify: `apps/jobs/models.py` (`BlepChangeRequest.apply_requested`)
- Test: `tests/test_change_request_service.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_change_request_service.py
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift, ShiftChangeRequest
from apps.core.services import TimeChangeRequestService
from apps.jobs.models import Job, Task, Blep


class ChangeRequestServiceTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='crs_u', password='x')
        self.mgr = User.objects.create_user(username='crs_mgr', password='x', is_superuser=True)
        self.now = timezone.now().replace(microsecond=0)
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)

    def test_approve_create_request_makes_shift(self):
        r = ShiftChangeRequest.objects.create(
            requester=self.user,
            requested_start=self.now - timedelta(hours=40),
            requested_end=self.now - timedelta(hours=32),
            reason='worked, forgot to clock in',
        )
        TimeChangeRequestService.approve(r, reviewer=self.mgr)
        r.refresh_from_db()
        self.assertEqual(r.status, ShiftChangeRequest.STATUS_APPROVED)
        self.assertTrue(Shift.objects.filter(user=self.user,
                        start_time=self.now - timedelta(hours=40)).exists())

    def test_approve_blocked_when_it_orphans_blep(self):
        shift = Shift.objects.create(user=self.user,
                                     start_time=self.now - timedelta(hours=5),
                                     end_time=self.now - timedelta(hours=1))
        Blep.objects.create(task=self.task, user=self.user,
                            start_time=self.now - timedelta(hours=4),
                            end_time=self.now - timedelta(hours=3))
        r = ShiftChangeRequest.objects.create(
            requester=self.user, shift=shift,
            requested_start=self.now - timedelta(hours=5),
            requested_end=self.now - timedelta(hours=3, minutes=30),  # cuts off the blep
            reason='left early',
        )
        with self.assertRaises(ValidationError):
            TimeChangeRequestService.approve(r, reviewer=self.mgr)
        r.refresh_from_db()
        self.assertEqual(r.status, ShiftChangeRequest.STATUS_PENDING)  # not consumed

    def test_deny_records_reviewer_and_note(self):
        r = ShiftChangeRequest.objects.create(
            requester=self.user, requested_start=self.now, requested_end=self.now,
            reason='x')
        TimeChangeRequestService.deny(r, reviewer=self.mgr, note='insufficient detail')
        r.refresh_from_db()
        self.assertEqual(r.status, ShiftChangeRequest.STATUS_DENIED)
        self.assertEqual(r.review_note, 'insufficient detail')

    def test_submit_flags_known_conflict(self):
        shift = Shift.objects.create(user=self.user,
                                     start_time=self.now - timedelta(hours=5),
                                     end_time=self.now - timedelta(hours=1))
        Blep.objects.create(task=self.task, user=self.user,
                            start_time=self.now - timedelta(hours=4),
                            end_time=self.now - timedelta(hours=3))
        r = ShiftChangeRequest(requester=self.user, shift=shift,
                               requested_start=self.now - timedelta(hours=5),
                               requested_end=self.now - timedelta(hours=3, minutes=30),
                               reason='left early')
        TimeChangeRequestService.submit(r)
        self.assertTrue(r.has_known_conflict)
        self.assertEqual(r.status, ShiftChangeRequest.STATUS_PENDING)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_change_request_service -v 2`
Expected: FAIL — service/methods undefined.

- [ ] **Step 3: Add `apply_requested` + `would_conflict` to each model**

`ShiftChangeRequest` (in `apps/core/models.py`):

```python
    def would_conflict(self):
        from apps.core.time_integrity import unenclosed_bleps_for_shift
        also = (self.shift.start_time, self.shift.end_time or timezone.now()) if self.shift_id else None
        return bool(unenclosed_bleps_for_shift(
            self.target_user, self.requested_start, self.requested_end, also_span=also))

    def apply_requested(self, reviewer):
        from apps.core.services import ShiftService
        if self.shift_id:
            return ShiftService.update(self.shift, actor=reviewer,
                                       start_time=self.requested_start,
                                       end_time=self.requested_end)
        return ShiftService.create(self.requester, actor=reviewer,
                                   start_time=self.requested_start,
                                   end_time=self.requested_end)
```

(`from django.utils import timezone` is already imported in core models; add if not.)

`BlepChangeRequest` (in `apps/jobs/models.py`):

```python
    def would_conflict(self):
        from apps.core.time_integrity import enclosing_shift_for_blep
        return enclosing_shift_for_blep(
            self.target_user, self.requested_start, self.requested_end) is None

    def apply_requested(self, reviewer):
        from apps.jobs.services import BlepService
        if self.blep_id:
            return BlepService.update(self.blep, actor=reviewer,
                                      start_time=self.requested_start,
                                      end_time=self.requested_end)
        return BlepService.create_historical(
            actor=reviewer, task=self.task,
            start_time=self.requested_start, end_time=self.requested_end,
            target_user=self.requester)
```

- [ ] **Step 4: Add the generic service**

In `apps/core/services.py`:

```python
class TimeChangeRequestService:
    @staticmethod
    def submit(request):
        """Validate + save a new request. Conflicts are allowed (warn-and-flag)."""
        if not (request.reason or '').strip():
            raise ValidationError("A reason is required.")
        request.has_known_conflict = request.would_conflict()
        request.save()
        return request

    @staticmethod
    def approve(request, reviewer):
        if request.status != request.STATUS_PENDING:
            raise ValidationError("Only pending requests can be approved.")
        with transaction.atomic():
            request.apply_requested(reviewer)   # raises ValidationError on invariant break
            request.status = request.STATUS_APPROVED
            request.reviewer = reviewer
            request.reviewed_at = timezone.now()
            request.save()
        return request

    @staticmethod
    def deny(request, reviewer, note=''):
        if request.status != request.STATUS_PENDING:
            raise ValidationError("Only pending requests can be denied.")
        request.status = request.STATUS_DENIED
        request.reviewer = reviewer
        request.reviewed_at = timezone.now()
        request.review_note = note or ''
        request.save()
        return request
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_change_request_service -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/core/services.py apps/core/models.py apps/jobs/models.py tests/test_change_request_service.py
git commit -m "feat(shifts): TimeChangeRequestService submit/approve/deny + per-model apply"
```

---

# Phase 2 — Backend API

### Task 8: Permission for the report (`CanManageTimeOrFinancials`)

**Files:**
- Modify: `apps/api/permissions.py`
- Test: `tests/test_permissions_combo.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_permissions_combo.py
from django.contrib.auth.models import Permission
from tests.base import BaseTestCase
from apps.core.models import User
from apps.api.permissions import CanManageTimeOrFinancials


class _Req:
    def __init__(self, user): self.user = user


class ComboPermTest(BaseTestCase):
    def _user(self, codename=None):
        u = User.objects.create_user(username=f'combo_{codename}', password='x')
        if codename:
            u.user_permissions.add(Permission.objects.get(
                codename=codename, content_type__app_label='core'))
            u = User.objects.get(pk=u.pk)
        return u

    def test_time_allowed(self):
        self.assertTrue(CanManageTimeOrFinancials().has_permission(
            _Req(self._user('can_manage_time')), None))

    def test_financials_allowed(self):
        self.assertTrue(CanManageTimeOrFinancials().has_permission(
            _Req(self._user('can_manage_financials')), None))

    def test_neither_denied(self):
        self.assertFalse(CanManageTimeOrFinancials().has_permission(
            _Req(self._user()), None))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_permissions_combo -v 2`
Expected: FAIL — name undefined.

- [ ] **Step 3: Implement**

In `apps/api/permissions.py`:

```python
class CanManageTimeOrFinancials(BasePermission):
    def has_permission(self, request, view):
        return (request.user.has_perm('core.can_manage_time')
                or request.user.has_perm('core.can_manage_financials'))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_permissions_combo -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/permissions.py tests/test_permissions_combo.py
git commit -m "feat(shifts): CanManageTimeOrFinancials permission for payroll report"
```

---

### Task 9: Shift serializer + viewset + clock endpoints + URLs

Replaces the `time_tracking` stubs and adds `/api/shifts/`.

**Files:**
- Create: `apps/api/shifts/__init__.py`, `apps/api/shifts/serializers.py`, `apps/api/shifts/views.py`, `apps/api/shifts/urls.py`
- Modify: `apps/api/time_tracking/urls.py`, `apps/api/urls.py`
- Test: `tests/test_api_shifts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_shifts.py
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, Shift


class ShiftAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.create_user(username='api_shift_u', password='x')
        self.client.force_authenticate(user=self.user)

    def test_clock_in_then_active_then_clock_out(self):
        r = self.client.post('/api/shifts/clock-in/', {}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        a = self.client.get('/api/shifts/active/')
        self.assertEqual(a.status_code, 200)
        self.assertIsNotNone(a.data['shift'])
        r2 = self.client.post('/api/shifts/clock-out/', {}, format='json')
        self.assertEqual(r2.status_code, 200, r2.data)
        a2 = self.client.get('/api/shifts/active/')
        self.assertIsNone(a2.data['shift'])

    def test_double_clock_in_400(self):
        self.client.post('/api/shifts/clock-in/', {}, format='json')
        r = self.client.post('/api/shifts/clock-in/', {}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_list_own_shifts_with_since(self):
        Shift.objects.create(user=self.user, start_time=timezone.now() - timedelta(hours=2),
                             end_time=timezone.now() - timedelta(hours=1))
        since = (timezone.now() - timedelta(days=1)).isoformat()
        r = self.client.get(f'/api/shifts/?user=me&since={since}')
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.data.get('results', r.data)), 1)

    def test_patch_recent_own_shift(self):
        s = Shift.objects.create(user=self.user, start_time=timezone.now() - timedelta(hours=3),
                                 end_time=timezone.now() - timedelta(hours=1))
        new_start = (timezone.now() - timedelta(hours=4)).isoformat()
        r = self.client.patch(f'/api/shifts/{s.pk}/',
                              {'start_time': new_start,
                               'end_time': s.end_time.isoformat()}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_shifts -v 2`
Expected: FAIL — 404/501 (routes not wired).

- [ ] **Step 3: Serializer**

```python
# apps/api/shifts/serializers.py
from rest_framework import serializers
from apps.core.models import Shift, User


class ShiftSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(),
                                              required=False, allow_null=True)

    class Meta:
        model = Shift
        fields = ['shift_id', 'user', 'user_name', 'start_time', 'end_time', 'is_open']
        read_only_fields = ['shift_id', 'user_name', 'is_open']

    def get_user_name(self, obj):
        return obj.user.get_full_name() or obj.user.username
```

- [ ] **Step 4: Viewset + clock function-views**

```python
# apps/api/shifts/views.py
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.models import Shift, User
from apps.core.services import ShiftService
from apps.api.permissions import CanManageTime
from .serializers import ShiftSerializer


def _resolve_target(request):
    """Clock self by default; managers may target ?user / body 'user'."""
    uid = request.data.get('user') or request.query_params.get('user')
    if uid and str(uid) != str(request.user.id):
        if not (request.user.is_superuser or request.user.has_perm('core.can_manage_time')):
            return None, Response({'detail': 'Not permitted to clock another user.'},
                                  status=status.HTTP_403_FORBIDDEN)
        return User.objects.get(pk=uid), None
    return request.user, None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clock_in(request):
    target, err = _resolve_target(request)
    if err:
        return err
    try:
        shift = ShiftService.clock_in(target)
    except DjangoValidationError as e:
        return Response({'detail': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
    return Response(ShiftSerializer(shift).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def clock_out(request):
    target, err = _resolve_target(request)
    if err:
        return err
    try:
        shift = ShiftService.clock_out(target)
    except DjangoValidationError as e:
        return Response({'detail': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
    return Response(ShiftSerializer(shift).data)


class ShiftViewSet(viewsets.ModelViewSet):
    """List/retrieve/patch shifts. ?user=me|<id>, ?since=<iso>."""
    serializer_class = ShiftSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Shift.objects.all().select_related('user')
        u = self.request.query_params.get('user')
        since = self.request.query_params.get('since')
        if u == 'me':
            qs = qs.filter(user=self.request.user)
        elif u:
            qs = qs.filter(user_id=u)
        if since:
            qs = qs.filter(start_time__gte=since)
        return qs

    @action(detail=False, methods=['get'], url_path='active')
    def active(self, request):
        shift = ShiftService.open_shift_for(request.user)
        return Response({'shift': ShiftSerializer(shift).data if shift else None})

    def update(self, request, *args, **kwargs):
        shift = self.get_object()
        partial = kwargs.get('partial', False)
        ser = self.get_serializer(shift, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        v = ser.validated_data
        try:
            ShiftService.update(shift, actor=request.user,
                                start_time=v.get('start_time', shift.start_time),
                                end_time=v.get('end_time', shift.end_time))
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ShiftSerializer(shift).data)

    def destroy(self, request, *args, **kwargs):
        shift = self.get_object()
        if not (request.user.is_superuser or request.user.has_perm('core.can_manage_time')):
            return Response({'detail': 'Not permitted.'}, status=status.HTTP_403_FORBIDDEN)
        shift.delete()
        return Response({'message': 'Shift deleted.'})
```

- [ ] **Step 5: URLs**

```python
# apps/api/shifts/urls.py
from django.urls import path
from .views import clock_in, clock_out

urlpatterns = [
    path('clock-in/', clock_in, name='shift-clock-in'),
    path('clock-out/', clock_out, name='shift-clock-out'),
]
```

Replace `apps/api/time_tracking/urls.py` contents with a re-export so the existing include keeps working:

```python
# apps/api/time_tracking/urls.py
from apps.api.shifts.urls import urlpatterns  # noqa: F401
```

In `apps/api/urls.py`: register the viewset on the router and ensure `/api/shifts/clock-in|out/` resolve. Add:

```python
from apps.api.shifts.views import ShiftViewSet
router.register(r'shifts', ShiftViewSet, basename='shift')
```

Find where `time_tracking.urls` is currently included under `shifts/`. It is included as `path('shifts/', include('apps.api.time_tracking.urls'))`. Router-registered `shifts/` (list/detail) and the explicit `shifts/clock-in/` must coexist — **place the explicit include BEFORE the router include** so `clock-in/`/`clock-out/`/`active/` are matched first. Verify the final ordering in `apps/api/urls.py`:

```python
urlpatterns = [
    path('shifts/', include('apps.api.shifts.urls')),   # clock-in/out (explicit)
    # ... existing patterns ...
    path('', include(router.urls)),                      # router: shifts/ list+detail+active
]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python manage.py test tests.test_api_shifts -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/shifts/ apps/api/time_tracking/urls.py apps/api/urls.py tests/test_api_shifts.py
git commit -m "feat(shifts): shift API (clock-in/out, list, active, patch); retire 501 stubs"
```

---

### Task 10: Change-request API (both types, unified queue read)

**Files:**
- Modify: `apps/api/shifts/serializers.py`, `apps/api/shifts/views.py`, `apps/api/urls.py`
- Test: `tests/test_api_change_requests.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_change_requests.py
from django.contrib.auth.models import Permission
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, Shift, ShiftChangeRequest


class ChangeRequestAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.worker = User.objects.create_user(username='cr_api_w', password='x')
        self.mgr = User.objects.create_user(username='cr_api_m', password='x')
        self.mgr.user_permissions.add(Permission.objects.get(
            codename='can_manage_time', content_type__app_label='core'))
        self.mgr = User.objects.get(pk=self.mgr.pk)
        self.now = timezone.now().replace(microsecond=0)

    def test_worker_files_shift_request(self):
        self.client.force_authenticate(user=self.worker)
        r = self.client.post('/api/shift-change-requests/', {
            'requested_start': (self.now - timedelta(hours=40)).isoformat(),
            'requested_end': (self.now - timedelta(hours=32)).isoformat(),
            'reason': 'forgot to clock in',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['status'], 'pending')

    def test_reason_required(self):
        self.client.force_authenticate(user=self.worker)
        r = self.client.post('/api/shift-change-requests/', {
            'requested_start': self.now.isoformat(),
            'requested_end': self.now.isoformat(), 'reason': '',
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_manager_approves(self):
        req = ShiftChangeRequest.objects.create(
            requester=self.worker,
            requested_start=self.now - timedelta(hours=40),
            requested_end=self.now - timedelta(hours=32), reason='x')
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(f'/api/shift-change-requests/{req.pk}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')

    def test_worker_cannot_approve(self):
        req = ShiftChangeRequest.objects.create(
            requester=self.worker, requested_start=self.now, requested_end=self.now, reason='x')
        self.client.force_authenticate(user=self.worker)
        r = self.client.post(f'/api/shift-change-requests/{req.pk}/approve/', {}, format='json')
        self.assertIn(r.status_code, (403, 401))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_change_requests -v 2`
Expected: FAIL — routes missing.

- [ ] **Step 3: Serializers**

Append to `apps/api/shifts/serializers.py`:

```python
from apps.core.models import ShiftChangeRequest
from apps.jobs.models import BlepChangeRequest


class _BaseChangeRequestSerializer(serializers.ModelSerializer):
    requester_name = serializers.SerializerMethodField()

    def get_requester_name(self, obj):
        return obj.requester.get_full_name() or obj.requester.username

    common_fields = ['request_id', 'requester', 'requester_name', 'requested_start',
                     'requested_end', 'reason', 'status', 'has_known_conflict',
                     'reviewer', 'reviewed_at', 'review_note', 'created_at']
    common_read_only = ['request_id', 'requester', 'requester_name', 'status',
                        'has_known_conflict', 'reviewer', 'reviewed_at', 'review_note',
                        'created_at']


class ShiftChangeRequestSerializer(_BaseChangeRequestSerializer):
    class Meta:
        model = ShiftChangeRequest
        fields = _BaseChangeRequestSerializer.common_fields + ['shift']
        read_only_fields = _BaseChangeRequestSerializer.common_read_only


class BlepChangeRequestSerializer(_BaseChangeRequestSerializer):
    task_name = serializers.CharField(source='task.name', read_only=True)

    class Meta:
        model = BlepChangeRequest
        fields = _BaseChangeRequestSerializer.common_fields + ['blep', 'task', 'task_name']
        read_only_fields = _BaseChangeRequestSerializer.common_read_only
```

- [ ] **Step 4: Viewsets**

Append to `apps/api/shifts/views.py`:

```python
from apps.core.models import ShiftChangeRequest
from apps.jobs.models import BlepChangeRequest
from apps.core.services import TimeChangeRequestService
from .serializers import ShiftChangeRequestSerializer, BlepChangeRequestSerializer


class _ChangeRequestViewSet(viewsets.ModelViewSet):
    """Common behaviour for shift/blep change requests."""

    def get_permissions(self):
        if self.action in ('approve', 'deny'):
            return [IsAuthenticated(), CanManageTime()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = self.queryset_model.objects.all().select_related('requester')
        status_p = self.request.query_params.get('status')
        mine = self.request.query_params.get('mine')
        if status_p:
            qs = qs.filter(status=status_p)
        if mine == 'true':
            qs = qs.filter(requester=self.request.user)
        elif not (self.request.user.is_superuser
                  or self.request.user.has_perm('core.can_manage_time')):
            qs = qs.filter(requester=self.request.user)  # non-managers see only their own
        return qs

    def create(self, request, *args, **kwargs):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        instance = self.queryset_model(requester=request.user, **ser.validated_data)
        try:
            TimeChangeRequestService.submit(instance)
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        try:
            TimeChangeRequestService.approve(self.get_object(), reviewer=request.user)
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=['post'])
    def deny(self, request, pk=None):
        note = (request.data or {}).get('note', '')
        try:
            TimeChangeRequestService.deny(self.get_object(), reviewer=request.user, note=note)
        except DjangoValidationError as e:
            return Response({'detail': e.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(self.get_object()).data)


class ShiftChangeRequestViewSet(_ChangeRequestViewSet):
    queryset_model = ShiftChangeRequest
    serializer_class = ShiftChangeRequestSerializer


class BlepChangeRequestViewSet(_ChangeRequestViewSet):
    queryset_model = BlepChangeRequest
    serializer_class = BlepChangeRequestSerializer
```

- [ ] **Step 5: Register routes**

In `apps/api/urls.py`:

```python
from apps.api.shifts.views import (ShiftViewSet, ShiftChangeRequestViewSet,
                                   BlepChangeRequestViewSet)
router.register(r'shift-change-requests', ShiftChangeRequestViewSet, basename='shift-change-request')
router.register(r'blep-change-requests', BlepChangeRequestViewSet, basename='blep-change-request')
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python manage.py test tests.test_api_change_requests -v 2`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/api/shifts/ apps/api/urls.py tests/test_api_change_requests.py
git commit -m "feat(shifts): change-request API (shift + blep) with approve/deny"
```

---

### Task 11: Payroll report endpoint

Per-worker, per-day shift times over a date range.

**Files:**
- Modify: `apps/api/shifts/views.py`, `apps/api/urls.py`
- Test: `tests/test_api_shift_report.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_shift_report.py
from django.contrib.auth.models import Permission
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, Shift


class ShiftReportAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.worker = User.objects.create_user(username='rep_w', password='x')
        self.fin = User.objects.create_user(username='rep_fin', password='x')
        self.fin.user_permissions.add(Permission.objects.get(
            codename='can_manage_financials', content_type__app_label='core'))
        self.fin = User.objects.get(pk=self.fin.pk)
        self.now = timezone.now().replace(microsecond=0)
        Shift.objects.create(user=self.worker, start_time=self.now - timedelta(hours=8),
                             end_time=self.now - timedelta(hours=1))

    def test_financials_user_can_read_report(self):
        self.client.force_authenticate(user=self.fin)
        start = (self.now - timedelta(days=1)).date().isoformat()
        end = self.now.date().isoformat()
        r = self.client.get(f'/api/shifts/report/?start={start}&end={end}')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('workers', r.data)

    def test_plain_user_denied(self):
        self.client.force_authenticate(user=self.worker)
        r = self.client.get('/api/shifts/report/?start=2026-05-01&end=2026-05-31')
        self.assertEqual(r.status_code, 403)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_shift_report -v 2`
Expected: FAIL — route missing.

- [ ] **Step 3: Implement the report view**

Append to `apps/api/shifts/views.py`:

```python
from collections import defaultdict
from datetime import datetime, time
from django.utils import timezone as dj_tz
from apps.api.permissions import CanManageTimeOrFinancials


@api_view(['GET'])
@permission_classes([IsAuthenticated, CanManageTimeOrFinancials])
def shift_report(request):
    start_s = request.query_params.get('start')
    end_s = request.query_params.get('end')
    if not start_s or not end_s:
        return Response({'detail': 'start and end (YYYY-MM-DD) are required.'},
                        status=status.HTTP_400_BAD_REQUEST)
    tz = dj_tz.get_current_timezone()
    start_dt = dj_tz.make_aware(datetime.combine(datetime.fromisoformat(start_s).date(), time.min), tz)
    end_dt = dj_tz.make_aware(datetime.combine(datetime.fromisoformat(end_s).date(), time.max), tz)

    qs = (Shift.objects.filter(start_time__gte=start_dt, start_time__lte=end_dt)
          .select_related('user').order_by('user__username', 'start_time'))
    if request.query_params.get('user'):
        qs = qs.filter(user_id=request.query_params['user'])

    workers = defaultdict(lambda: {'user_id': None, 'name': '', 'days': defaultdict(list),
                                   'total_minutes': 0})
    for s in qs:
        w = workers[s.user_id]
        w['user_id'] = s.user_id
        w['name'] = s.user.get_full_name() or s.user.username
        local_start = dj_tz.localtime(s.start_time)
        end = s.end_time or dj_tz.now()
        minutes = max(0, int((end - s.start_time).total_seconds() // 60))
        w['days'][local_start.date().isoformat()].append({
            'shift_id': s.shift_id,
            'start': s.start_time.isoformat(),
            'end': s.end_time.isoformat() if s.end_time else None,
            'minutes': minutes,
            'open': s.end_time is None,
        })
        w['total_minutes'] += minutes

    result = []
    for w in workers.values():
        result.append({
            'user_id': w['user_id'], 'name': w['name'], 'total_minutes': w['total_minutes'],
            'days': [{'date': d, 'shifts': shifts} for d, shifts in sorted(w['days'].items())],
        })
    return Response({'start': start_s, 'end': end_s, 'workers': result})
```

- [ ] **Step 4: Route it**

In `apps/api/shifts/urls.py` add (these explicit paths are included under `shifts/` before the router):

```python
from .views import clock_in, clock_out, shift_report

urlpatterns = [
    path('clock-in/', clock_in, name='shift-clock-in'),
    path('clock-out/', clock_out, name='shift-clock-out'),
    path('report/', shift_report, name='shift-report'),
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_api_shift_report -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/shifts/ tests/test_api_shift_report.py
git commit -m "feat(shifts): payroll shift-time report endpoint"
```

---

# Phase 3 — Frontend

> Frontend tasks are verified by `cd frontend && npm run build` (must succeed) plus manual reasoning; this codebase has no JS unit harness. Each task ends with a successful build + commit.

### Task 12: Login lands on Home

**Files:**
- Modify: `frontend/src/routes/LoginPage.svelte`
- Test: build + manual.

- [ ] **Step 1: Add the redirect**

In `frontend/src/routes/LoginPage.svelte`, import the router push and navigate after a successful login:

```svelte
<script>
  import { push } from 'svelte-spa-router';
  import { login } from '../stores/auth.js';

  let username = '';
  let password = '';
  let error = '';

  async function handleSubmit() {
    error = '';
    try {
      await login(username, password);
      push('/');           // always land on Home regardless of prior hash
    } catch (e) {
      error = e.message || 'Login failed';
    }
  }
</script>
```

(Leave the existing template unchanged.)

- [ ] **Step 2: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/LoginPage.svelte
git commit -m "feat(shifts): land on Home after login"
```

---

### Task 13: Shift store

**Files:**
- Create: `frontend/src/stores/shift.js`

- [ ] **Step 1: Create the store**

```javascript
// frontend/src/stores/shift.js
import { writable } from 'svelte/store';
import { api } from '../lib/api.js';

export const currentShift = writable(null);   // open shift object or null
export const shiftActivityVersion = writable(0);

export async function refreshCurrentShift() {
  try {
    const data = await api.get('/api/shifts/active/');
    currentShift.set(data.shift);
  } catch {
    currentShift.set(null);
  }
}

export async function notifyShiftChanged() {
  await refreshCurrentShift();
  shiftActivityVersion.update((n) => n + 1);
}
```

- [ ] **Step 2: Build + commit**

```bash
cd frontend && npm run build
git add frontend/src/stores/shift.js
git commit -m "feat(shifts): currentShift store + change notifier"
```

---

### Task 14: Generalize `BlepEditModal` → `TimeEditModal`

A single modal handling `recordType` ('shift'|'blep') × `action` ('edit'|'create'|'request'). It does live conflict detection and disables Save on a broken invariant (with a message); in `request` mode it shows a required reason field and warns (does not block) on conflict.

**Files:**
- Create: `frontend/src/components/time/TimeEditModal.svelte`
- Modify: `frontend/src/components/tasks/BlepEditModal.svelte` (re-export TimeEditModal preset to blep/edit so existing call sites keep working)

- [ ] **Step 1: Create `TimeEditModal.svelte`**

```svelte
<!-- frontend/src/components/time/TimeEditModal.svelte -->
<script>
  import { api } from '../../lib/api.js';
  import { modalKeys } from '../../lib/modalKeys.js';
  import { notifyBlepChanged } from '../../stores/blepActivity.js';
  import { notifyShiftChanged } from '../../stores/shift.js';

  let {
    open = false,
    recordType = 'blep',          // 'blep' | 'shift'
    action = 'edit',              // 'edit' | 'create' | 'request'
    record = null,                // existing record when editing/requesting-amend
    taskId = null,                // blep create/request needs a task
    currentUser,
    userPermissions = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  const canManageTime = $derived(userPermissions.includes('can_manage_time'));

  let startTime = $state('');
  let endTime = $state('');
  let reason = $state('');
  let targetUserId = $state('');
  let users = $state([]);
  let busy = $state(false);
  let error = $state('');
  let conflictMsg = $state('');     // soft conflict text

  function isoToLocal(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  function localToIso(local) { return local ? new Date(local).toISOString() : null; }

  async function loadUsers() {
    try { users = await api.get('/api/auth/users/'); } catch { users = []; }
  }

  $effect(() => {
    if (open) {
      startTime = record ? isoToLocal(record.start_time) : '';
      endTime = record ? isoToLocal(record.end_time) : '';
      reason = '';
      conflictMsg = '';
      error = '';
      const rid = recordType === 'shift' ? record?.user : record?.user;
      targetUserId = String(rid ?? currentUser?.id ?? '');
      if (canManageTime) loadUsers();
    }
  });

  // Soft conflict detection: ask the server what the counterpart records look like.
  async function checkConflict() {
    conflictMsg = '';
    const s = localToIso(startTime), e = localToIso(endTime);
    if (!s || !e) return;
    const uid = targetUserId || currentUser?.id;
    try {
      if (recordType === 'shift') {
        // any of this user's bleps not enclosed by [s,e]?
        const resp = await api.get(`/api/bleps/?user=${uid}&since=${encodeURIComponent(s)}`);
        const bleps = resp.results || resp;
        const bad = bleps.filter(b => b.end_time &&
          !(new Date(s) <= new Date(b.start_time) && new Date(b.end_time) <= new Date(e)) &&
          (new Date(b.start_time) < new Date(e) && new Date(b.end_time) > new Date(s)));
        if (bad.length) conflictMsg =
          `This shift would not cover blep(s) on ${bad.map(b => b.task_name).join(', ')}.`;
      } else {
        const resp = await api.get(`/api/shifts/?user=${uid}&since=${encodeURIComponent(
          new Date(new Date(s).getTime() - 86400000).toISOString())}`);
        const shifts = (resp.results || resp).filter(sh => sh.end_time);
        const enclosed = shifts.some(sh =>
          new Date(sh.start_time) <= new Date(s) && new Date(e) <= new Date(sh.end_time));
        if (!enclosed) conflictMsg = 'No shift covers this time — widen the enclosing shift first.';
      }
    } catch { /* soft check only */ }
  }

  // Save disabled on a hard block (edit/create with a conflict). Request mode warns only.
  const blocked = $derived(action !== 'request' && !!conflictMsg);

  async function save() {
    busy = true; error = '';
    const payload = { start_time: localToIso(startTime), end_time: localToIso(endTime) };
    if (canManageTime && targetUserId) payload.user = Number(targetUserId);
    try {
      if (action === 'request') {
        payload.reason = reason;
        if (recordType === 'shift') {
          if (record) payload.shift = record.shift_id;
          await api.post('/api/shift-change-requests/', payload);
        } else {
          payload.task = record ? record.task : taskId;
          if (record) payload.blep = record.blep_id;
          await api.post('/api/blep-change-requests/', payload);
        }
      } else if (recordType === 'shift') {
        if (action === 'edit') await api.patch(`/api/shifts/${record.shift_id}/`, payload);
        else await api.post('/api/shifts/', payload);    // manager create (rare)
      } else {
        if (action === 'edit') await api.patch(`/api/bleps/${record.blep_id}/`, payload);
        else { payload.task = taskId; await api.post('/api/bleps/', payload); }
      }
      if (recordType === 'shift') await notifyShiftChanged(); else await notifyBlepChanged();
      onSaved();
    } catch (e) {
      error = e.message || 'Could not save.';
    } finally { busy = false; }
  }
</script>

{#if open}
  <div class="overlay" use:modalKeys={{ onSave: () => { if (!busy && !blocked) save(); }, onCancel: onClose }}>
    <div class="modal">
      <h3>{action === 'request' ? 'Request change' : action === 'create' ? 'Add' : 'Edit'}
          {recordType === 'shift' ? 'shift' : 'time entry'}</h3>
      <p><label><strong>Start</strong><br>
        <input type="datetime-local" bind:value={startTime} onblur={checkConflict}></label></p>
      <p><label><strong>End</strong><br>
        <input type="datetime-local" bind:value={endTime} onblur={checkConflict}></label></p>

      {#if action === 'request'}
        <p><label><strong>Reason *</strong><br>
          <textarea bind:value={reason} required></textarea></label></p>
      {/if}

      {#if canManageTime && action !== 'request'}
        <p><label><strong>User (manager only)</strong><br>
          <select bind:value={targetUserId}>
            <option value="">-- Select user --</option>
            {#each users as u}<option value={String(u.id)}>{u.name} ({u.username})</option>{/each}
          </select></label></p>
      {/if}

      {#if conflictMsg}
        <p class={blocked ? 'error' : 'warn'}>{conflictMsg}
          {#if blocked}<br><em>Fix the conflicting record first, then save.</em>{/if}</p>
      {/if}

      <div class="buttons">
        <button type="button" onclick={save} disabled={busy || blocked || (action === 'request' && !reason.trim())}>
          {action === 'request' ? 'Submit request' : 'Save'}
        </button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </div>
  </div>
{/if}

<style>
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex;
             align-items: center; justify-content: center; z-index: 200; }
  .modal { background: white; padding: 1.5em; border: 2px solid #333; max-width: 420px; width: 90%; }
  .buttons { display: flex; gap: 0.5em; margin-top: 1em; }
  .error { color: #b91c1c; }
  .warn { color: #b45309; }
  textarea { width: 100%; min-height: 3em; }
</style>
```

- [ ] **Step 2: Point `BlepEditModal` at the generalized modal**

Replace `frontend/src/components/tasks/BlepEditModal.svelte` body with a thin adapter so existing call sites (task detail) keep working:

```svelte
<script>
  import TimeEditModal from '../time/TimeEditModal.svelte';
  let { open = false, mode = 'edit', blep = null, taskId = null,
        currentUser, userPermissions = [], onSaved = () => {}, onClose = () => {} } = $props();
</script>

<TimeEditModal {open} recordType="blep" action={mode} record={blep} {taskId}
  {currentUser} {userPermissions} {onSaved} {onClose} />
```

- [ ] **Step 3: Build**

Run: `cd frontend && npm run build`
Expected: build succeeds (task-detail blep edit still compiles).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/time/TimeEditModal.svelte frontend/src/components/tasks/BlepEditModal.svelte
git commit -m "feat(shifts): generalize BlepEditModal into TimeEditModal (edit/create/request, shift/blep)"
```

---

### Task 15: Clock In/Out band on Home

**Files:**
- Create: `frontend/src/components/home/ClockBand.svelte`
- Modify: `frontend/src/routes/Home.svelte`

- [ ] **Step 1: Create `ClockBand.svelte`**

```svelte
<!-- frontend/src/components/home/ClockBand.svelte -->
<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import { currentShift, refreshCurrentShift, notifyShiftChanged } from '../../stores/shift.js';

  let busy = $state(false);
  let error = $state('');
  let now = $state(Date.now());

  onMount(() => {
    refreshCurrentShift();
    const t = setInterval(() => { now = Date.now(); }, 30000);
    return () => clearInterval(t);
  });

  function elapsed(iso) {
    const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
    const h = Math.floor(mins / 60), m = mins % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  async function clockIn() {
    busy = true; error = '';
    try { await api.post('/api/shifts/clock-in/', {}); await notifyShiftChanged(); }
    catch (e) { error = e.message || 'Could not clock in.'; } finally { busy = false; }
  }
  async function clockOut() {
    busy = true; error = '';
    try { await api.post('/api/shifts/clock-out/', {}); await notifyShiftChanged(); }
    catch (e) { error = e.message || 'Could not clock out.'; } finally { busy = false; }
  }
</script>

<div class="clock-band">
  {#if $currentShift}
    <span class="status on">On the clock — {elapsed($currentShift.start_time)}</span>
    <button type="button" class="big" onclick={clockOut} disabled={busy}>Clock Out</button>
  {:else}
    <span class="status off">Not clocked in</span>
    <button type="button" class="big" onclick={clockIn} disabled={busy}>Clock In</button>
  {/if}
  {#if error}<span class="error">{error}</span>{/if}
</div>

<style>
  .clock-band { display: flex; align-items: center; gap: 1em; padding: 0.75em 1em;
                background: #f0f7ff; border: 2px solid #2563eb; margin-bottom: 1em; }
  .status.on { color: #16a34a; font-weight: 700; }
  .status.off { color: #555; }
  .big { font-size: 1.1em; padding: 0.5em 1.5em; }
  .error { color: #b91c1c; }
</style>
```

- [ ] **Step 2: Mount it on Home (above the tabs)**

In `frontend/src/routes/Home.svelte`, import and place `<ClockBand />` between `<SearchBox />` and `<nav class="home-tabs">`:

```svelte
  import ClockBand from '../components/home/ClockBand.svelte';
```
```svelte
<SearchBox />
<ClockBand />
<nav class="home-tabs">
```

- [ ] **Step 3: Build + commit**

```bash
cd frontend && npm run build
git add frontend/src/components/home/ClockBand.svelte frontend/src/routes/Home.svelte
git commit -m "feat(shifts): Clock In/Out band on Home"
```

---

### Task 16: `ShiftLogTable` + My Shifts / My Requests on Time tab; wire blep Request Edit

**Files:**
- Create: `frontend/src/components/time/ShiftLogTable.svelte`
- Create: `frontend/src/components/home/MyShiftsList.svelte`
- Create: `frontend/src/components/home/MyChangeRequestsList.svelte`
- Modify: `frontend/src/components/home/RecentTimeList.svelte`
- Modify: `frontend/src/routes/Home.svelte` (Time tab)

- [ ] **Step 1: `ShiftLogTable.svelte` (mirrors BlepLogTable)**

```svelte
<!-- frontend/src/components/time/ShiftLogTable.svelte -->
<script>
  import { onMount, onDestroy } from 'svelte';
  let { shifts = [], showWorker = false, actions = undefined } = $props();
  let now = $state(Date.now());
  const DOW = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

  function fmt(iso) {
    if (!iso) return '—';
    const d = new Date(iso); let h = d.getHours(); const ap = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    return `${DOW[d.getDay()]} ${h}:${String(d.getMinutes()).padStart(2,'0')} ${ap}`;
  }
  function dur(s) {
    const end = s.end_time ? new Date(s.end_time).getTime() : now;
    const mins = Math.max(0, Math.round((end - new Date(s.start_time).getTime())/60000));
    const h = Math.floor(mins/60), m = mins % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }
  let tick;
  onMount(() => { tick = setInterval(() => now = Date.now(), 30000); });
  onDestroy(() => tick && clearInterval(tick));
</script>

<table class="data-table">
  <thead><tr>
    {#if showWorker}<th>Worker</th>{/if}
    <th>Clock In</th><th>Clock Out</th><th>Duration</th>{#if actions}<th></th>{/if}
  </tr></thead>
  <tbody>
    {#each shifts as s (s.shift_id)}
      <tr>
        {#if showWorker}<td>{s.user_name || '—'}</td>{/if}
        <td>{fmt(s.start_time)}</td>
        <td>{#if s.end_time}{fmt(s.end_time)}{:else}<span class="active-tag">open</span>{/if}</td>
        <td>{dur(s)}</td>
        {#if actions}<td>{@render actions(s)}</td>{/if}
      </tr>
    {/each}
  </tbody>
</table>

<style>.active-tag { color: #16a34a; font-weight: 600; }</style>
```

- [ ] **Step 2: `MyShiftsList.svelte`**

```svelte
<!-- frontend/src/components/home/MyShiftsList.svelte -->
<script>
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import { shiftActivityVersion } from '../../stores/shift.js';
  import ShiftLogTable from '../time/ShiftLogTable.svelte';
  import TimeEditModal from '../time/TimeEditModal.svelte';

  let shifts = $state([]);
  let loading = $state(true);
  let modalOpen = $state(false);
  let editing = $state(null);
  let modalAction = $state('edit');

  const perms = $derived($userStore?.permissions || []);
  const canManageTime = $derived(perms.includes('can_manage_time'));

  function within30h(iso) { return Date.now() - new Date(iso).getTime() < 30 * 3600 * 1000; }
  function isEditable(s) { return canManageTime || within30h(s.start_time); }

  async function load() {
    loading = true;
    try {
      const since = new Date(Date.now() - 7 * 86400000).toISOString();
      const resp = await api.get(`/api/shifts/?user=me&since=${encodeURIComponent(since)}`);
      shifts = resp.results || resp;
    } finally { loading = false; }
  }
  function openEdit(s) { editing = s; modalAction = 'edit'; modalOpen = true; }
  function openRequest(s) { editing = s; modalAction = 'request'; modalOpen = true; }
  async function onSaved() { modalOpen = false; editing = null; await load(); }

  $effect(() => { load(); });
  let last = $state(0);
  $effect(() => { const v = $shiftActivityVersion; if (v !== last) { last = v; load(); } });
</script>

<section>
  <h3>My Shifts</h3>
  {#if loading}<p>Loading…</p>
  {:else if shifts.length === 0}<p>No recent shifts.</p>
  {:else}
    <ShiftLogTable {shifts}>
      {#snippet actions(s)}
        {#if isEditable(s)}
          <button type="button" onclick={() => openEdit(s)}>Edit</button>
        {:else}
          <button type="button" onclick={() => openRequest(s)}>Request Change</button>
        {/if}
      {/snippet}
    </ShiftLogTable>
  {/if}
</section>

<TimeEditModal open={modalOpen} recordType="shift" action={modalAction} record={editing}
  currentUser={$userStore} userPermissions={perms} onSaved={onSaved} onClose={() => { modalOpen = false; editing = null; }} />
```

- [ ] **Step 3: `MyChangeRequestsList.svelte`**

```svelte
<!-- frontend/src/components/home/MyChangeRequestsList.svelte -->
<script>
  import { api } from '../../lib/api.js';
  import { shiftActivityVersion } from '../../stores/shift.js';
  import { blepActivityVersion } from '../../stores/blepActivity.js';

  let rows = $state([]);
  let loading = $state(true);

  async function load() {
    loading = true;
    try {
      const [sh, bl] = await Promise.all([
        api.get('/api/shift-change-requests/?mine=true'),
        api.get('/api/blep-change-requests/?mine=true'),
      ]);
      const tag = (list, kind) => (list.results || list).map(r => ({ ...r, kind }));
      rows = [...tag(sh, 'Shift'), ...tag(bl, 'Time')]
        .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    } finally { loading = false; }
  }
  $effect(() => { load(); });
  let lastS = $state(0), lastB = $state(0);
  $effect(() => { const v = $shiftActivityVersion; if (v !== lastS) { lastS = v; load(); } });
  $effect(() => { const v = $blepActivityVersion; if (v !== lastB) { lastB = v; load(); } });
</script>

<section>
  <h3>My Change Requests</h3>
  {#if loading}<p>Loading…</p>
  {:else if rows.length === 0}<p>No change requests.</p>
  {:else}
    <table class="data-table">
      <thead><tr><th>Type</th><th>Requested</th><th>Status</th><th>Reason</th></tr></thead>
      <tbody>
        {#each rows as r (r.kind + r.request_id)}
          <tr>
            <td>{r.kind}</td>
            <td>{new Date(r.requested_start).toLocaleString()} → {r.requested_end ? new Date(r.requested_end).toLocaleString() : '—'}</td>
            <td>{r.status}{#if r.has_known_conflict && r.status === 'pending'} ⚠{/if}</td>
            <td>{r.reason}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>
```

- [ ] **Step 4: Wire blep Request Edit + 30h in `RecentTimeList.svelte`**

Replace the `within24h` helper with `within30h` (30 * 60 * 60 * 1000), and replace the `requestEdit` stub so the "Request Edit" button opens `TimeEditModal` in request mode. Switch its import from `BlepEditModal` to `TimeEditModal` and render:

```svelte
  import TimeEditModal from '../time/TimeEditModal.svelte';
  // ...
  let modalAction = $state('edit');
  function openEdit(blep) { editingBlep = blep; modalAction = 'edit'; modalOpen = true; }
  function requestEdit(blep) { editingBlep = blep; modalAction = 'request'; modalOpen = true; }
```
```svelte
<TimeEditModal open={modalOpen} recordType="blep" action={modalAction} record={editingBlep}
  currentUser={$userStore} userPermissions={userPermissions}
  onSaved={handleSaved} onClose={closeModal} />
```

Update the `actions` snippet to pass the blep: `<button type="button" onclick={() => requestEdit(blep)}>Request Edit</button>`. Change `within24h` references in `isEditable` to `within30h`.

- [ ] **Step 5: Add the two lists to the Home Time tab**

In `frontend/src/routes/Home.svelte`, import `MyShiftsList` and `MyChangeRequestsList`, and in the `{:else if tab === 'time'}` block render them with the existing lists:

```svelte
{:else if tab === 'time'}
  <MyShiftsList />
  <RecentTimeList />
  <MyChangeRequestsList />
  <RecentLoginsList />
```

- [ ] **Step 6: Build + commit**

```bash
cd frontend && npm run build
git add frontend/src/components/time/ShiftLogTable.svelte frontend/src/components/home/MyShiftsList.svelte frontend/src/components/home/MyChangeRequestsList.svelte frontend/src/components/home/RecentTimeList.svelte frontend/src/routes/Home.svelte
git commit -m "feat(shifts): My Shifts + Request Change + My Requests on Home Time tab"
```

---

### Task 17: Manager Shifts tab — request queue + payroll report

**Files:**
- Create: `frontend/src/components/users/ShiftRequestQueue.svelte`
- Create: `frontend/src/components/users/PayrollReport.svelte`
- Modify: `frontend/src/routes/users/UserListPage.svelte` (add tabs)

- [ ] **Step 1: `ShiftRequestQueue.svelte`**

```svelte
<!-- frontend/src/components/users/ShiftRequestQueue.svelte -->
<script>
  import { api } from '../../lib/api.js';

  let rows = $state([]);
  let loading = $state(true);
  let error = $state('');

  async function load() {
    loading = true; error = '';
    try {
      const [sh, bl] = await Promise.all([
        api.get('/api/shift-change-requests/?status=pending'),
        api.get('/api/blep-change-requests/?status=pending'),
      ]);
      const tag = (list, kind, ep) => (list.results || list).map(r => ({ ...r, kind, ep }));
      rows = [...tag(sh, 'Shift', 'shift-change-requests'),
              ...tag(bl, 'Time', 'blep-change-requests')]
        .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    } catch (e) { error = e.message || 'Could not load requests.'; }
    finally { loading = false; }
  }

  async function approve(r) {
    error = '';
    try { await api.post(`/api/${r.ep}/${r.request_id}/approve/`); await load(); }
    catch (e) { error = e.message || 'Approve failed (resolve the conflict first).'; }
  }
  async function deny(r) {
    const note = prompt('Reason for denial (optional):') ?? '';
    try { await api.post(`/api/${r.ep}/${r.request_id}/deny/`, { note }); await load(); }
    catch (e) { error = e.message || 'Deny failed.'; }
  }

  $effect(() => { load(); });
</script>

<section>
  <h3>Pending Time Change Requests</h3>
  {#if error}<p style="color:#b91c1c">{error}</p>{/if}
  {#if loading}<p>Loading…</p>
  {:else if rows.length === 0}<p>No pending requests.</p>
  {:else}
    <table class="data-table">
      <thead><tr><th>Type</th><th>Worker</th><th>Requested</th><th>Reason</th><th>Conflict</th><th>Actions</th></tr></thead>
      <tbody>
        {#each rows as r (r.kind + r.request_id)}
          <tr>
            <td>{r.kind}</td>
            <td>{r.requester_name}</td>
            <td>{new Date(r.requested_start).toLocaleString()} → {r.requested_end ? new Date(r.requested_end).toLocaleString() : '—'}</td>
            <td>{r.reason}</td>
            <td>{r.has_known_conflict ? '⚠ yes' : '—'}</td>
            <td>
              <button type="button" onclick={() => approve(r)}>Approve</button>
              <button type="button" onclick={() => deny(r)}>Deny</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p><em>If Approve fails with a conflict, edit the conflicting shift/blep (via the worker's
      record) so the shift encloses the blep, then approve again.</em></p>
  {/if}
</section>
```

- [ ] **Step 2: `PayrollReport.svelte` (date-range picker)**

```svelte
<!-- frontend/src/components/users/PayrollReport.svelte -->
<script>
  import { api } from '../../lib/api.js';

  function isoDate(d) { return d.toISOString().slice(0, 10); }
  let start = $state(isoDate(new Date(Date.now() - 6 * 86400000)));
  let end = $state(isoDate(new Date()));
  let workers = $state([]);
  let loading = $state(false);
  let error = $state('');

  function hm(mins) { return `${Math.floor(mins / 60)}h ${mins % 60}m`; }

  async function load() {
    loading = true; error = '';
    try {
      const r = await api.get(`/api/shifts/report/?start=${start}&end=${end}`);
      workers = r.workers;
    } catch (e) { error = e.message || 'Could not load report.'; }
    finally { loading = false; }
  }
  $effect(() => { load(); });
</script>

<section>
  <h3>Payroll — Shift Hours</h3>
  <fieldset style="margin-bottom:10px">
    <legend>Range</legend>
    <label>From <input type="date" bind:value={start} onchange={load}></label>
    <label>To <input type="date" bind:value={end} onchange={load}></label>
  </fieldset>
  {#if error}<p style="color:#b91c1c">{error}</p>{/if}
  {#if loading}<p>Loading…</p>
  {:else if workers.length === 0}<p>No shifts in range.</p>
  {:else}
    {#each workers as w (w.user_id)}
      <h4>{w.name} — total {hm(w.total_minutes)}</h4>
      <table class="data-table">
        <thead><tr><th>Date</th><th>Shifts</th><th>Day total</th></tr></thead>
        <tbody>
          {#each w.days as d (d.date)}
            <tr>
              <td>{d.date}</td>
              <td>{d.shifts.map(s => `${new Date(s.start).toLocaleTimeString()}–${s.end ? new Date(s.end).toLocaleTimeString() : 'open'}`).join(', ')}</td>
              <td>{hm(d.shifts.reduce((t, s) => t + s.minutes, 0))}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/each}
  {/if}
</section>
```

- [ ] **Step 3: Add tabs to `UserListPage.svelte`**

Wrap the existing user table in a tab and add a Shifts tab hosting the queue + report. Add to the `<script>`:

```svelte
  import { user as userStore } from '../../stores/auth.js';
  import ShiftRequestQueue from '../../components/users/ShiftRequestQueue.svelte';
  import PayrollReport from '../../components/users/PayrollReport.svelte';
  let tab = $state('users');
  const perms = $derived($userStore?.permissions || []);
  const canSeeShifts = $derived(perms.includes('can_manage_time') || perms.includes('can_manage_financials') || $userStore?.is_superuser);
```

Above the existing table markup:

```svelte
<nav class="home-tabs">
  <button class:active={tab === 'users'} onclick={() => tab = 'users'}>Users</button>
  {#if canSeeShifts}
    <button class:active={tab === 'shifts'} onclick={() => tab = 'shifts'}>Shifts</button>
  {/if}
</nav>

{#if tab === 'shifts'}
  <ShiftRequestQueue />
  <PayrollReport />
{:else}
  <!-- existing users table here -->
{/if}
```

(Reuse the `.home-tabs` styles — copy the block from `Home.svelte` into this component's `<style>`.)

- [ ] **Step 4: Build + commit**

```bash
cd frontend && npm run build
git add frontend/src/components/users/ShiftRequestQueue.svelte frontend/src/components/users/PayrollReport.svelte frontend/src/routes/users/UserListPage.svelte
git commit -m "feat(shifts): manager Shifts tab — request queue + payroll report"
```

---

# Phase 4 — Backfill & docs

### Task 18: Full backend regression run

- [ ] **Step 1: Run the whole suite once (single agent only)**

Run: `python manage.py test -v 1`
Expected: PASS. Fix any regressions (most likely: existing tests that create bleps without an enclosing shift now hit the Task 5 guard — give those tests a covering `Shift` in their setUp; do NOT relax production logic).

- [ ] **Step 2: Commit any test fixes**

```bash
git add tests/
git commit -m "test(shifts): give blep-creating tests an enclosing shift"
```

---

### Task 19: Backfill management command (human-run)

Creates enclosing shifts for existing bleps so the invariant holds before browser testing. **Idempotent; the human runs it.**

**Files:**
- Create: `apps/core/management/commands/backfill_shifts.py`
- Test: `tests/test_backfill_shifts.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backfill_shifts.py
from django.core.management import call_command
from django.utils import timezone
from datetime import timedelta
from tests.base import BaseTestCase
from apps.core.models import User, Shift
from apps.jobs.models import Job, Task, Blep


class BackfillShiftsTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username='backfill_u', password='x')
        self.job = Job.objects.first()
        self.task = Task.objects.create(name='T', job=self.job, rate_scheme_id=1)
        self.day = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0) - timedelta(days=2)
        Blep.objects.create(task=self.task, user=self.user,
                            start_time=self.day, end_time=self.day + timedelta(hours=1))
        Blep.objects.create(task=self.task, user=self.user,
                            start_time=self.day + timedelta(hours=2),
                            end_time=self.day + timedelta(hours=4))

    def test_creates_enclosing_shift_for_day(self):
        call_command('backfill_shifts')
        shifts = Shift.objects.filter(user=self.user)
        self.assertEqual(shifts.count(), 1)
        s = shifts.first()
        self.assertLessEqual(s.start_time, self.day)
        self.assertGreaterEqual(s.end_time, self.day + timedelta(hours=4))

    def test_idempotent(self):
        call_command('backfill_shifts')
        call_command('backfill_shifts')
        self.assertEqual(Shift.objects.filter(user=self.user).count(), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_backfill_shifts -v 2`
Expected: FAIL — command not found.

- [ ] **Step 3: Implement the command**

```python
# apps/core/management/commands/backfill_shifts.py
from collections import defaultdict
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from apps.core.models import Shift
from apps.jobs.models import Blep
from apps.core.time_integrity import enclosing_shift_for_blep


class Command(BaseCommand):
    help = "Create enclosing Shifts for existing bleps (idempotent). Run before browser testing."

    def handle(self, *args, **opts):
        bleps = (Blep.objects.filter(user__isnull=False, end_time__isnull=False)
                 .select_related('user').order_by('user_id', 'start_time'))
        # group by (user, local date)
        groups = defaultdict(list)
        skipped = 0
        for b in bleps:
            if enclosing_shift_for_blep(b.user, b.start_time, b.end_time):
                continue  # already covered — idempotent
            local_date = timezone.localtime(b.start_time).date()
            groups[(b.user_id, local_date)].append(b)

        created = 0
        with transaction.atomic():
            for (user_id, _date), group in groups.items():
                start = min(b.start_time for b in group)
                end = max(b.end_time for b in group)
                Shift.objects.create(user_id=user_id, start_time=start, end_time=end)
                created += 1

        # report bleps we cannot place (open or null-user)
        orphan = Blep.objects.filter(user__isnull=True).count()
        open_bleps = Blep.objects.filter(end_time__isnull=True).count()
        self.stdout.write(self.style.SUCCESS(f"Created {created} shift(s)."))
        if orphan:
            self.stdout.write(self.style.WARNING(f"{orphan} blep(s) have no user — not enclosed."))
        if open_bleps:
            self.stdout.write(self.style.WARNING(f"{open_bleps} open blep(s) skipped (no end_time)."))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_backfill_shifts -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/core/management/commands/backfill_shifts.py tests/test_backfill_shifts.py
git commit -m "feat(shifts): idempotent backfill_shifts management command (human-run)"
```

- [ ] **Step 6: Hand-off note**

In your completion summary, tell the human: after applying migrations (`migrate`), run `python manage.py backfill_shifts` once **before** browser-testing with fixture data, and review any WARNING lines about null-user / open bleps.

---

### Task 20: Update durable docs

**Files:** `docs/designs/data-constraints.md`, `docs/designs/users-and-permissions.md`, `docs/designs/architecture-and-conventions.md`, `docs/designs/jobs-tasks-and-worksheets.md`

- [ ] **Step 1: data-constraints.md** — add the enclosure invariant (verbatim from spec §3), the `Shift` field constraints (user required, one open shift per user enforced in service, multiple shifts/day allowed), and the `shifts` / `shift_change_requests` / `blep_change_requests` `db_table` names.

- [ ] **Step 2: users-and-permissions.md** — promote the shift stub endpoints to live: `POST /api/shifts/clock-in|out/` (self `IsAuthenticated`, on-behalf `can_manage_time`); `GET/PATCH /api/shifts/`, `/active/`; `shift-change-requests`/`blep-change-requests` (create/list `IsAuthenticated`; approve/deny `can_manage_time`); `GET /api/shifts/report/` (`can_manage_time` OR `can_manage_financials`). Note login lands on Home.

- [ ] **Step 3: architecture-and-conventions.md** — note `TimeEditModal` (generalized from `BlepEditModal`); shift endpoints are live (remove the 501-stub references for `/api/shifts/...`); `@history` on `Shift` + change-request models; the `_ChangeRequestViewSet` shared base.

- [ ] **Step 4: jobs-tasks-and-worksheets.md** — document the Blep auto-clock-in (starting a blep opens a shift) and clock-out-closes-open-bleps lifecycle, plus the enclosure guard on blep create/edit, in the Blep section.

- [ ] **Step 5: Commit**

```bash
git add docs/designs/
git commit -m "docs(shifts): update data-constraints, permissions, architecture, jobs docs"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** clock in/out (T3, T9, T15) · auto-clock-in (T5) · clock-out closes bleps (T3) · review my shifts (T16) · update most-recent shift / 30h window (T4, T16) · request change older shift, amend+create (T6, T7, T10, T16) · symmetric blep requests (T6, T7, T10, T16) · enclosure invariant + conflict UI warn/block/jump (T2, T4, T5, T7, T14, T17) · manager approve/deny on Users tab (T10, T17) · payroll report w/ date range + can_manage_time||financials (T8, T11, T17) · login lands on Home (T12) · `@history` (T1, T6) · backfill, no exemption (T19) · docs (T20). All spec sections map to a task.
- **Placeholder scan:** none — every code step carries real code; the only `pass` is an intentional no-op with an explanatory comment in `unenclosed_bleps_for_shift`.
- **Type consistency:** `ShiftService.open_shift_for/clock_in/clock_out/ensure_open_shift/update/create`, `TimeChangeRequestService.submit/approve/deny`, `would_conflict`/`apply_requested`, `enclosing_shift_for_blep`/`unenclosed_bleps_for_shift`, `currentShift`/`refreshCurrentShift`/`notifyShiftChanged`, `TimeEditModal` props (`recordType`/`action`/`record`) used consistently across backend, API, and frontend tasks.

## Known follow-ups (out of scope, already logged)

- `Blep.user` should become non-nullable once orphan bleps are cleaned up (`docs/designs/LATER.md`).
- Deferred per spec §12: stale-shift auto-close (cron), clocked-vs-logged comparison view, approve-with-modification, per-worker schedule shapes.
