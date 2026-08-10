"""Task 7 (CO amend-in-place plan): CO add-lines gain estimate-style
authoring claims via ``ChangeOrderWizardService`` (subclasses
``EstimateWizardService`` — a CO composes future agreement, so its pool and
billing amounts share estimate semantics: est_qty billing, cancelled tasks
and released materials excluded from the pool).

Covers (brief Step 1 a-h):
  (a) CO source-pool marks estimate-claimed atoms claimed_by_other, this-CO
      claims claimed_by_current, another CO's claims claimed_by_other
  (b) line-items-from-atoms creates an action='add' CO line with source rows
      + derived values (single-atom copy rule)
  (c) add-atoms onto an add line works; onto a replace line -> 400
  (d) remove-atoms deletes the line when the last source goes
  (e) discarding the draft CO releases the claims
  (f) send guard no longer trips on a sourced AC-less add line
  (g) estimate pool shows a CO-claimed atom as claimed_by_other (symmetric
      fix — also exercised in tests/test_estimate_wizard_service.py)
  (h) accepting a CO with an authored-claimed add line crystallizes nothing
      for it (sources already exist) and the claims survive

Plus: the API endpoints (source-pool, line-items-from-atoms, add-atoms,
remove-atoms) mirroring the estimate viewset's, and the
recompute_adjustment_replaces call every atom-mutation endpoint must make
(Task 6 interface).
"""
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.deliverables.models import Deliverable
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, ChangeOrderLineItemSource,
    Estimate, EstimateLineItem, EstimateLineItemSource,
)
from apps.estimates.services import ChangeOrderClaimConflict, ChangeOrderWizardService
from apps.inventory.models import Material
from apps.jobs.models import Job, RateScheme, Task
from tests.base import grant_atoms


# ---------------------------------------------------------------------------
# Shared scaffolding: an approved job, on hold, with an accepted estimate
# (one line already claims a task — the "already agreed" atom the CO pool
# must show as claimed_by_other) and a draft ChangeOrder ready for authoring.
# ---------------------------------------------------------------------------

class COWizardServiceBase(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )

        # An unclaimed task + material — the pool's available atoms.
        self.task = Task(job=self.job, name='Cutting', est_qty=Decimal('2'))
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()

        self.material = Material.objects.create(
            job=self.job, description='Steel', quantity=Decimal('3'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )

        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_ACCEPTED,
        )

        # A task already claimed by the accepted estimate itself — the CO
        # pool must show this as claimed_by_other (covered work, not
        # CO-addable), even though it's the estimate this CO amends.
        self.claimed_task = Task(job=self.job, name='Sanding', est_qty=Decimal('1'))
        self.claimed_task.stamp_from_scheme(self.scheme)
        self.claimed_task.save()
        self.claimed_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Sanding',
            qty=Decimal('1'), price=Decimal('100.00'), units='hour',
            accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.claimed_line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.claimed_task.pk,
        )

        Deliverable.objects.create(
            job=self.job, description='Widget', qty_ordered=Decimal('1'),
            units='ea', sort_order=10,
        )

        self.co = self._make_draft_co()

    def _make_draft_co(self):
        self.job.refresh_from_db()
        self.job.on_hold = True
        self.job.hold_reason = 'CO editing'
        self.job.save()
        return ChangeOrderService.create(job_id=self.job.pk)


# ---------------------------------------------------------------------------
# (a) / (g)-adjacent: source pool cross-lens claims
# ---------------------------------------------------------------------------

