"""Per-unit-lines spec Task 6: drift detection + the Revert (restamp)
endpoint.

After `_stamp_atom_per_unit` (Task 3) snapshots a claim's per-unit
agreement and stamps the atom to the whole-job total, the atom and the
agreement can diverge — a CO qty change moves the claim onto a
differently-qty'd line, or someone hand-edits the atom directly. This
module covers:

  1. Source-pool atom dicts and line-item serializer source entries gain
     `per_unit_qty` / `expected_total` / (task, when snapshotted)
     `expected_worker_time` / `drift` for a per-unit claim — ABSENT
     (never False) on a non-per-unit claim or an unclaimed pool atom.
  2. A CO replace line accepted with a NEW qty produces drift on the
     moved claim (the atom itself is untouched by acceptance — see
     tests/test_change_order_acceptance.py's
     test_replace_task_line_moves_claim_not_crystallize).
  3. `POST /api/estimates/{id}/restamp-atom/` and the CO analog reset the
     atom to the (possibly new) agreement and clear drift.
  4. Permission parity with every other per-unit authoring endpoint
     (CanManageJobOrPM via the viewsets' default get_permissions).
  5. Restamping a whole-line (non-per-unit) claim is a 400.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.api.estimates.serializers import EstimateLineItemSerializer
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.deliverables.models import Deliverable
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, ChangeOrderLineItemSource,
    Estimate, EstimateLineItem, EstimateLineItemSource,
)
from apps.estimates.services import ChangeOrderWizardService, EstimateWizardService
from apps.inventory.models import Material
from apps.jobs.models import Job, RateScheme, Task
from tests.base import grant_atoms


class PerUnitDriftTestBase(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(
            name='Labor', is_active=True, code='LAB-PUD')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-9001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-9001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('60'),
            unit_label='hour', accounting_category=self.cat,
        )

    def _task(self, est_qty=None, est_worker_time=None):
        t = Task(job=self.job, name='Cutting')
        t.stamp_from_scheme(self.scheme)
        t.est_qty = est_qty
        t.est_worker_time = est_worker_time
        t.save()
        return t

    def _material(self, quantity):
        return Material.objects.create(
            job=self.job, description='Steel', quantity=quantity,
            sell_price=Decimal('2.50'), accounting_category=self.cat,
        )

    def _bundle(self, atoms, qty=Decimal('10')):
        overrides = {
            'description': 'Bundle', 'qty': qty, 'units': 'each', 'price': Decimal('99.00'),
        }
        return EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, atoms, overrides=overrides, per_unit=True)

    def _sources_data(self, line):
        return EstimateLineItemSerializer(line).data['sources']


# ---------------------------------------------------------------------------
# 1. Drift flags appear only when values diverge; absent on non-per-unit
#    claims and available pool atoms.
# ---------------------------------------------------------------------------

class DriftFlagsAppearOnlyOnDivergenceTest(PerUnitDriftTestBase):
    def test_no_drift_immediately_after_stamping(self):
        task = self._task(Decimal('0.75'), timedelta(minutes=45))
        material = self._material(Decimal('4'))
        li = self._bundle(
            [{'type': 'task', 'id': task.pk}, {'type': 'material', 'id': material.pk}],
            qty=Decimal('10'),
        )
        sources = self._sources_data(li)
        task_src = next(s for s in sources if s['source_type'] == 'task')
        mat_src = next(s for s in sources if s['source_type'] == 'material')

        self.assertEqual(task_src['per_unit_qty'], '0.75')
        self.assertEqual(task_src['expected_total'], '7.50')
        self.assertEqual(task_src['expected_worker_time'], '07:30:00')
        # Task 7 fix: the current-value counterpart to expected_worker_time
        # — right after stamping the two agree exactly.
        self.assertEqual(task_src['worker_time'], '07:30:00')
        self.assertFalse(task_src['drift'])

        self.assertEqual(mat_src['per_unit_qty'], '4.00')
        self.assertEqual(mat_src['expected_total'], '40.00')
        self.assertFalse(mat_src['drift'])
        self.assertNotIn('expected_worker_time', mat_src)
        # A material never gets a worker_time counterpart either — it has
        # no expected_worker_time to pair with.
        self.assertNotIn('worker_time', mat_src)

    def test_task_qty_drift_when_hand_edited(self):
        task = self._task(Decimal('0.75'), None)
        li = self._bundle([{'type': 'task', 'id': task.pk}], qty=Decimal('10'))
        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('7.50'))
        task.est_qty = Decimal('8.00')
        task.save()

        task_src = self._sources_data(li)[0]
        self.assertTrue(task_src['drift'])
        self.assertEqual(task_src['expected_total'], '7.50')  # expectation unchanged

    def test_task_worker_time_drift_when_hand_edited(self):
        task = self._task(Decimal('1'), timedelta(minutes=30))
        li = self._bundle([{'type': 'task', 'id': task.pk}], qty=Decimal('10'))
        task.refresh_from_db()
        self.assertEqual(task.est_worker_time, timedelta(hours=5))
        # est_qty stays in sync (10.00); only worker_time diverges.
        task.est_worker_time = timedelta(hours=6)
        task.save()

        task_src = self._sources_data(li)[0]
        self.assertTrue(task_src['drift'])
        # Task 7 fix: schedule-only drift (qty in sync) must still be
        # spellable — expected stays the stamped agreement, current reflects
        # the hand edit, and they now visibly disagree.
        self.assertEqual(task_src['expected_total'], '10.00')
        self.assertEqual(task_src['qty'], '10.00')
        self.assertEqual(task_src['expected_worker_time'], '05:00:00')
        self.assertEqual(task_src['worker_time'], '06:00:00')

    def test_material_qty_drift_when_hand_edited(self):
        material = self._material(Decimal('4'))
        li = self._bundle([{'type': 'material', 'id': material.pk}], qty=Decimal('10'))
        material.refresh_from_db()
        self.assertEqual(material.quantity, Decimal('40.00'))
        material.quantity = Decimal('39.00')
        material.save()

        mat_src = self._sources_data(li)[0]
        self.assertTrue(mat_src['drift'])

    def test_drift_keys_absent_on_whole_line_claim(self):
        task = self._task(Decimal('2'))
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': task.pk}])
        task_src = self._sources_data(li)[0]
        for key in ('per_unit_qty', 'expected_total', 'expected_worker_time', 'worker_time', 'drift'):
            self.assertNotIn(key, task_src)

    def test_drift_keys_absent_on_available_pool_atom(self):
        task = self._task(Decimal('2'))
        pool = EstimateWizardService.get_source_pool(self.estimate)
        entry = next(a for a in pool['atoms'] if a['type'] == 'task' and a['id'] == task.pk)
        self.assertEqual(entry['state'], 'available')
        for key in ('per_unit_qty', 'expected_total', 'drift'):
            self.assertNotIn(key, entry)

    def test_pool_shows_drift_on_claimed_by_current_entry(self):
        task = self._task(Decimal('0.75'))
        li = self._bundle([{'type': 'task', 'id': task.pk}], qty=Decimal('10'))
        task.refresh_from_db()
        task.est_qty = Decimal('1.00')
        task.save()

        pool = EstimateWizardService.get_source_pool(self.estimate)
        entry = next(a for a in pool['atoms'] if a['type'] == 'task' and a['id'] == task.pk)
        self.assertEqual(entry['state'], 'claimed_by_current')
        self.assertEqual(entry['per_unit_qty'], Decimal('0.75'))
        self.assertEqual(entry['expected_total'], Decimal('7.50'))
        self.assertTrue(entry['drift'])


# ---------------------------------------------------------------------------
# 2. CO qty-change scenario: a replace line accepted with a new qty
#    produces drift on the moved claim.
# ---------------------------------------------------------------------------

class COReplaceQtyChangeBase(PerUnitDriftTestBase):
    """Scaffolding only (no test_ methods — shared by two sibling test
    classes below so neither accidentally re-runs the other's tests via
    inheritance): an accepted per-unit estimate line (task per_unit_qty=10,
    per_unit_worker_time=2h, line qty=1) and a draft CO replacing it with
    qty=15 — not yet accepted; call `self._accept()` when a test needs the
    claim actually moved."""

    def setUp(self):
        super().setUp()
        # A fresh job/estimate created directly in the target states
        # (status transitions are validated on .save(), so — like every
        # other CO-acceptance test in this suite — the approved job and
        # accepted estimate are built via .create(), not by mutating the
        # base class's draft ones).
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-9010',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-9010',
        )
        Deliverable.objects.create(
            job=self.job, description='Widget', qty_ordered=Decimal('1'),
            units='ea', sort_order=10,
        )

        self.task = self._task(Decimal('10'), timedelta(hours=2))
        self.line = self._bundle(
            [{'type': 'task', 'id': self.task.pk}], qty=Decimal('1'))
        # Trivial multiplier (qty=1) — the stamp leaves est_qty/est_worker_time
        # numerically equal to the per-unit snapshot. Model.save() validates
        # the draft->accepted transition (only open->accepted is legal), so
        # flip the field directly — same intent as every other CO-acceptance
        # test's Estimate.objects.create(status=STATUS_ACCEPTED), just applied
        # after the fact since this estimate had to be draft to be bundled.
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_ACCEPTED)
        self.estimate.refresh_from_db()

        self.task.refresh_from_db()
        self.assertEqual(self.task.est_qty, Decimal('10.00'))
        self.assertEqual(self.task.est_worker_time, timedelta(hours=2))

        self.job.refresh_from_db()
        self.job.on_hold = True
        self.job.hold_reason = 'CO editing'
        self.job.save()
        self.co = ChangeOrderService.create(job_id=self.job.pk)
        self.replace_li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.line.pk, description='Cutting (more)',
            qty=Decimal('15'), units='hour', price=Decimal('1500.00'),
        )

    def _accept(self):
        ChangeOrderService.mark_open(self.co.pk)
        ChangeOrderService.update_status(self.co.pk, ChangeOrder.STATUS_ACCEPTED)


class COQtyChangeDriftTest(COReplaceQtyChangeBase):
    def test_moved_claim_preserves_per_unit_snapshot(self):
        self._accept()
        self.assertFalse(self.line.sources.exists())
        moved = ChangeOrderLineItemSource.objects.get(change_order_line_item=self.replace_li)
        self.assertEqual(moved.per_unit_qty, Decimal('10.00'))
        self.assertEqual(moved.per_unit_worker_time, timedelta(hours=2))

    def test_task_untouched_by_acceptance(self):
        self._accept()
        self.task.refresh_from_db()
        self.assertEqual(self.task.est_qty, Decimal('10.00'))
        self.assertEqual(self.task.est_worker_time, timedelta(hours=2))

    def test_moved_claim_shows_drift_against_new_qty(self):
        self._accept()
        pool = ChangeOrderWizardService.get_source_pool(self.co)
        entry = next(a for a in pool['atoms'] if a['type'] == 'task' and a['id'] == self.task.pk)
        self.assertEqual(entry['state'], 'claimed_by_current')
        self.assertEqual(entry['per_unit_qty'], Decimal('10.00'))
        self.assertEqual(entry['expected_total'], Decimal('150.00'))  # 10 * 15
        self.assertEqual(entry['expected_worker_time'], timedelta(hours=30))  # 2h * 15
        self.assertTrue(entry['drift'])

    def test_no_drift_before_acceptance(self):
        # Pre-acceptance, the claim still lives on the target (qty=1) — the
        # agreement hasn't moved yet, so it's still in sync.
        pool = ChangeOrderWizardService.get_source_pool(self.co)
        entry = next(a for a in pool['atoms'] if a['type'] == 'task' and a['id'] == self.task.pk)
        self.assertEqual(entry['state'], 'claimed_by_other')  # still the estimate's claim
        self.assertFalse(entry['drift'])


# ---------------------------------------------------------------------------
# 3./4./5. Restamp endpoint: resets both task fields, permission parity,
# whole-line claim rejected.
# ---------------------------------------------------------------------------

class RestampAtomEstimateAPITest(PerUnitDriftTestBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.manager = User.objects.create_user(username='pud_restamp_mgr', password='x')
        self.manager = grant_atoms(self.manager, 'can_manage_jobs')
        self.plain = User.objects.create_user(username='pud_restamp_plain', password='x')

    def _url(self, estimate=None):
        estimate = estimate or self.estimate
        return f'/api/estimates/{estimate.pk}/restamp-atom/'

    def test_restamp_resets_task_fields_and_clears_drift(self):
        task = self._task(Decimal('0.75'), timedelta(minutes=45))
        li = self._bundle([{'type': 'task', 'id': task.pk}], qty=Decimal('10'))
        src = li.sources.get()
        task.refresh_from_db()
        task.est_qty = Decimal('999.00')
        task.est_worker_time = timedelta(hours=99)
        task.save()

        # Confirm drift before restamping.
        task_src = self._sources_data(li)[0]
        self.assertTrue(task_src['drift'])

        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(self._url(), {'source_id': src.source_id}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn('message', resp.data)

        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('7.50'))
        self.assertEqual(task.est_worker_time, timedelta(hours=7, minutes=30))

        task_src = self._sources_data(li)[0]
        self.assertFalse(task_src['drift'])

    def test_restamp_resets_material(self):
        material = self._material(Decimal('4'))
        li = self._bundle([{'type': 'material', 'id': material.pk}], qty=Decimal('10'))
        src = li.sources.get()
        material.refresh_from_db()
        material.quantity = Decimal('1.00')
        material.save()

        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(self._url(), {'source_id': src.source_id}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

        material.refresh_from_db()
        self.assertEqual(material.quantity, Decimal('40.00'))

    def test_permission_denied_for_plain_worker(self):
        task = self._task(Decimal('1'))
        li = self._bundle([{'type': 'task', 'id': task.pk}], qty=Decimal('10'))
        src = li.sources.get()

        self.client.force_authenticate(user=self.plain)
        resp = self.client.post(self._url(), {'source_id': src.source_id}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_restamp_on_whole_line_claim_returns_400(self):
        task = self._task(Decimal('1'))
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': task.pk}])
        src = li.sources.get()

        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(self._url(), {'source_id': src.source_id}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.json())

    def test_restamp_claim_from_another_document_returns_400(self):
        task = self._task(Decimal('1'))
        li = self._bundle([{'type': 'task', 'id': task.pk}], qty=Decimal('10'))
        src = li.sources.get()

        other_estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-9002',
        )
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(self._url(other_estimate), {'source_id': src.source_id}, format='json')
        self.assertEqual(resp.status_code, 400)


class RestampAtomChangeOrderAPITest(COReplaceQtyChangeBase):
    """Reuses COReplaceQtyChangeBase's replace scaffolding, accepted here:
    the moved claim lives on `self.replace_li`, backed by the CO's new
    qty=15."""

    def setUp(self):
        super().setUp()
        self._accept()
        self.moved_src = ChangeOrderLineItemSource.objects.get(
            change_order_line_item=self.replace_li)
        self.client = APIClient()
        self.manager = User.objects.create_user(username='pud_co_restamp_mgr', password='x')
        self.manager = grant_atoms(self.manager, 'can_manage_jobs')
        self.plain = User.objects.create_user(username='pud_co_restamp_plain', password='x')

    def _url(self):
        return f'/api/change-orders/{self.co.pk}/restamp-atom/'

    def test_restamp_resets_to_new_agreement(self):
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(
            self._url(), {'source_id': self.moved_src.source_id}, format='json')
        self.assertEqual(resp.status_code, 200, resp.data)

        self.task.refresh_from_db()
        self.assertEqual(self.task.est_qty, Decimal('150.00'))  # 10 * 15
        self.assertEqual(self.task.est_worker_time, timedelta(hours=30))  # 2h * 15

        pool = ChangeOrderWizardService.get_source_pool(self.co)
        entry = next(a for a in pool['atoms'] if a['type'] == 'task' and a['id'] == self.task.pk)
        self.assertFalse(entry['drift'])

    def test_permission_denied_for_plain_worker(self):
        self.client.force_authenticate(user=self.plain)
        resp = self.client.post(
            self._url(), {'source_id': self.moved_src.source_id}, format='json')
        self.assertEqual(resp.status_code, 403)
