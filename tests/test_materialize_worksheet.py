"""The shared worksheet→job materialization core that both estimate-acceptance
carry-over (#2) and the manual copy-from-worksheet button (#3) delegate to."""

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, Task, PlanTask, ServiceItem
from apps.estimates.models import EstWorksheet
from apps.inventory.models import PlanMaterial, Material, Earmark, InventoryItem
from apps.jobs.services import JobService


def _make_scheme(suffix):
    ac = AccountingCategory.objects.create(code=f'MW-{suffix}', name=f'mw-{suffix}')
    return ServiceItem.objects.create(
        name=f'S-mw-{suffix}', algorithm=ServiceItem.FLAT_FEE,
        rate=Decimal('1'), unit_label='ea', accounting_category=ac,
    )


class MaterializeWorksheetTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(code='MW-MAT', name='mw-mat')
        self.scheme = _make_scheme('core')
        self.contact = Contact.objects.create(
            first_name='T', last_name='C', email='mw@test.com')
        self.job = Job.objects.create(job_number='JOB-MW', contact=self.contact)
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.pli = InventoryItem.objects.create(
            code='MW-PLI', accounting_category=self.ac, is_catalog=True,
            qty_on_hand=Decimal('100'),
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Cut', description='cut it',
            service_item=self.scheme, est_qty=Decimal('2'),
            sort_order=7, est_worker_time=timedelta(hours=3),
        )
        # Task-attached material (inventoried, non-default units).
        self.pm_attached = PlanMaterial.objects.create(
            est_worksheet=self.ws, plan_task=self.pt, description='Steel',
            quantity=Decimal('10'), units='kg', accounting_category=self.ac,
            inventory_item=self.pli,
        )
        # Task-less material.
        self.pm_loose = PlanMaterial.objects.create(
            est_worksheet=self.ws, plan_task=None, description='Washers',
            quantity=Decimal('5'), units='box', accounting_category=self.ac,
        )

    def test_creates_tasks_preserving_sort_order_and_worker_time(self):
        JobService.materialize_worksheet_onto_job(self.job, self.ws)
        task = Task.objects.get(job=self.job)
        self.assertEqual(task.name, 'Cut')
        self.assertEqual(task.sort_order, 7)
        self.assertEqual(task.est_worker_time, timedelta(hours=3))
        self.assertEqual(task.source_plan_task, self.pt)

    def test_creates_materials_preserving_units_and_mapping(self):
        JobService.materialize_worksheet_onto_job(self.job, self.ws)
        task = Task.objects.get(job=self.job)

        steel = Material.objects.get(job=self.job, description='Steel')
        self.assertEqual(steel.units, 'kg')
        self.assertEqual(steel.task, task)
        self.assertEqual(steel.source_plan_material, self.pm_attached)

        washers = Material.objects.get(job=self.job, description='Washers')
        self.assertEqual(washers.units, 'box')
        self.assertIsNone(washers.task)

    def test_creates_earmarks_for_inventoried_materials(self):
        JobService.materialize_worksheet_onto_job(self.job, self.ws)
        earmark = Earmark.objects.get(job=self.job, inventory_item=self.pli)
        self.assertEqual(earmark.quantity, Decimal('10'))

    def test_returns_counts(self):
        result = JobService.materialize_worksheet_onto_job(self.job, self.ws)
        self.assertEqual(result, {'tasks_created': 1, 'materials_created': 2})

    def test_idempotent_on_rerun(self):
        JobService.materialize_worksheet_onto_job(self.job, self.ws)
        result = JobService.materialize_worksheet_onto_job(self.job, self.ws)
        self.assertEqual(result, {'tasks_created': 0, 'materials_created': 0})
        self.assertEqual(Task.objects.filter(job=self.job).count(), 1)
        self.assertEqual(Material.objects.filter(job=self.job).count(), 2)
        self.assertEqual(
            Earmark.objects.filter(job=self.job, inventory_item=self.pli).count(), 1)

    def test_clones_faithfully_when_scheme_superseded(self):
        self.scheme.supersede(name='S-mw-core v2')
        JobService.materialize_worksheet_onto_job(self.job, self.ws)
        task = Task.objects.get(job=self.job)
        self.assertEqual(task.service_item_id, self.scheme.pk)
