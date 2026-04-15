from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task
from apps.inventory.models import Material, PlanMaterial, PriceListItem
from apps.core.models import AccountingCategory
from apps.estimates.models import EstWorksheet
from apps.jobs.models import PlanTask


class MaterialFieldsTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='labor')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', work_number='555-0100',
        )
        self.job = Job.objects.create(job_number='JOB-TEST-1', contact=self.contact)
        self.task = Task.objects.create(job=self.job, name='t')

    def test_material_has_job_consumption_state_restocked_qty(self):
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='x', quantity=Decimal('2.00'),
        )
        self.assertEqual(m.job_id, self.job.pk)
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_NA)
        self.assertEqual(m.restocked_qty, Decimal('0.00'))

    def test_material_effective_qty(self):
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='x', quantity=Decimal('5.00'),
        )
        m.restocked_qty = Decimal('2.00')
        m.save()
        self.assertEqual(m.effective_qty, Decimal('3.00'))

    def test_material_rejects_mismatched_task_job(self):
        job_b = Job.objects.create(job_number='JOB-TEST-2', contact=self.contact)
        with self.assertRaises(ValidationError):
            Material.objects.create(
                task=self.task, job=job_b,
                description='x', quantity=Decimal('1.00'),
            )

    def test_material_rejects_restocked_qty_exceeding_quantity(self):
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='x', quantity=Decimal('2.00'),
        )
        m.restocked_qty = Decimal('3.00')
        with self.assertRaises(ValidationError):
            m.save()


class PlanMaterialFieldsTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='plantest@example.com', work_number='555-0200',
        )
        self.job = Job.objects.create(job_number='JOB-PLAN-1', contact=self.contact)
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.pt = PlanTask.objects.create(est_worksheet=self.ws, name='pt1')

    def test_plan_material_has_est_worksheet(self):
        pm = PlanMaterial.objects.create(
            plan_task=self.pt, est_worksheet=self.ws,
            description='x', quantity=Decimal('1.00'),
        )
        self.assertEqual(pm.est_worksheet_id, self.ws.pk)

    def test_plan_material_invariant_rejects_mismatched_ws(self):
        other_job = Job.objects.create(job_number='JOB-PLAN-2', contact=self.contact)
        other_ws = EstWorksheet.objects.create(job=other_job)
        with self.assertRaises(ValidationError):
            PlanMaterial.objects.create(
                plan_task=self.pt, est_worksheet=other_ws,
                description='x', quantity=Decimal('1.00'),
            )
