"""Tests for /api/tasks/ endpoints — permissions and worker-accessible actions."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase

from apps.contacts.models import Contact
from apps.jobs.models import Job, RateScheme, Task

User = get_user_model()


def _stamp_task(job, scheme, name, **extra):
    """Create+stamp a Task from a RateScheme preset (task-owned-money
    Phase 1) — Task.objects.create(rate_scheme=...) no longer works since
    Task has no such field; stamp_from_scheme copies the preset's money
    fields on before first save."""
    task = Task(job=job, name=name, **extra)
    task.stamp_from_scheme(scheme)
    task.save()
    return task


class ActualQtyAddActionTest(TestCase):
    """POST /api/tasks/{id}/actual-qty/add/ applies a signed increment to
    the running total. IsAuthenticated only — any worker on the task can
    contribute. The old replace-style PATCH endpoint is gone."""

    def setUp(self):
        from apps.core.models import AccountingCategory

        ac = AccountingCategory.objects.create(code='LAB2', name='Labor2')
        self.scheme = RateScheme.objects.create(
            name='Press',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'),
            unit_label='piece',
            accounting_category=ac,
        )

        contact = Contact.objects.create(first_name='Acme', last_name='Corp')
        self.job = Job.objects.create(
            name='Widget Run', contact=contact, job_number='JOB-TEST-002'
        )
        self.task = _stamp_task(self.job, self.scheme, 'Press parts')

        # A plain worker — no can_manage_jobs permission.
        self.worker = User.objects.create_user(
            username='plain_worker', password='testpass'
        )

    def _url(self):
        return f'/api/tasks/{self.task.pk}/actual-qty/add/'

    def _post(self, payload):
        return self.client.post(
            self._url(), data=payload, content_type='application/json'
        )

    def test_worker_without_manage_jobs_can_add(self):
        self.client.login(username='plain_worker', password='testpass')
        resp = self._post({'actual_qty': '7.50'})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.actual_qty, Decimal('7.50'))

    def test_adds_accumulate(self):
        self.client.login(username='plain_worker', password='testpass')
        self._post({'actual_qty': '9'})
        resp = self._post({'actual_qty': '5'})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.actual_qty, Decimal('14'))

    def test_negative_add_subtracts(self):
        self.client.login(username='plain_worker', password='testpass')
        self._post({'actual_qty': '50'})
        resp = self._post({'actual_qty': '-45'})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.actual_qty, Decimal('5'))

    def test_add_below_zero_total_rejected(self):
        self.client.login(username='plain_worker', password='testpass')
        self._post({'actual_qty': '3'})
        resp = self._post({'actual_qty': '-4'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('actual_qty', resp.json())

    def test_zero_add_rejected(self):
        self.client.login(username='plain_worker', password='testpass')
        resp = self._post({'actual_qty': '0'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('actual_qty', resp.json())

    def test_missing_actual_qty_returns_400(self):
        self.client.login(username='plain_worker', password='testpass')
        resp = self._post({})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('actual_qty', resp.json())

    def test_invalid_decimal_returns_400(self):
        self.client.login(username='plain_worker', password='testpass')
        resp = self._post({'actual_qty': 'not-a-number'})
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('actual_qty', resp.json())

    def test_unauthenticated_request_is_rejected(self):
        resp = self._post({'actual_qty': '5'})
        self.assertIn(resp.status_code, (401, 403))

    def test_response_returns_new_total(self):
        self.client.login(username='plain_worker', password='testpass')
        self._post({'actual_qty': '9'})
        resp = self._post({'actual_qty': '3.5'})
        body = resp.json()
        self.assertIn('actual_qty', body)
        self.assertEqual(Decimal(body['actual_qty']), Decimal('12.5'))

    def test_add_on_complete_task_rejected(self):
        self.client.login(username='plain_worker', password='testpass')
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.STATUS_COMPLETE, actual_qty=Decimal('5'))
        resp = self._post({'actual_qty': '1'})
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_replace_patch_endpoint_is_gone(self):
        """The old PATCH /actual-qty/ replace endpoint must no longer route."""
        self.client.login(username='plain_worker', password='testpass')
        resp = self.client.patch(
            f'/api/tasks/{self.task.pk}/actual-qty/',
            data={'actual_qty': '5'}, content_type='application/json',
        )
        self.assertIn(resp.status_code, (404, 405), resp.content)


class CancelTaskPermissionTest(TestCase):
    """POST /api/tasks/{id}/cancel/ is open to any authenticated user
    (plan C2, 2026-07-12: cancel shares delete's principal set — it is the
    worker's exit from a task that can no longer be deleted)."""

    def setUp(self):
        from apps.core.models import AccountingCategory

        ac = AccountingCategory.objects.create(code='LABC', name='LaborC')
        self.scheme = RateScheme.objects.create(
            name='CancelScheme',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'),
            unit_label='piece',
            accounting_category=ac,
        )
        contact = Contact.objects.create(first_name='Cancel', last_name='Co')
        self.job = Job.objects.create(
            name='Cancel Job', contact=contact, job_number='JOB-CANCEL-001'
        )
        self.task = _stamp_task(self.job, self.scheme, 'Cancellable')

        # A plain worker — no atom, not the job's PM.
        self.worker = User.objects.create_user(
            username='cancel_worker', password='testpass'
        )
        # An atom-holder.
        self.manager = User.objects.create_user(
            username='cancel_mgr', password='testpass'
        )
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)
        # The job's project manager (no atom, but is PM).
        self.pm = User.objects.create_user(
            username='cancel_pm', password='testpass'
        )
        self.job.project_manager = self.pm
        self.job.save(update_fields=['project_manager'])

    def _url(self):
        return f'/api/tasks/{self.task.pk}/cancel/'

    def test_cancel_allowed_for_worker(self):
        self.client.force_login(self.worker)
        resp = self.client.post(self._url(), data={}, content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.STATUS_CANCELLED)

    def test_cancel_allowed_for_atom_holder(self):
        # Resolves the target job via JobScopedPermissionMixin — must not 403.
        self.client.force_login(self.manager)
        resp = self.client.post(self._url(), data={}, content_type='application/json')
        self.assertNotEqual(resp.status_code, 403, resp.content)

    def test_cancel_allowed_for_project_manager(self):
        self.client.force_login(self.pm)
        resp = self.client.post(self._url(), data={}, content_type='application/json')
        self.assertNotEqual(resp.status_code, 403, resp.content)