class ChangeOrderSourcePoolTest(COWizardServiceBase):
    def test_pool_has_task_and_material_atoms(self):
        pool = ChangeOrderWizardService.get_source_pool(self.co)
        atom_ids = [(a['type'], a['id']) for a in pool['atoms']]
        self.assertIn(('task', self.task.pk), atom_ids)
        self.assertIn(('material', self.material.pk), atom_ids)

    def test_unclaimed_atom_is_available(self):
        pool = ChangeOrderWizardService.get_source_pool(self.co)
        entry = next(a for a in pool['atoms'] if a['type'] == 'task' and a['id'] == self.task.pk)
        self.assertEqual(entry['state'], 'available')

    def test_estimate_claimed_atom_is_claimed_by_other(self):
        pool = ChangeOrderWizardService.get_source_pool(self.co)
        entry = next(
            a for a in pool['atoms']
            if a['type'] == 'task' and a['id'] == self.claimed_task.pk
        )
        self.assertEqual(entry['state'], 'claimed_by_other')
        self.assertEqual(entry['claiming_estimate_number'], self.estimate.estimate_number)

    def test_other_co_claimed_atom_is_claimed_by_other(self):
        other_co = ChangeOrder.objects.create(job=self.job, estimate=self.estimate)
        other_li = ChangeOrderLineItem.objects.create(
            change_order=other_co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Other CO line', qty=Decimal('1'), price=Decimal('10.00'),
            accounting_category=self.cat,
        )
        ChangeOrderLineItemSource.objects.create(
            change_order_line_item=other_li,
            source_type=ChangeOrderLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        pool = ChangeOrderWizardService.get_source_pool(self.co)
        entry = next(a for a in pool['atoms'] if a['type'] == 'task' and a['id'] == self.task.pk)
        self.assertEqual(entry['state'], 'claimed_by_other')
        self.assertEqual(entry['claiming_change_order_number'], other_co.change_order_number)

    def test_current_co_claimed_atom_is_claimed_by_current(self):
        li = ChangeOrderWizardService.add_atoms_to_new_line_item(
            self.co, [{'type': 'task', 'id': self.task.pk}])
        pool = ChangeOrderWizardService.get_source_pool(self.co)
        entry = next(a for a in pool['atoms'] if a['type'] == 'task' and a['id'] == self.task.pk)
        self.assertEqual(entry['state'], 'claimed_by_current')
        self.assertEqual(entry['claiming_line_item_id'], li.pk)


# ---------------------------------------------------------------------------
# (b) line-items-from-atoms
# ---------------------------------------------------------------------------

class AddAtomsToNewLineItemCOTest(COWizardServiceBase):
    def test_creates_add_line_with_sources_and_derived_values(self):
        li = ChangeOrderWizardService.add_atoms_to_new_line_item(
            self.co, [{'type': 'task', 'id': self.task.pk}])
        self.assertEqual(li.action, ChangeOrderLineItem.ACTION_ADD)
        self.assertEqual(li.change_order_id, self.co.pk)
        self.assertEqual(li.sources.count(), 1)
        self.assertEqual(li.description, self.task.name)
        self.assertEqual(li.qty, self.task.est_qty)
        self.assertEqual(li.price, self.task.effective_rate())
        self.assertEqual(li.accounting_category_id, self.cat.pk)

    def test_claim_conflict_raises_change_order_claim_conflict(self):
        ChangeOrderWizardService.add_atoms_to_new_line_item(
            self.co, [{'type': 'task', 'id': self.task.pk}])
        with self.assertRaises(ChangeOrderClaimConflict) as ctx:
            ChangeOrderWizardService.add_atoms_to_new_line_item(
                self.co, [{'type': 'task', 'id': self.task.pk}])
        self.assertEqual(ctx.exception.atom_ids, [{'type': 'task', 'id': self.task.pk}])


# ---------------------------------------------------------------------------
# (c) add-atoms: add lines only
# ---------------------------------------------------------------------------

class AddAtomsToLineItemCOTest(COWizardServiceBase):
    def test_add_atoms_onto_add_line_appends_source(self):
        li = ChangeOrderWizardService.add_atoms_to_new_line_item(
            self.co, [{'type': 'task', 'id': self.task.pk}])
        ChangeOrderWizardService.add_atoms_to_line_item(
            li, [{'type': 'material', 'id': self.material.pk}])
        li.refresh_from_db()
        self.assertEqual(li.sources.count(), 2)

    def test_add_atoms_onto_replace_line_is_refused(self):
        target_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=99, description='Old',
            qty=Decimal('1'), price=Decimal('10.00'), accounting_category=self.cat,
        )
        replace_li = ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=target_line, description='New', qty=Decimal('1'),
            price=Decimal('20.00'), accounting_category=self.cat,
        )
        with self.assertRaises(ValidationError) as ctx:
            ChangeOrderWizardService.add_atoms_to_line_item(
                replace_li, [{'type': 'task', 'id': self.task.pk}])
        self.assertIn('add lines only', str(ctx.exception))


