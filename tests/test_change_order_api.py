"""
Tests for the ChangeOrder REST API.

Covers:
- create: 400 when job not on_hold, 201 when on_hold with CanManageJobs, 403 without permission
- line-item add via line-items endpoint
- mark-open action
- PATCH status to accepted advances the job to approved
- GET /api/jobs/{id}/agreement/ returns composed lines + grand_total
- DELETE a draft CO returns 200 + JSON
"""
from decimal import Decimal

from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from apps.deliverables.models import Deliverable
from apps.estimates.models import ChangeOrder, ChangeOrderLineItem, Estimate
from apps.jobs.models import Job
from tests.base import FixtureTestCase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_can_manage_jobs(user):
    perm = Permission.objects.get(codename='can_manage_jobs', content_type__app_label='core')
    user.user_permissions.add(perm)
    # Reload to clear permission cache.
    from apps.core.models import User
    return User.objects.get(pk=user.pk)


def _advance_job_to_on_hold(job):
    """Draft → submitted → approved, then hold (on_hold flag)."""
    from apps.jobs.services import JobService
    for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
        job.status = s
        job.save()
    JobService.hold_job(job.pk, 'CO editing')
    job.refresh_from_db()


def _make_accepted_estimate(job, number='EST-API-CO-1'):
    return Estimate.objects.create(
        job=job, estimate_number=number, version=1,
        status=Estimate.STATUS_ACCEPTED,
    )


def _make_deliverable(job, description='Unit', sort_order=10):
    return Deliverable.objects.create(
        job=job, description=description,
        qty_ordered=Decimal('1'), units='ea', sort_order=sort_order,
    )


# ---------------------------------------------------------------------------
# Create tests
# ---------------------------------------------------------------------------