class PercentageServiceTaskRejectionTest(TestCase):
    """A RateScheme with algorithm=PERCENTAGE must be rejected when assigning
    to a Task — percentage services are document-level adjustments only."""

    def setUp(self):
        from apps.core.models import AccountingCategory
        from django.contrib.auth.models import Permission

        ac = AccountingCategory.objects.create(code='LABD', name='LaborD')
        self.contact = Contact.objects.create(first_name='Pct', last_name='Co')
        self.job = Job.objects.create(
            name='Pct Job', contact=self.contact, job_number='JOB-PCT-001'
        )
        self.rush = RateScheme.objects.create(
            name='Rush', algorithm=RateScheme.PERCENTAGE, rate=Decimal('15'),
            unit_label='%', accounting_category=ac,
        )
        self.manager = User.objects.create_user(
            username='pct_mgr', password='testpass'
        )
        perm = Permission.objects.get(codename='can_manage_jobs')
        self.manager.user_permissions.add(perm)

    def test_cannot_assign_percentage_service_to_task(self):
        self.client.force_login(self.manager)
        resp = self.client.post(f'/api/jobs/{self.job.pk}/tasks/', {
            'name': 'x', 'rate_scheme': self.rush.pk, 'est_qty': '1',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)


class TaskMoneyPermissionTest(TestCase):
    """Task-owned money (Phase 1), Task 8: a Task's money block (qty_source,
    rate, unit_label, accounting_category, active_modifiers) may only be
    WRITTEN by CanManageJobOrPM (the can_manage_jobs atom or the task's
    job's project_manager) or the can_manage_financials atom. Everyone else
    (any authenticated user) gets stamp-only creation via `rate_scheme` and
    non-money edits — see TaskSerializer.validate()/MONEY_FIELDS."""

    def setUp(self):
        from apps.core.models import AccountingCategory

        self.ac = AccountingCategory.objects.create(code='MNY1', name='Money1')
        self.ac2 = AccountingCategory.objects.create(code='MNY2', name='Money2')
        self.scheme = RateScheme.objects.create(
            name='Money Scheme',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('42.00'),
            unit_label='piece',
            accounting_category=self.ac,
            modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 10}],
        )

        contact = Contact.objects.create(
            first_name='Money', last_name='Job', email='money-job@test.example')
        self.job = Job.objects.create(
            name='Money Job', contact=contact, job_number='JOB-MONEY-001',
        )
        other_contact = Contact.objects.create(
            first_name='Other', last_name='Job', email='other-job@test.example')
        self.other_job = Job.objects.create(
            name='Other Job', contact=other_contact, job_number='JOB-MONEY-002',
        )

        # Plain worker — no atom, not a PM of either job.
        self.worker = User.objects.create_user(
            username='money_worker', password='testpass')
        # can_manage_jobs atom holder.
        self.manager = User.objects.create_user(
            username='money_mgr', password='testpass')
        self.manager.user_permissions.add(
            Permission.objects.get(codename='can_manage_jobs'))
        self.manager = User.objects.get(pk=self.manager.pk)
        # can_manage_financials atom holder — not can_manage_jobs, not a PM.
        self.financials = User.objects.create_user(
            username='money_fin', password='testpass')
        self.financials.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials'))
        self.financials = User.objects.get(pk=self.financials.pk)
        # This job's PM — no atom.
        self.pm = User.objects.create_user(username='money_pm', password='testpass')
        self.job.project_manager = self.pm
        self.job.save(update_fields=['project_manager'])
        # The OTHER job's PM — no atom, and not PM of self.job.
        self.other_pm = User.objects.create_user(
            username='money_other_pm', password='testpass')
        self.other_job.project_manager = self.other_pm
        self.other_job.save(update_fields=['project_manager'])

        self.task = _stamp_task(self.job, self.scheme, 'Billable work')

    def _tasks_url(self, job=None):
        return f'/api/jobs/{(job or self.job).pk}/tasks/'

    def _task_detail_url(self, task=None, job=None):
        t = task or self.task
        return f'/api/jobs/{(job or self.job).pk}/tasks/{t.pk}/'

    # --- Stamp-only creation (any authenticated user) ---

    def test_worker_stamp_create_returns_201_with_stamped_values(self):
        self.client.force_login(self.worker)
        resp = self.client.post(self._tasks_url(), {
            'name': 'Worker Task', 'rate_scheme': self.scheme.pk,
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['qty_source'], self.scheme.algorithm)
        self.assertEqual(Decimal(body['rate']), self.scheme.rate)
        self.assertEqual(body['unit_label'], self.scheme.unit_label)
        self.assertEqual(body['accounting_category'], self.ac.pk)
        self.assertEqual(body['active_modifiers'], [])
        self.assertEqual(body['source_scheme'], self.scheme.pk)
        self.assertEqual(body['source_scheme_name'], self.scheme.name)

    def test_stamp_on_create_copies_all_five_aspects_plus_source_scheme(self):
        """Mirrors the model-level assertion in test_task_stamping.py at
        the API boundary: qty_source, rate, unit_label, accounting_category,
        active_modifiers, and source_scheme all land on the created task."""
        self.client.force_login(self.pm)
        resp = self.client.post(self._tasks_url(), {
            'name': 'Stamped', 'rate_scheme': self.scheme.pk,
            'active_modifiers': ['rush'],
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201, resp.content)
        task = Task.objects.get(pk=resp.json()['task_id'])
        self.assertEqual(task.qty_source, self.scheme.algorithm)
        self.assertEqual(task.rate, self.scheme.rate)
        self.assertEqual(task.unit_label, self.scheme.unit_label)
        self.assertEqual(task.accounting_category_id, self.ac.pk)
        self.assertEqual(len(task.active_modifiers), 1)
        self.assertEqual(task.active_modifiers[0]['key'], 'rush')
        self.assertEqual(task.source_scheme_id, self.scheme.pk)

    # --- Worker: money fields are 403 on both create and edit ---

    def test_worker_post_with_money_field_returns_403(self):
        money_payloads = {
            'rate': '999.00',
            'unit_label': 'hour',
            'qty_source': Task.QTY_ELAPSED,
            'accounting_category': self.ac2.pk,
            # CREATE shape is a list of modifier key strings (resolved by
            # stamp_from_scheme) — the dict/snapshot shape is UPDATE-only.
            'active_modifiers': ['rush'],
        }
        self.client.force_login(self.worker)
        for field, value in money_payloads.items():
            with self.subTest(field=field):
                resp = self.client.post(self._tasks_url(), {
                    'name': f'Worker {field}', 'rate_scheme': self.scheme.pk,
                    field: value,
                }, content_type='application/json')
                self.assertEqual(resp.status_code, 403, resp.content)

    def test_worker_patch_with_money_field_returns_403(self):
        money_payloads = {
            'rate': '999.00',
            'unit_label': 'hour',
            'qty_source': Task.QTY_ELAPSED,
            'accounting_category': self.ac2.pk,
            'active_modifiers': [{'key': 'rush', 'label': 'Rush', 'percent': 10}],
        }
        self.client.force_login(self.worker)
        for field, value in money_payloads.items():
            with self.subTest(field=field):
                resp = self.client.patch(
                    self._task_detail_url(), data={field: value},
                    content_type='application/json',
                )
                self.assertEqual(resp.status_code, 403, resp.content)

    def test_worker_patch_non_money_field_still_allowed(self):
        """The gate is field-specific — a worker may still edit ordinary
        fields (e.g. name) on a pending task."""
        self.client.force_login(self.worker)
        resp = self.client.patch(
            self._task_detail_url(), data={'name': 'Renamed by worker'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.name, 'Renamed by worker')

    # --- Elevated principals: PM-of-this-job, can_manage_jobs atom,
    # can_manage_financials atom may PATCH money fields ---

    def test_pm_of_this_job_can_patch_money_fields(self):
        self.client.force_login(self.pm)
        resp = self.client.patch(
            self._task_detail_url(),
            data={'rate': '77.50', 'accounting_category': self.ac2.pk},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.rate, Decimal('77.50'))
        self.assertEqual(self.task.accounting_category_id, self.ac2.pk)

    def test_manager_atom_can_patch_money_fields(self):
        self.client.force_login(self.manager)
        resp = self.client.patch(
            self._task_detail_url(), data={'unit_label': 'hour'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.unit_label, 'hour')

    def test_financials_atom_can_patch_money_fields(self):
        self.client.force_login(self.financials)
        resp = self.client.patch(
            self._task_detail_url(), data={'qty_source': Task.QTY_ELAPSED},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.qty_source, Task.QTY_ELAPSED)

    # --- PM-of-this-job vs PM-of-a-different-job ---

    def test_pm_of_a_different_job_cannot_patch_money_fields(self):
        """Being *a* job's PM doesn't grant money-write on every job's
        tasks — only CanManageJobOrPM's own-job scoping."""
        self.client.force_login(self.other_pm)
        resp = self.client.patch(
            self._task_detail_url(), data={'rate': '5.00'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.rate, self.scheme.rate)

    # --- Unauthenticated ---
    #
    # DRF coerces NotAuthenticated (401) to 403 whenever no configured
    # authenticator implements `authenticate_header` (rest_framework.views.
    # APIView.handle_exception) — this project's only authenticator is
    # SessionAuthentication, which doesn't, so anonymous requests render as
    # 403 everywhere in this codebase (see ActualQtyAddActionTest above,
    # which accepts either defensively). 403 is the real, verified status.

    def test_unauthenticated_post_returns_403(self):
        resp = self.client.post(self._tasks_url(), {
            'name': 'x', 'rate_scheme': self.scheme.pk,
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 403, resp.content)

    def test_unauthenticated_patch_returns_403(self):
        resp = self.client.patch(
            self._task_detail_url(), data={'rate': '1.00'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403, resp.content)


class TaskMoneyFieldShapeValidationTest(TestCase):
    """Review finding (code review, task-owned-money Phase 1 final wave):
    the active_modifiers contract is asymmetric by design — CREATE takes a
    list of modifier KEY STRINGS (resolved server-side by
    stamp_from_scheme); UPDATE takes the full [{key, label, percent}]
    snapshot list, applied by setattr in TaskService.update_task. Without
    TaskSerializer.validate_active_modifiers, a manager PATCHing the
    create-shape (key strings) onto an existing task would persist a
    malformed row that later crashes Task.effective_rate() on every
    list/detail GET. Also covers the rate >= 0 guard (same finding)."""

    def setUp(self):
        from apps.core.models import AccountingCategory

        self.ac = AccountingCategory.objects.create(code='SHP1', name='Shape1')
        self.scheme = RateScheme.objects.create(
            name='Shape Scheme',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('20.00'),
            unit_label='piece',
            accounting_category=self.ac,
            modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 10}],
        )
        contact = Contact.objects.create(
            first_name='Shape', last_name='Job', email='shape-job@test.example')
        self.job = Job.objects.create(
            name='Shape Job', contact=contact, job_number='JOB-SHAPE-001',
        )
        # can_manage_jobs atom holder — money-write gate is not what's under
        # test here, shape validation is, so use a principal that always
        # clears the permission gate.
        self.manager = User.objects.create_user(
            username='shape_mgr', password='testpass')
        self.manager.user_permissions.add(
            Permission.objects.get(codename='can_manage_jobs'))
        self.manager = User.objects.get(pk=self.manager.pk)
        self.task = _stamp_task(self.job, self.scheme, 'Shape task')

    def _tasks_url(self):
        return f'/api/jobs/{self.job.pk}/tasks/'

    def _task_detail_url(self, task=None):
        t = task or self.task
        return f'/api/jobs/{self.job.pk}/tasks/{t.pk}/'

    # --- active_modifiers shape: CREATE wants key strings ---

    def test_create_with_dict_shape_active_modifiers_returns_400(self):
        """The UPDATE shape (snapshot dicts) sent on CREATE must 400, not
        persist a malformed row."""
        self.client.force_login(self.manager)
        resp = self.client.post(self._tasks_url(), {
            'name': 'Bad Create', 'rate_scheme': self.scheme.pk,
            'active_modifiers': [{'key': 'rush', 'label': 'Rush', 'percent': 10}],
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('active_modifiers', resp.json())

    def test_create_with_key_string_shape_active_modifiers_returns_201(self):
        self.client.force_login(self.manager)
        resp = self.client.post(self._tasks_url(), {
            'name': 'Good Create', 'rate_scheme': self.scheme.pk,
            'active_modifiers': ['rush'],
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(len(body['active_modifiers']), 1)
        self.assertEqual(body['active_modifiers'][0]['key'], 'rush')

    # --- active_modifiers shape: UPDATE wants {key, label, percent} dicts ---

    def test_patch_with_key_string_shape_active_modifiers_returns_400(self):
        """This is the exact bug the finding describes: the CREATE shape
        (bare key strings) sent on PATCH must 400 instead of being setattr'd
        straight onto the model, which would later blow up
        Task.effective_rate() on read."""
        self.client.force_login(self.manager)
        resp = self.client.patch(
            self._task_detail_url(), data={'active_modifiers': ['rush']},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('active_modifiers', resp.json())
        self.task.refresh_from_db()
        self.assertEqual(self.task.active_modifiers, [])

    def test_patch_with_snapshot_dict_shape_active_modifiers_returns_200(self):
        self.client.force_login(self.manager)
        resp = self.client.patch(
            self._task_detail_url(),
            data={'active_modifiers': [
                {'key': 'rush', 'label': 'Rush', 'percent': 10},
            ]},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.task.refresh_from_db()
        self.assertEqual(self.task.active_modifiers,
                         [{'key': 'rush', 'label': 'Rush', 'percent': 10}])

    def test_patch_with_non_dict_entry_returns_400(self):
        self.client.force_login(self.manager)
        resp = self.client.patch(
            self._task_detail_url(), data={'active_modifiers': [None]},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_patch_with_bool_percent_returns_400(self):
        """bool is a subclass of int — a naive isinstance(x, (int, float))
        check would wrongly accept it. Mirrors validate_data's
        Decimal(str(...)) idiom, which correctly rejects it."""
        self.client.force_login(self.manager)
        resp = self.client.patch(
            self._task_detail_url(),
            data={'active_modifiers': [
                {'key': 'rush', 'label': 'Rush', 'percent': True},
            ]},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    def test_patch_with_missing_key_returns_400(self):
        self.client.force_login(self.manager)
        resp = self.client.patch(
            self._task_detail_url(),
            data={'active_modifiers': [{'label': 'Rush', 'percent': 10}]},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)

    # --- rate: min 0 ---

    def test_patch_negative_rate_returns_400(self):
        self.client.force_login(self.manager)
        resp = self.client.patch(
            self._task_detail_url(), data={'rate': '-5.00'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertIn('rate', resp.json())
        self.task.refresh_from_db()
        self.assertEqual(self.task.rate, Decimal('20.00'))

    def test_patch_zero_rate_returns_200(self):
        self.client.force_login(self.manager)
        resp = self.client.patch(
            self._task_detail_url(), data={'rate': '0.00'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)


class InactiveSchemeTaskCreateTest(TestCase):
    """POSTing a `rate_scheme` whose preset has been retired (is_active=
    False) must render a clean 409 (SchemeInactiveError), not an uncaught
    500. TaskService.create_direct raises SchemeInactiveError for an
    inactive preset; JobTaskMixin.tasks() (apps/api/mixins.py) and
    TaskViewSet.subtasks() (apps/api/tasks/views.py) both call it directly
    and must catch it exactly like the sibling endpoints
    (JobViewSet.populate_from_template / add_from_template) already do."""

    def setUp(self):
        from apps.core.models import AccountingCategory

        ac = AccountingCategory.objects.create(code='INACT', name='Inactive AC')
        self.inactive_scheme = RateScheme.objects.create(
            name='Retired Scheme', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='ea', accounting_category=ac,
            is_active=False,
        )
        active_scheme = RateScheme.objects.create(
            name='Active Parent Scheme', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='ea', accounting_category=ac,
        )
        contact = Contact.objects.create(
            first_name='Inact', last_name='Job', email='inact-job@test.example')
        self.job = Job.objects.create(
            name='Inactive Scheme Job', contact=contact, job_number='JOB-INACT-001')
        self.parent_task = _stamp_task(self.job, active_scheme, 'Parent')
        # Any authenticated user (stamp-only creation is worker-accessible).
        self.worker = User.objects.create_user(username='inact_worker', password='testpass')

    def test_job_task_post_with_inactive_scheme_returns_409(self):
        self.client.force_login(self.worker)
        resp = self.client.post(f'/api/jobs/{self.job.pk}/tasks/', {
            'name': 'x', 'rate_scheme': self.inactive_scheme.pk,
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertIn('detail', resp.json())

    def test_subtask_post_with_inactive_scheme_returns_409(self):
        self.client.force_login(self.worker)
        resp = self.client.post(f'/api/tasks/{self.parent_task.pk}/subtasks/', {
            'name': 'x', 'rate_scheme': self.inactive_scheme.pk,
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertIn('detail', resp.json())