# ---------------------------------------------------------------------------
# (d) remove-atoms
# ---------------------------------------------------------------------------

class RemoveAtomsFromLineItemCOTest(COWizardServiceBase):
    def test_remove_last_source_deletes_line(self):
        li = ChangeOrderWizardService.add_atoms_to_new_line_item(
            self.co, [{'type': 'task', 'id': self.task.pk}])
        src_id = li.sources.first().source_id
        result = ChangeOrderWizardService.remove_atoms_from_line_item(li, [src_id])
        self.assertTrue(result['line_item_deleted'])
        self.assertFalse(ChangeOrderLineItem.objects.filter(pk=li.pk).exists())

    def test_remove_one_of_two_sources_keeps_line(self):
        li = ChangeOrderWizardService.add_atoms_to_new_line_item(
            self.co, [
                {'type': 'task', 'id': self.task.pk},
                {'type': 'material', 'id': self.material.pk},
            ])
        src_id = li.sources.get(source_type='material').source_id
        result = ChangeOrderWizardService.remove_atoms_from_line_item(li, [src_id])
        self.assertFalse(result['line_item_deleted'])
        li.refresh_from_db()
        self.assertEqual(li.sources.count(), 1)


# ---------------------------------------------------------------------------
# (e) discard releases claims
# ---------------------------------------------------------------------------

class DiscardDraftReleasesClaimsCOTest(COWizardServiceBase):
    def test_discard_draft_co_releases_claims(self):
        ChangeOrderWizardService.add_atoms_to_new_line_item(
            self.co, [{'type': 'task', 'id': self.task.pk}])
        self.assertEqual(
            ChangeOrderLineItemSource.objects.filter(
                source_type='task', source_pk=self.task.pk).count(),
            1,
        )
        ChangeOrderService.discard_draft(self.co.pk)
        self.assertEqual(
            ChangeOrderLineItemSource.objects.filter(
                source_type='task', source_pk=self.task.pk).count(),
            0,
        )


# ---------------------------------------------------------------------------
# (f) send guard: sourced add lines are exempt from the bare-AC check
# ---------------------------------------------------------------------------

class SendGuardSourcesExemptCOTest(COWizardServiceBase):
    def test_sourced_add_line_without_ac_does_not_block_send(self):
        li = ChangeOrderWizardService.add_atoms_to_new_line_item(
            self.co, [{'type': 'task', 'id': self.task.pk}])
        li.accounting_category = None
        li.save()
        # Must not raise: the line has sources, so it isn't a "bare" hand line.
        ChangeOrderService.assert_all_bare_add_lines_have_ac(self.co)

    def test_bare_add_line_without_sources_or_ac_still_blocks(self):
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_ADD,
            description='No category', qty=Decimal('1'), price=Decimal('10.00'),
        )
        with self.assertRaises(ValidationError):
            ChangeOrderService.assert_all_bare_add_lines_have_ac(self.co)


# ---------------------------------------------------------------------------
# (h) acceptance: authored-claimed add lines crystallize nothing, claims survive
# ---------------------------------------------------------------------------