class ChangeOrderCreateAPITest(FixtureTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        from apps.core.models import User
        self.manager = User.objects.create_user(username='co_mgr', password='x')
        self.manager = _add_can_manage_jobs(self.manager)
        self.plain = User.objects.create_user(username='co_plain', password='x')

        self.job = Job.objects.first()
        # Clear any existing estimates on the fixture job so we control state.
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job)
        _make_deliverable(self.job)

    def test_create_returns_201_when_on_hold(self):
        _advance_job_to_on_hold(self.job)
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post('/api/change-orders/', {'job': self.job.pk}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['status'], ChangeOrder.STATUS_DRAFT)
        self.assertEqual(resp.data['job'], self.job.pk)

    def test_create_returns_400_when_not_on_hold(self):
        # Job is in approved state (not on_hold).
        # Advance draft → submitted → approved (skip on_hold).
        self.job.status = Job.STATUS_SUBMITTED
        self.job.save()
        self.job.status = Job.STATUS_APPROVED
        self.job.save()
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post('/api/change-orders/', {'job': self.job.pk}, format='json')
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_create_returns_403_without_can_manage_jobs(self):
        _advance_job_to_on_hold(self.job)
        self.client.force_authenticate(user=self.plain)
        resp = self.client.post('/api/change-orders/', {'job': self.job.pk}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_create_returns_403_unauthenticated(self):
        _advance_job_to_on_hold(self.job)
        resp = self.client.post('/api/change-orders/', {'job': self.job.pk}, format='json')
        self.assertIn(resp.status_code, [401, 403])


# ---------------------------------------------------------------------------
# Line-item, mark-open, accept workflow
# ---------------------------------------------------------------------------

class ChangeOrderWorkflowAPITest(FixtureTestCase):
    """Full happy-path: create → add line item → mark-open → accept → job approved."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        from apps.core.models import User
        self.manager = User.objects.create_user(username='co_wf_mgr', password='x')
        self.manager = _add_can_manage_jobs(self.manager)
        self.client.force_authenticate(user=self.manager)

        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job, number='EST-WF-1')
        _make_deliverable(self.job)
        _advance_job_to_on_hold(self.job)

        # Create the CO via the API.
        resp = self.client.post('/api/change-orders/', {'job': self.job.pk}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.co_id = resp.data['change_order_id']

    def test_add_line_item(self):
        resp = self.client.post(
            f'/api/change-orders/{self.co_id}/line-items/',
            {
                'action': ChangeOrderLineItem.ACTION_ADD,
                'description': 'Extra scope',
                'qty': '2.00',
                'price': '150.00',
                'accounting_category': 901,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['description'], 'Extra scope')

    def test_mark_open(self):
        # Add a line item first (required to transition from draft).
        self._add_line_item()
        resp = self.client.post(f'/api/change-orders/{self.co_id}/mark-open/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['status'], ChangeOrder.STATUS_OPEN)

    def test_accept_advances_job_to_approved(self):
        self._add_line_item()
        # mark-open
        r = self.client.post(f'/api/change-orders/{self.co_id}/mark-open/')
        self.assertEqual(r.status_code, 200, r.data)
        # PATCH status to accepted
        resp = self.client.patch(
            f'/api/change-orders/{self.co_id}/',
            {'status': ChangeOrder.STATUS_ACCEPTED},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['status'], ChangeOrder.STATUS_ACCEPTED)

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def _add_line_item(self):
        resp = self.client.post(
            f'/api/change-orders/{self.co_id}/line-items/',
            {
                'action': ChangeOrderLineItem.ACTION_ADD,
                'description': 'Extra scope',
                'qty': '1.00',
                'price': '250.00',
                'accounting_category': 901,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data

    def test_payload_carries_diff_total_as_total(self):
        """The job-overview Scope block reads change_order.total as the net
        delta against the base estimate. The serializer must expose the
        authoritative compose_change_order_diff diff_total (not qty*price of
        the CO's own add/remove/replace lines)."""
        from apps.estimates.models import EstimateLineItem
        # Base estimate line: $200. CO adds a $250 line → delta +250.00.
        EstimateLineItem.objects.create(
            estimate=self.est, description='Base', qty=Decimal('2'),
            units='ea', price=Decimal('100.00'), line_number=1,
        )
        self._add_line_item()  # +1 * 250.00 = +250.00
        resp = self.client.get(f'/api/change-orders/?job={self.job.pk}')
        self.assertEqual(resp.status_code, 200)
        results = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        row = next(r for r in results if r['change_order_id'] == self.co_id)
        self.assertEqual(str(row['total']), '250.00')

    def test_total_present_and_read_only_on_get(self):
        """Sanity check alongside the write-protection regression test below:
        `total` is exposed on GET and is a SerializerMethodField (inherently
        read-only) — attempting to PATCH it must not error and must not
        change the computed value."""
        self._add_line_item()
        resp = self.client.get(f'/api/change-orders/{self.co_id}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn('total', resp.data)
        original_total = resp.data['total']

        resp2 = self.client.patch(
            f'/api/change-orders/{self.co_id}/',
            {'total': '999999.99'},
            format='json',
        )
        self.assertEqual(resp2.status_code, 200, resp2.data)
        self.assertEqual(resp2.data['total'], original_total)

    def test_patch_ignores_writes_to_protected_fields(self):
        """Task-6 regression: get_total() accidentally swallowed
        read_only_fields (the list ended up as dead code after a `return`
        inside get_total instead of living in class Meta), making
        change_order_number, version, estimate, created_date, sent_date and
        closed_date writable via PATCH. ChangeOrderService.update_fields has
        no guards of its own (a plain setattr loop) and DRF read_only_fields
        silently drops unknown-write attempts (200, not 400) — so this must
        assert DB state, not response status code."""
        # A second estimate row to attempt reassigning `estimate` onto —
        # the job already has an accepted estimate (self.est), so this one
        # is just a draft; its status is irrelevant, only its pk matters.
        other_est = Estimate.objects.create(
            job=self.job, estimate_number='EST-WF-OTHER', version=1,
            status=Estimate.STATUS_DRAFT,
        )
        before = ChangeOrder.objects.get(pk=self.co_id)
        original_number = before.change_order_number
        original_version = before.version
        original_estimate_id = before.estimate_id
        original_sent_date = before.sent_date

        resp = self.client.patch(
            f'/api/change-orders/{self.co_id}/',
            {
                'version': 99,
                'sent_date': '2020-01-01T00:00:00Z',
                'estimate': other_est.pk,
                'change_order_number': 'CO-HAX',
                'expiration_date': '2030-06-15T00:00:00Z',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        after = ChangeOrder.objects.get(pk=self.co_id)
        self.assertEqual(after.change_order_number, original_number)
        self.assertEqual(after.version, original_version)
        self.assertEqual(after.estimate_id, original_estimate_id)
        self.assertEqual(after.sent_date, original_sent_date)
        # The legitimately-writable field did change, proving the PATCH
        # itself was processed (not a no-op / rejected request).
        self.assertEqual(
            after.expiration_date.isoformat(), '2030-06-15T00:00:00+00:00',
        )


# ---------------------------------------------------------------------------
# Delete (discard draft)
# ---------------------------------------------------------------------------

class ChangeOrderDeleteAPITest(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        from apps.core.models import User
        self.manager = User.objects.create_user(username='co_del_mgr', password='x')
        self.manager = _add_can_manage_jobs(self.manager)
        self.client.force_authenticate(user=self.manager)

        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        _make_accepted_estimate(self.job, number='EST-DEL-1')
        _make_deliverable(self.job)
        _advance_job_to_on_hold(self.job)

        resp = self.client.post('/api/change-orders/', {'job': self.job.pk}, format='json')
        self.assertEqual(resp.status_code, 201)
        self.co_id = resp.data['change_order_id']

    def test_delete_draft_returns_200_with_json(self):
        resp = self.client.delete(f'/api/change-orders/{self.co_id}/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn('message', resp.data)
        # Verify it's actually gone.
        self.assertFalse(ChangeOrder.objects.filter(pk=self.co_id).exists())

    def test_delete_non_draft_returns_400(self):
        # Add line item and open the CO so it's not draft.
        self.client.post(
            f'/api/change-orders/{self.co_id}/line-items/',
            {'action': ChangeOrderLineItem.ACTION_ADD, 'description': 'Item',
             'qty': '1', 'price': '100', 'accounting_category': 901},
            format='json',
        )
        self.client.post(f'/api/change-orders/{self.co_id}/mark-open/')
        resp = self.client.delete(f'/api/change-orders/{self.co_id}/')
        self.assertEqual(resp.status_code, 400, resp.data)


# ---------------------------------------------------------------------------
# ?job= filter
# ---------------------------------------------------------------------------

class ChangeOrderFilterAPITest(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        from apps.core.models import User
        self.manager = User.objects.create_user(username='co_filter_mgr', password='x')
        self.manager = _add_can_manage_jobs(self.manager)
        self.client.force_authenticate(user=self.manager)

        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job, number='EST-FILTER-1')
        _make_deliverable(self.job)
        _advance_job_to_on_hold(self.job)

        # Create one CO for this job
        resp = self.client.post('/api/change-orders/', {'job': self.job.pk}, format='json')
        self.assertEqual(resp.status_code, 201)
        self.co_id = resp.data['change_order_id']

    def test_filter_by_job(self):
        resp = self.client.get(f'/api/change-orders/?job={self.job.pk}')
        self.assertEqual(resp.status_code, 200)
        ids = [item['change_order_id'] for item in resp.data['results']]
        self.assertIn(self.co_id, ids)

    def test_list_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get('/api/change-orders/')
        self.assertIn(resp.status_code, [401, 403])


# ---------------------------------------------------------------------------
# Seed-new action
# ---------------------------------------------------------------------------

class ChangeOrderSeedNewAPITest(FixtureTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        from apps.core.models import User
        self.manager = User.objects.create_user(username='co_seed_mgr', password='x')
        self.manager = _add_can_manage_jobs(self.manager)
        self.client.force_authenticate(user=self.manager)

        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        _make_accepted_estimate(self.job, number='EST-SEED-1')
        _make_deliverable(self.job)
        _advance_job_to_on_hold(self.job)

        # Create, add line, open, reject — so we have a terminal CO to seed from.
        resp = self.client.post('/api/change-orders/', {'job': self.job.pk}, format='json')
        self.assertEqual(resp.status_code, 201)
        self.co_id = resp.data['change_order_id']

        self.client.post(
            f'/api/change-orders/{self.co_id}/line-items/',
            {'action': ChangeOrderLineItem.ACTION_ADD, 'description': 'Scope',
             'qty': '1', 'price': '100', 'accounting_category': 901},
            format='json',
        )
        self.client.post(f'/api/change-orders/{self.co_id}/mark-open/')
        # Patch to rejected
        self.client.patch(
            f'/api/change-orders/{self.co_id}/',
            {'status': ChangeOrder.STATUS_REJECTED},
            format='json',
        )

    def test_seed_new_creates_draft_co(self):
        resp = self.client.post(f'/api/change-orders/{self.co_id}/seed-new/')
        self.assertEqual(resp.status_code, 201, resp.data)
        new_co_id = resp.data['change_order_id']
        self.assertNotEqual(new_co_id, self.co_id)
        self.assertEqual(resp.data['status'], ChangeOrder.STATUS_DRAFT)
        self.assertEqual(resp.data['parent'], self.co_id)


# ---------------------------------------------------------------------------
# Agreement endpoint
# ---------------------------------------------------------------------------

class AgreementAPITest(FixtureTestCase):
    """GET /api/jobs/{id}/agreement/ returns the composed agreement."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        from apps.core.models import User
        self.user = User.objects.create_user(username='co_agree', password='x')
        self.client.force_authenticate(user=self.user)

        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()

    def test_agreement_no_accepted_estimate_returns_empty(self):
        resp = self.client.get(f'/api/jobs/{self.job.pk}/agreement/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['lines'], [])
        self.assertEqual(resp.data['grand_total'], '0')

    def test_agreement_with_accepted_estimate_returns_lines(self):
        est = _make_accepted_estimate(self.job, number='EST-AGREE-1')
        # Add a line item directly (service layer would normally do this, but
        # since the estimate is already accepted we insert directly for test isolation).
        from apps.estimates.models import EstimateLineItem
        EstimateLineItem.objects.create(
            estimate=est,
            description='Panel A',
            qty=Decimal('2'),
            price=Decimal('100.00'),
            line_number=1,
        )

        resp = self.client.get(f'/api/jobs/{self.job.pk}/agreement/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(len(resp.data['lines']), 1)
        self.assertEqual(resp.data['lines'][0]['description'], 'Panel A')
        # grand_total should be str '200.00'
        self.assertIn('grand_total', resp.data)
        self.assertEqual(Decimal(resp.data['grand_total']), Decimal('200.00'))

    def test_agreement_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get(f'/api/jobs/{self.job.pk}/agreement/')
        self.assertIn(resp.status_code, [401, 403])


# ---------------------------------------------------------------------------
# deliverables-baseline action
# ---------------------------------------------------------------------------

class DeliverablesBaselineAPITest(FixtureTestCase):
    """GET /api/change-orders/{id}/deliverables-baseline/

    Baseline is the snapshot attached to:
    - the latest accepted CO on the estimate (if one exists, created before this CO), or
    - the accepted estimate itself.
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        from apps.core.models import User
        self.user = User.objects.create_user(username='co_baseline', password='x')
        self.manager = User.objects.create_user(username='co_bl_mgr', password='x')
        self.manager = _add_can_manage_jobs(self.manager)

        self.job = Job.objects.first()
        Estimate.objects.filter(job=self.job).delete()
        self.est = _make_accepted_estimate(self.job, number='EST-BL-1')

        # Two deliverables on the job.
        self.d1 = _make_deliverable(self.job, description='Widget A', sort_order=10)
        self.d2 = _make_deliverable(self.job, description='Widget B', sort_order=20)

        # Advance job to on_hold and create a CO (Trigger 1 snapshots the estimate).
        _advance_job_to_on_hold(self.job)
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post('/api/change-orders/', {'job': self.job.pk}, format='json')
        self.assertEqual(resp.status_code, 201, resp.data)
        self.co_id = resp.data['change_order_id']

    def test_baseline_returns_estimate_snapshots_when_no_prior_accepted_co(self):
        """First CO on an estimate: baseline is the estimate's snapshot rows."""
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(f'/api/change-orders/{self.co_id}/deliverables-baseline/')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn('baseline', resp.data)
        rows = resp.data['baseline']
        self.assertEqual(len(rows), 2)
        descriptions = {r['description'] for r in rows}
        self.assertIn('Widget A', descriptions)
        self.assertIn('Widget B', descriptions)

    def test_baseline_row_fields(self):
        """Each baseline row has the expected fields with Decimal-as-string qty."""
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(f'/api/change-orders/{self.co_id}/deliverables-baseline/')
        self.assertEqual(resp.status_code, 200, resp.data)
        row = resp.data['baseline'][0]
        for field in ('id', 'description', 'qty_ordered', 'units', 'sort_order', 'source_deliverable'):
            self.assertIn(field, row, f'Missing field: {field}')
        # qty_ordered must be a string (Decimal-as-string convention).
        self.assertIsInstance(row['qty_ordered'], str)

    def test_baseline_ordered_by_sort_order(self):
        """Rows are returned in sort_order ascending."""
        self.client.force_authenticate(user=self.user)
        resp = self.client.get(f'/api/change-orders/{self.co_id}/deliverables-baseline/')
        self.assertEqual(resp.status_code, 200, resp.data)
        sort_orders = [r['sort_order'] for r in resp.data['baseline']]
        self.assertEqual(sort_orders, sorted(sort_orders))

    def test_baseline_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get(f'/api/change-orders/{self.co_id}/deliverables-baseline/')
        self.assertIn(resp.status_code, [401, 403])

    def test_baseline_uses_latest_accepted_co_when_prior_co_exists(self):
        """When a prior accepted CO exists on the estimate, the baseline is its snapshot."""
        from apps.deliverables.models import DeliverableSnapshot
        from apps.estimates.models import ChangeOrder

        # Accept the first CO (creates snapshot on it via Trigger 2 path - but
        # here we test Trigger 1 on the NEXT CO).
        # We manually create an accepted CO and snapshot it to represent a prior agreement.
        prior_co = ChangeOrder.objects.create(
            job=self.job,
            estimate=self.est,
            status=ChangeOrder.STATUS_ACCEPTED,
        )
        # Manually snapshot the prior CO (as Trigger 2 would have).
        from apps.deliverables.services import DeliverableService
        DeliverableService.snapshot_document(change_order=prior_co)

        # Now create a new CO — Trigger 1 should snapshot the prior_co (not the estimate).
        # First put the job back on hold for the service guard.
        self.job.refresh_from_db()
        self.job.on_hold = True
        self.job.hold_reason = 'CO editing'
        self.job.save()

        self.client.force_authenticate(user=self.manager)
        resp2 = self.client.post('/api/change-orders/', {'job': self.job.pk}, format='json')
        self.assertEqual(resp2.status_code, 201, resp2.data)
        new_co_id = resp2.data['change_order_id']

        self.client.force_authenticate(user=self.user)
        resp = self.client.get(f'/api/change-orders/{new_co_id}/deliverables-baseline/')
        self.assertEqual(resp.status_code, 200, resp.data)
        rows = resp.data['baseline']
        # The baseline should be the snapshots attached to prior_co (not the estimate).
        baseline_ids = {r['id'] for r in rows}
        prior_co_snap_ids = set(
            DeliverableSnapshot.objects.filter(change_order=prior_co).values_list('pk', flat=True)
        )
        self.assertEqual(baseline_ids, prior_co_snap_ids)
