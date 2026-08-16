"""The claim_estimate_line param on the job-nested task-creation endpoints
(mint-by-modal gesture, 2026-08-15 estimating-structure spec §2/§4, Task 3).

v1 mints tasks only — material create takes no claim param (see
docs/plans/... Task 3 brief). Binding goes through MintService
(apps.estimates.mint), which refuses unless the estimate is ACCEPTED (draft
and open both refuse now — see tests.test_mint_service for the service's
own unit coverage of every refusal path); these tests cover the two
endpoints' presence-gate, atomicity, and error-shape wiring around that
service.

Object graph built by hand, mirroring tests/test_mint_service.py;
client/login idiom mirrors tests/test_api_tasks.py (TaskMoneyPermissionTest).
"""
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, User
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource, ServiceItem
from apps.jobs.models import Job, RateScheme, Task


class ClaimEstimateLineTaskCreateAPITest(TestCase):
    """POST /api/jobs/{id}/tasks/ with an optional claim_estimate_line param."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(code='PWK', name='Plan Work')
        self.scheme = RateScheme.objects.create(
            name='Plan Work Scheme', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('50.00'), unit_label='ea', accounting_category=self.cat,
        )
        contact = Contact.objects.create(
            first_name='Plan', last_name='Work', email='plan-work@test.example')
        self.job = Job.objects.create(
            name='Plan Work Job', contact=contact, job_number='JOB-PLANWORK-001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-PLANWORK-001',
            status=Estimate.STATUS_DRAFT,
        )
        self.line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Hand line',
            qty=Decimal('1'), price=Decimal('0.00'), accounting_category=self.cat,
        )

        # can_manage_jobs atom holder.
        self.manager = User.objects.create_user(
            username='plan_mgr', password='testpass')
        self.manager.user_permissions.add(
            Permission.objects.get(codename='can_manage_jobs'))
        self.manager = User.objects.get(pk=self.manager.pk)
        # Plain worker — no atom, not a PM of the job.
        self.worker = User.objects.create_user(
            username='plan_worker', password='testpass')

    def _tasks_url(self):
        return f'/api/jobs/{self.job.pk}/tasks/'

    def _post_task(self, extra=None):
        data = {'name': 'CNC parts', 'rate_scheme': self.scheme.pk, 'est_qty': '3'}
        if extra:
            data.update(extra)
        return self.client.post(self._tasks_url(), data, format='json')

    def _line_at_status(self, est_status, suffix):
        """A fresh estimate + hand line arranged directly at est_status.
        Mirrors tests/test_mint_service.py's _accept/_open pattern: created
        DRAFT, then QuerySet.update() bypasses save()'s transition guard to
        land on an arbitrary status."""
        est = Estimate.objects.create(
            job=self.job, estimate_number=f'EST-PLANWORK-{suffix}',
            status=Estimate.STATUS_DRAFT,
        )
        Estimate.objects.filter(pk=est.pk).update(status=est_status)
        return EstimateLineItem.objects.create(
            estimate=est, line_number=1, description=f'Line {suffix}',
            qty=Decimal('1'), price=Decimal('0.00'), accounting_category=self.cat,
        )

    def test_create_task_with_claim_on_accepted_estimate_mints_source_row(self):
        self.client.force_login(self.manager)
        line = self._line_at_status(Estimate.STATUS_ACCEPTED, 'accepted')
        resp = self._post_task({'claim_estimate_line': line.pk})
        self.assertEqual(resp.status_code, 201, resp.data)
        task_id = resp.data['task_id']
        self.assertTrue(Task.objects.filter(pk=task_id).exists())
        self.assertTrue(EstimateLineItemSource.objects.filter(
            estimate_line_item=line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=task_id).exists())

    def test_claim_refused_on_draft_and_open(self):
        """MintService only accepts ACCEPTED (Task 2) — draft and open both
        refuse now, via the service's uncaught ValidationError rendering a
        400. Atomicity: the task row must NOT survive the rollback."""
        self.client.force_login(self.manager)
        for est_status in (Estimate.STATUS_DRAFT, Estimate.STATUS_OPEN):
            with self.subTest(status=est_status):
                line = self._line_at_status(est_status, est_status)
                task_count_before = Task.objects.filter(job=self.job).count()
                resp = self._post_task({'claim_estimate_line': line.pk})
                self.assertEqual(resp.status_code, 400)
                self.assertIn('detail', resp.data)
                self.assertEqual(
                    Task.objects.filter(job=self.job).count(), task_count_before)
                self.assertFalse(EstimateLineItemSource.objects.filter(
                    estimate_line_item=line).exists())

    def test_claim_param_refused_on_dead_estimate(self):
        self.client.force_login(self.manager)
        Estimate.objects.filter(pk=self.estimate.pk).update(status='rejected')
        task_count_before = Task.objects.filter(job=self.job).count()
        resp = self._post_task({'claim_estimate_line': self.line.pk})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Task.objects.filter(job=self.job).count(), task_count_before)
        self.assertFalse(EstimateLineItemSource.objects.filter(
            estimate_line_item=self.line).exists())

    def test_claim_param_presence_requires_manage(self):
        self.client.force_login(self.worker)
        task_count_before = Task.objects.filter(job=self.job).count()
        resp = self._post_task({'claim_estimate_line': self.line.pk})
        self.assertEqual(resp.status_code, 403)
        self.assertIn('detail', resp.data)
        self.assertEqual(Task.objects.filter(job=self.job).count(), task_count_before)
        self.assertFalse(EstimateLineItemSource.objects.filter(
            estimate_line_item=self.line).exists())

    def test_claim_param_presence_gate_wins_over_field_validation(self):
        """Gate-first contract (unified across both plan-work-gesture
        endpoints): claim_estimate_line's presence-gate runs BEFORE
        serializer validation, so a non-manager sending both an invalid
        payload (a nonexistent rate_scheme, which would otherwise 400
        serializer-side) and the claim param gets 403, not 400 — same
        precedence as apps.api.jobs.views._resolve_claim_line on
        add_from_template."""
        self.client.force_login(self.worker)
        task_count_before = Task.objects.filter(job=self.job).count()
        resp = self.client.post(self._tasks_url(), {
            'rate_scheme': 999999,  # nonexistent -> would 400 serializer-side
            'claim_estimate_line': self.line.pk,
        }, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('detail', resp.data)
        self.assertEqual(Task.objects.filter(job=self.job).count(), task_count_before)

    def test_worker_create_without_param_still_works(self):
        self.client.force_login(self.worker)
        task_count_before = Task.objects.filter(job=self.job).count()
        resp = self._post_task()
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(
            Task.objects.filter(job=self.job).count(), task_count_before + 1)

    def test_unknown_line_is_400_and_creates_nothing(self):
        self.client.force_login(self.manager)
        task_count_before = Task.objects.filter(job=self.job).count()
        resp = self._post_task({'claim_estimate_line': 999999})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.data)
        self.assertEqual(Task.objects.filter(job=self.job).count(), task_count_before)

    def test_non_numeric_claim_line_is_400_and_creates_nothing(self):
        """Mixins copy of the gate (JobTaskMixin.tasks) guards non-numeric
        input the same way the shared _resolve_claim_line helper does for
        add_from_template."""
        self.client.force_login(self.manager)
        task_count_before = Task.objects.filter(job=self.job).count()
        resp = self._post_task({'claim_estimate_line': 'not-a-number'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.data)
        self.assertEqual(Task.objects.filter(job=self.job).count(), task_count_before)


class ClaimEstimateLineAddFromTemplateAPITest(TestCase):
    """POST /api/jobs/{id}/add-from-template/ with an optional
    claim_estimate_line param (claims SOURCE_TASK)."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(code='PWT', name='Plan Work Tmpl')
        self.scheme = RateScheme.objects.create(
            name='Plan Work Tmpl Scheme', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('25.00'), unit_label='ea', accounting_category=self.cat,
        )
        self.template = ServiceItem.objects.create(
            template_name='Plan Work Template',
            description='Template for plan-work claim tests',
            is_active=True,
            rate_scheme=self.scheme,
        )
        contact = Contact.objects.create(
            first_name='Plan', last_name='Tmpl', email='plan-tmpl@test.example')
        self.job = Job.objects.create(
            name='Plan Work Tmpl Job', contact=contact, job_number='JOB-PLANWORK-T01',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-PLANWORK-T01',
            status=Estimate.STATUS_DRAFT,
        )
        self.line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Hand line',
            qty=Decimal('1'), price=Decimal('0.00'), accounting_category=self.cat,
        )

        self.manager = User.objects.create_user(
            username='plan_tmpl_mgr', password='testpass')
        self.manager.user_permissions.add(
            Permission.objects.get(codename='can_manage_jobs'))
        self.manager = User.objects.get(pk=self.manager.pk)
        self.worker = User.objects.create_user(
            username='plan_tmpl_worker', password='testpass')

    def _url(self):
        return f'/api/jobs/{self.job.pk}/add-from-template/'

    def _post_template(self, extra=None):
        data = {'service_item_id': self.template.pk, 'est_qty': '1'}
        if extra:
            data.update(extra)
        return self.client.post(self._url(), data, format='json')

    def _line_at_status(self, est_status, suffix):
        est = Estimate.objects.create(
            job=self.job, estimate_number=f'EST-PLANWORK-T-{suffix}',
            status=Estimate.STATUS_DRAFT,
        )
        Estimate.objects.filter(pk=est.pk).update(status=est_status)
        return EstimateLineItem.objects.create(
            estimate=est, line_number=1, description=f'Line {suffix}',
            qty=Decimal('1'), price=Decimal('0.00'), accounting_category=self.cat,
        )

    def test_add_from_template_with_claim_on_accepted_estimate_mints_source_row(self):
        self.client.force_login(self.manager)
        line = self._line_at_status(Estimate.STATUS_ACCEPTED, 'accepted')
        resp = self._post_template({'claim_estimate_line': line.pk})
        self.assertEqual(resp.status_code, 201, resp.data)
        task_id = resp.data['task_id']
        self.assertTrue(Task.objects.filter(pk=task_id).exists())
        self.assertTrue(EstimateLineItemSource.objects.filter(
            estimate_line_item=line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=task_id).exists())

    def test_claim_refused_on_draft_and_open(self):
        self.client.force_login(self.manager)
        for est_status in (Estimate.STATUS_DRAFT, Estimate.STATUS_OPEN):
            with self.subTest(status=est_status):
                line = self._line_at_status(est_status, est_status)
                task_count_before = Task.objects.filter(job=self.job).count()
                resp = self._post_template({'claim_estimate_line': line.pk})
                self.assertEqual(resp.status_code, 400)
                self.assertIn('detail', resp.data)
                self.assertEqual(
                    Task.objects.filter(job=self.job).count(), task_count_before)
                self.assertFalse(EstimateLineItemSource.objects.filter(
                    estimate_line_item=line).exists())

    def test_claim_param_refused_on_dead_estimate(self):
        self.client.force_login(self.manager)
        Estimate.objects.filter(pk=self.estimate.pk).update(status='rejected')
        task_count_before = Task.objects.filter(job=self.job).count()
        resp = self._post_template({'claim_estimate_line': self.line.pk})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Task.objects.filter(job=self.job).count(), task_count_before)
        self.assertFalse(EstimateLineItemSource.objects.filter(
            estimate_line_item=self.line).exists())

    def test_claim_param_presence_requires_manage(self):
        self.client.force_login(self.worker)
        task_count_before = Task.objects.filter(job=self.job).count()
        resp = self._post_template({'claim_estimate_line': self.line.pk})
        self.assertEqual(resp.status_code, 403)
        self.assertIn('detail', resp.data)
        self.assertEqual(Task.objects.filter(job=self.job).count(), task_count_before)
        self.assertFalse(EstimateLineItemSource.objects.filter(
            estimate_line_item=self.line).exists())

    def test_claim_param_presence_gate_wins_over_field_validation(self):
        """Same gate-first contract as the tasks endpoint: a worker sending
        both an invalid payload (missing required service_item_id) and the
        claim param gets 403, not 400."""
        self.client.force_login(self.worker)
        task_count_before = Task.objects.filter(job=self.job).count()
        resp = self.client.post(self._url(), {
            'claim_estimate_line': self.line.pk,
            # service_item_id omitted -> would 400 field-validation-side
        }, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('detail', resp.data)
        self.assertEqual(Task.objects.filter(job=self.job).count(), task_count_before)

    def test_worker_add_from_template_without_param_still_works(self):
        self.client.force_login(self.worker)
        task_count_before = Task.objects.filter(job=self.job).count()
        resp = self._post_template()
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(
            Task.objects.filter(job=self.job).count(), task_count_before + 1)

    def test_unknown_line_is_400_and_creates_nothing(self):
        self.client.force_login(self.manager)
        task_count_before = Task.objects.filter(job=self.job).count()
        resp = self._post_template({'claim_estimate_line': 999999})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.data)
        self.assertEqual(Task.objects.filter(job=self.job).count(), task_count_before)

    def test_non_numeric_claim_line_is_400_and_creates_nothing(self):
        self.client.force_login(self.manager)
        task_count_before = Task.objects.filter(job=self.job).count()
        resp = self._post_template({'claim_estimate_line': 'not-a-number'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.data)
        self.assertEqual(Task.objects.filter(job=self.job).count(), task_count_before)