class AcceptanceAuthoredClaimedAddCOTest(COWizardServiceBase):
    def test_authored_claimed_add_line_crystallizes_nothing_and_claims_survive(self):
        li = ChangeOrderWizardService.add_atoms_to_new_line_item(
            self.co, [{'type': 'task', 'id': self.task.pk}])
        self.assertEqual(li.sources.count(), 1)
        pre_task_count = Task.objects.filter(job=self.job).count()

        ChangeOrderService.mark_open(self.co.pk)
        ChangeOrderService.update_status(self.co.pk, ChangeOrder.STATUS_ACCEPTED)

        # No new atom minted for this line — it already pointed at self.task.
        self.assertEqual(Task.objects.filter(job=self.job).count(), pre_task_count)
        li.refresh_from_db()
        self.assertEqual(li.sources.count(), 1)
        self.assertEqual(li.sources.first().source_pk, self.task.pk)


# ---------------------------------------------------------------------------
# API endpoints: source-pool, line-items-from-atoms, add-atoms, remove-atoms
# ---------------------------------------------------------------------------

class ChangeOrderWizardAPITest(COWizardServiceBase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.manager = User.objects.create_user(username='co_wizard_mgr', password='x')
        self.manager = grant_atoms(self.manager, 'can_manage_jobs')
        self.plain = User.objects.create_user(username='co_wizard_plain', password='x')

    def test_source_pool_endpoint_is_authenticated_only(self):
        self.client.force_authenticate(user=self.plain)
        resp = self.client.get(f'/api/change-orders/{self.co.pk}/source-pool/')
        self.assertEqual(resp.status_code, 200)
        types = [a['type'] for a in resp.json()['atoms']]
        self.assertIn('task', types)
        self.assertIn('material', types)

    def test_line_items_from_atoms_requires_can_manage_job_or_pm(self):
        self.client.force_authenticate(user=self.plain)
        resp = self.client.post(
            f'/api/change-orders/{self.co.pk}/line-items-from-atoms/',
            {'atoms': [{'type': 'task', 'id': self.task.pk}]}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_line_items_from_atoms_endpoint(self):
        self.client.force_authenticate(user=self.manager)
        resp = self.client.post(
            f'/api/change-orders/{self.co.pk}/line-items-from-atoms/',
            {'atoms': [{'type': 'task', 'id': self.task.pk}]}, format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['action'], ChangeOrderLineItem.ACTION_ADD)

    def test_line_items_from_atoms_conflict_returns_409(self):
        self.client.force_authenticate(user=self.manager)
        url = f'/api/change-orders/{self.co.pk}/line-items-from-atoms/'
        payload = {'atoms': [{'type': 'task', 'id': self.task.pk}]}
        self.client.post(url, payload, format='json')
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()['code'], 'atoms_already_claimed')

    def test_add_atoms_endpoint(self):
        self.client.force_authenticate(user=self.manager)
        li = ChangeOrderWizardService.add_atoms_to_new_line_item(
            self.co, [{'type': 'task', 'id': self.task.pk}])
        resp = self.client.post(
            f'/api/change-orders/{self.co.pk}/line-items/{li.pk}/add-atoms/',
            {'atoms': [{'type': 'material', 'id': self.material.pk}]}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        li.refresh_from_db()
        self.assertEqual(li.sources.count(), 2)

    def test_add_atoms_endpoint_onto_replace_line_returns_400(self):
        self.client.force_authenticate(user=self.manager)
        target_line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=50, description='Old',
            qty=Decimal('1'), price=Decimal('10.00'), accounting_category=self.cat,
        )
        replace_li = ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=target_line, description='New', qty=Decimal('1'),
            price=Decimal('20.00'), accounting_category=self.cat,
        )
        resp = self.client.post(
            f'/api/change-orders/{self.co.pk}/line-items/{replace_li.pk}/add-atoms/',
            {'atoms': [{'type': 'task', 'id': self.task.pk}]}, format='json',
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_remove_atoms_endpoint(self):
        self.client.force_authenticate(user=self.manager)
        li = ChangeOrderWizardService.add_atoms_to_new_line_item(
            self.co, [
                {'type': 'task', 'id': self.task.pk},
                {'type': 'material', 'id': self.material.pk},
            ])
        src_id = li.sources.get(source_type='material').source_id
        resp = self.client.post(
            f'/api/change-orders/{self.co.pk}/line-items/{li.pk}/remove-atoms/',
            {'source_ids': [src_id]}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(resp.json()['line_item_deleted'])

    def test_remove_all_atoms_deletes_line_item(self):
        self.client.force_authenticate(user=self.manager)
        li = ChangeOrderWizardService.add_atoms_to_new_line_item(
            self.co, [{'type': 'task', 'id': self.task.pk}])
        all_ids = list(li.sources.values_list('source_id', flat=True))
        resp = self.client.post(
            f'/api/change-orders/{self.co.pk}/line-items/{li.pk}/remove-atoms/',
            {'source_ids': all_ids}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(resp.json()['line_item_deleted'])


# ---------------------------------------------------------------------------
# recompute_adjustment_replaces: atom-mutation endpoints re-price adjustment
# replace lines against the amended basis (Task 6 interface).
# ---------------------------------------------------------------------------

def _advance_job_to_on_hold(job):
    from apps.jobs.services import JobService
    for s in (Job.STATUS_SUBMITTED, Job.STATUS_APPROVED):
        job.status = s
        job.save()
    JobService.hold_job(job.pk, 'CO editing')
    job.refresh_from_db()


class AtomEndpointRecomputesAdjustmentReplaceTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        self.labor = AccountingCategory.objects.create(
            code='LAB-COATOM', name='Labor-COATOM', taxable=False)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-1',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0002',
        )
        Deliverable.objects.create(
            job=self.job, description='Widget', qty_ordered=Decimal('1'),
            units='ea', sort_order=10,
        )

        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-ATOM-CO-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )
        self.li_labor = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, description='Labor',
            qty=Decimal('1'), price=Decimal('100.00'), accounting_category=self.labor,
        )
        self.adj_scheme = RateScheme.objects.create(
            name='Rush-COATOM', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%', accounting_category=self.labor,
        )
        self.adj = EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, description='Rush 10%',
            qty=Decimal('1'), price=Decimal('10.00'), units='pct',
            accounting_category=self.labor,
            adjustment_service=self.adj_scheme, adjustment_percent=Decimal('10.00'),
        )

        self.task_scheme = RateScheme.objects.create(
            name='Hourly-COATOM', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('60'), unit_label='hour', accounting_category=self.labor,
        )
        self.task = Task(job=self.job, name='Extra work', est_qty=Decimal('1'))
        self.task.stamp_from_scheme(self.task_scheme)
        self.task.save()

        _advance_job_to_on_hold(self.job)
        self.co = ChangeOrderService.create(job_id=self.job.pk)

        # 10% of 100 = 10.00 at creation.
        self.replace_li = ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.adj.pk, adjustment_percent='10.00',
        )

        self.client = APIClient()
        self.manager = User.objects.create_user(username='co_atom_recompute_mgr', password='x')
        self.manager = grant_atoms(self.manager, 'can_manage_jobs')
        self.client.force_authenticate(user=self.manager)

    def test_line_items_from_atoms_recomputes_adjustment_replace(self):
        self.assertEqual(self.replace_li.price, Decimal('10.00'))
        resp = self.client.post(
            f'/api/change-orders/{self.co.pk}/line-items-from-atoms/',
            {'atoms': [{'type': 'task', 'id': self.task.pk}]}, format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.replace_li.refresh_from_db()
        # basis now 100 + 60 (task est_qty 1 x rate 60) = 160 -> 10% = 16.00
        self.assertEqual(self.replace_li.price, Decimal('16.00'))
