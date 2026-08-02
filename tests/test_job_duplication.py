from decimal import Decimal
from apps.core.models import JobHistory
from datetime import timedelta
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import Configuration, AccountingCategory, User
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Task, RateScheme
from apps.inventory.models import Material, InventoryItem, Earmark
from apps.deliverables.models import Deliverable
from apps.jobs.services import JobService


def _make_scheme(suffix):
    ac = AccountingCategory.objects.create(code=f'DUP-{suffix}', name=f'dup-{suffix}')
    return RateScheme.objects.create(
        name=f'S-dup-{suffix}', algorithm=RateScheme.ENTERED_QTY,
        rate=Decimal('1'), unit_label='ea', accounting_category=ac,
    )


class DuplicateJobTestBase(BaseTestCase):
    """Builds a representative source Job: 2 tasks (one a subtask), 2 materials
    (one task-attached + inventoried, one task-less + inventoried), 2 deliverables."""

    def setUp(self):
        super().setUp()
        # Job numbering config (duplicate_job calls generate_next_number('job')).
        # We override the sequence pattern with a distinctive 'JOB-DUP-' prefix so
        # test_creates_approved_job_with_fresh_metadata can assert on it; this makes
        # the setup load-bearing, not just defensive.
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-DUP-{counter:04d}'})
        Configuration.objects.update_or_create(
            key='job_counter', defaults={'value': '0'})

        self.contact = Contact.objects.create(
            first_name='Source', last_name='Customer',
            email='src@example.com', work_number='555-0001',
        )
        self.other_contact = Contact.objects.create(
            first_name='New', last_name='Customer',
            email='new@example.com', work_number='555-0002',
        )
        self.category = AccountingCategory.objects.create(name='Material', code='DUPMAT')
        self.scheme = _make_scheme('a')
        self.plywood = InventoryItem.objects.create(
            code='DUP.PLY', description='Plywood', units='sheet',
            qty_on_hand=Decimal('20.00'), purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            accounting_category=self.category,
        )
        self.screws = InventoryItem.objects.create(
            code='DUP.SCR', description='Screws', units='ea',
            qty_on_hand=Decimal('50.00'), purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00'),
            accounting_category=self.category,
        )

        self.source = Job.objects.create(
            job_number='JOB-SRC-001', name='Cabinet run', description='Six uppers',
            contact=self.contact, customer_po_number='CUST-PO-9',
            due_date=None,
        )
        self.task_a = Task.objects.create(
            job=self.source, name='Build', description='Build the boxes',
            sort_order=1, est_worker_time=timedelta(hours=4),
            est_qty=Decimal('6'), rate_scheme=self.scheme,
        )
        self.task_b = Task.objects.create(
            job=self.source, name='Finish', description='Sand + seal',
            sort_order=2, est_worker_time=timedelta(hours=2),
            est_qty=Decimal('6'), rate_scheme=self.scheme,
            parent_task=self.task_a,
        )
        self.material_attached = Material.objects.create(
            job=self.source, task=self.task_a, inventory_item=self.plywood,
            quantity=Decimal('5.00'), unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        self.material_loose = Material.objects.create(
            job=self.source, task=None, inventory_item=self.screws,
            quantity=Decimal('2.00'), unit_cost=Decimal('8.00'),
            sell_price=Decimal('12.00'),
        )
        self.deliverable_1 = Deliverable.objects.create(
            job=self.source, description='Upper cabinet', qty_ordered=Decimal('6'),
            units='ea', sort_order=10,
        )
        self.deliverable_2 = Deliverable.objects.create(
            job=self.source, description='Toe kick', qty_ordered=Decimal('3'),
            units='ea', sort_order=20,
        )


class DuplicateApprovedTest(DuplicateJobTestBase):

    def test_creates_approved_job_with_fresh_metadata(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.other_contact, path='approved')
        new_job.refresh_from_db()
        self.assertEqual(new_job.status, Job.STATUS_APPROVED)
        self.assertIsNotNone(new_job.start_date)            # set by the approved transition
        self.assertEqual(new_job.contact_id, self.other_contact.pk)
        self.assertEqual(new_job.name, 'Cabinet run')
        self.assertEqual(new_job.description, 'Six uppers')
        self.assertNotEqual(new_job.job_number, self.source.job_number)
        self.assertTrue(new_job.job_number.startswith('JOB-DUP-'))
        self.assertEqual(new_job.customer_po_number, '')    # not copied
        self.assertIsNone(new_job.due_date)                 # not copied

    def test_copies_deliverables(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')
        delivs = Deliverable.objects.filter(job=new_job).order_by('sort_order')
        self.assertEqual([d.description for d in delivs], ['Upper cabinet', 'Toe kick'])
        self.assertEqual(delivs[0].qty_ordered, Decimal('6'))

    def test_copies_tasks_reset_and_preserves_hierarchy(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')
        tasks = {t.name: t for t in Task.objects.filter(job=new_job)}
        self.assertEqual(set(tasks), {'Build', 'Finish'})
        build, finish = tasks['Build'], tasks['Finish']
        # reset fields
        self.assertEqual(finish.status, Task.STATUS_PENDING)
        self.assertIsNone(finish.assignee_id)
        self.assertIsNone(finish.actual_qty)
        # carried fields
        self.assertEqual(finish.est_qty, Decimal('6'))
        self.assertEqual(finish.rate_scheme_id, self.scheme.pk)
        # hierarchy remapped to the NEW build task (not the source's)
        self.assertEqual(finish.parent_task_id, build.task_id)

    def test_copies_materials_with_task_links_and_reset_state(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')
        mats = Material.objects.filter(job=new_job)
        self.assertEqual(mats.count(), 2)
        attached = mats.get(inventory_item=self.plywood)
        loose = mats.get(inventory_item=self.screws)
        self.assertIsNotNone(attached.task_id)
        self.assertEqual(attached.task.job_id, new_job.pk)   # points at NEW task
        self.assertIsNone(loose.task_id)
        self.assertEqual(attached.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.assertIsNone(attached.po_line_item_id)

    def test_creates_earmarks(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')
        self.assertEqual(
            Earmark.objects.get(inventory_item=self.plywood, job=new_job).quantity,
            Decimal('5.00'))
        self.assertEqual(
            Earmark.objects.get(inventory_item=self.screws, job=new_job).quantity,
            Decimal('2.00'))

    def test_records_action_history_for_each_status_hop(self):
        # Job is @history-tracked, so each update_status also auto-logs an
        # 'audit' field-diff entry. We assert on the deliberate 'action' entries
        # (the user-facing "Duplicated from ..." narrative), not the audit noise.
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')
        actions = list(JobHistory.objects.filter(
            object_type='job', object_id=new_job.pk, entry_type='action'))
        hops = [a.changes.get('status', {}).get('new') for a in actions]
        self.assertEqual(hops.count(Job.STATUS_SUBMITTED), 1)
        self.assertEqual(hops.count(Job.STATUS_APPROVED), 1)
        self.assertEqual(len(hops), 2)
        self.assertTrue(all(
            a.changes.get('_action') == f'Duplicated from {self.source.job_number}'
            for a in actions))

    def test_duplication_preserves_material_provenance(self):
        """copy_fields carries cost_source, so a duplicated material keeps its
        provenance instead of auto-minting an 'entered' lot. A provisional
        (lot-less, cost_source=None) copy stays provisional; an established
        catalog-backed copy keeps its cost_source and shares the lot."""
        from apps.inventory.services import MaterialService
        # A provisional, lot-less material on the source job.
        provisional = Material.objects.create(
            job=self.source, task=None, inventory_item=None,
            quantity=Decimal('4.00'), sell_price=Decimal('50.00'),
            accounting_category=self.category, units='ea',
            description='provisional stock',
        )
        # An established material (already has a lot + cost_source).
        established = MaterialService.create_on_job(
            job=self.source, quantity=Decimal('2.00'),
            unit_cost=Decimal('9.00'), accounting_category=self.category,
            units='ea', description='entered stock',
        )
        self.assertIsNone(provisional.cost_source)
        self.assertEqual(established.cost_source, Material.COST_SOURCE_ENTERED)

        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')

        prov_copy = Material.objects.get(job=new_job, description='provisional stock')
        self.assertIsNone(prov_copy.inventory_item_id)          # still lot-less
        self.assertIsNone(prov_copy.cost_source)                # still provisional

        est_copy = Material.objects.get(job=new_job, description='entered stock')
        self.assertEqual(est_copy.cost_source, Material.COST_SOURCE_ENTERED)
        self.assertEqual(est_copy.inventory_item_id, established.inventory_item_id)

    def test_no_estimate_on_new_job(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')
        self.assertFalse(new_job.estimate_set.exists())

    def test_source_job_unchanged(self):
        JobService.duplicate_job(self.source, contact=self.other_contact, path='approved')
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, Job.STATUS_DRAFT)
        self.assertEqual(self.source.contact_id, self.contact.pk)
        self.assertEqual(Task.objects.filter(job=self.source).count(), 2)


class DuplicateEstimateTest(DuplicateJobTestBase):
    """Estimate path: work is copied onto the new DRAFT job (job-owns-atoms —
    no worksheet is created; estimates project from the Job's atoms)."""

    def test_creates_draft_job_no_status_walk(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.other_contact, path='estimate')
        self.assertEqual(new_job.status, Job.STATUS_DRAFT)
        self.assertIsNone(new_job.start_date)
        self.assertEqual(new_job.contact_id, self.other_contact.pk)

    def test_copies_tasks_onto_job(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='estimate')
        names = set(Task.objects.filter(job=new_job).values_list('name', flat=True))
        self.assertEqual(names, {'Build', 'Finish'})
        build = Task.objects.get(job=new_job, name='Build')
        self.assertEqual(build.est_qty, Decimal('6'))
        self.assertEqual(build.rate_scheme_id, self.scheme.pk)
        self.assertEqual(build.est_worker_time, timedelta(hours=4))  # carried over
        # Hierarchy is preserved on the copied tasks.
        finish = Task.objects.get(job=new_job, name='Finish')
        self.assertEqual(finish.parent_task_id, build.pk)

    def test_copies_materials_preserving_task_attachment(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='estimate')
        build = Task.objects.get(job=new_job, name='Build')
        attached = Material.objects.get(job=new_job, inventory_item=self.plywood)
        loose = Material.objects.get(job=new_job, inventory_item=self.screws)
        self.assertEqual(attached.task_id, build.pk)
        self.assertIsNone(loose.task_id)

    def test_no_earmarks_on_estimate_path(self):
        # Estimate path copies materials onto a new DRAFT job. Pre-approval jobs
        # must NOT earmark on create (gate added in MaterialService.create_on_job);
        # earmarks are created in bulk at estimate acceptance instead.
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='estimate')
        self.assertEqual(Earmark.objects.filter(job=new_job).count(), 0)


class DuplicateApiTest(DuplicateJobTestBase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.mgr = User.objects.create_user(username='dup_mgr', password='x')
        self.mgr.user_permissions.add(Permission.objects.get(
            codename='can_manage_jobs', content_type__app_label='core'))
        self.mgr = User.objects.get(pk=self.mgr.pk)  # refresh permission cache
        self.worker = User.objects.create_user(username='dup_worker', password='x')

    def _url(self):
        return f'/api/jobs/{self.source.pk}/duplicate/'

    def test_requires_can_manage_jobs(self):
        self.client.force_authenticate(user=self.worker)
        r = self.client.post(self._url(),
                             {'contact_id': self.contact.pk, 'path': 'approved'},
                             format='json')
        self.assertEqual(r.status_code, 403, r.data)

    def test_approved_path_returns_new_job_id(self):
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(self._url(),
                             {'contact_id': self.other_contact.pk, 'path': 'approved'},
                             format='json')
        self.assertEqual(r.status_code, 201, r.data)
        new_job = Job.objects.get(pk=r.data['job_id'])
        self.assertEqual(new_job.status, Job.STATUS_APPROVED)
        self.assertEqual(new_job.contact_id, self.other_contact.pk)

    def test_estimate_path_returns_new_job_id(self):
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(self._url(),
                             {'contact_id': self.contact.pk, 'path': 'estimate'},
                             format='json')
        self.assertEqual(r.status_code, 201, r.data)
        new_job = Job.objects.get(pk=r.data['job_id'])
        self.assertEqual(new_job.status, Job.STATUS_DRAFT)
        self.assertTrue(Task.objects.filter(job=new_job).exists())

    def test_bad_path_is_400(self):
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(self._url(),
                             {'contact_id': self.contact.pk, 'path': 'nope'},
                             format='json')
        self.assertEqual(r.status_code, 400, r.data)

    def test_missing_contact_is_400(self):
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(self._url(), {'path': 'approved'}, format='json')
        self.assertEqual(r.status_code, 400, r.data)

    def test_unknown_contact_is_400(self):
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(self._url(),
                             {'contact_id': 999999, 'path': 'approved'},
                             format='json')
        self.assertEqual(r.status_code, 400, r.data)

    def test_non_numeric_contact_is_400(self):
        # A non-numeric contact_id must be a clean 400, not a 500 from the ORM.
        self.client.force_authenticate(user=self.mgr)
        r = self.client.post(self._url(),
                             {'contact_id': 'abc', 'path': 'approved'},
                             format='json')
        self.assertEqual(r.status_code, 400, r.data)


class DuplicateEmptySourceTest(BaseTestCase):
    """A source Job with no tasks, materials, or deliverables still duplicates
    cleanly on both paths (spec edge case: earmark creation early-returns and the
    status walk must still succeed on a work-less job)."""

    def setUp(self):
        super().setUp()
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-DUP-{counter:04d}'})
        Configuration.objects.update_or_create(
            key='job_counter', defaults={'value': '0'})
        self.contact = Contact.objects.create(
            first_name='Bare', last_name='Customer',
            email='bare@example.com', work_number='555-0009',
        )
        self.source = Job.objects.create(
            job_number='JOB-BARE-001', name='Bare job', description='',
            contact=self.contact,
        )

    def test_approved_path_on_empty_source(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='approved')
        self.assertEqual(new_job.status, Job.STATUS_APPROVED)
        self.assertIsNotNone(new_job.start_date)
        self.assertEqual(Task.objects.filter(job=new_job).count(), 0)
        self.assertEqual(Material.objects.filter(job=new_job).count(), 0)
        self.assertEqual(Earmark.objects.filter(job=new_job).count(), 0)
        self.assertEqual(Deliverable.objects.filter(job=new_job).count(), 0)

    def test_estimate_path_on_empty_source(self):
        new_job = JobService.duplicate_job(
            self.source, contact=self.contact, path='estimate')
        self.assertEqual(new_job.status, Job.STATUS_DRAFT)
        self.assertEqual(Task.objects.filter(job=new_job).count(), 0)
        self.assertEqual(Material.objects.filter(job=new_job).count(), 0)
