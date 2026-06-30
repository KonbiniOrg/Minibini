from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, PlanTask, RateScheme
from apps.estimates.models import EstWorksheet
from apps.inventory.models import InventoryItem, PlanMaterial, Material, Earmark
from apps.jobs.services import JobService


class CopyFromWorksheetMaterialsTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c', code='CW1')
        self.pli = InventoryItem.objects.create(
            code='I-CW', accounting_category=self.cat, is_catalog=True,
        )
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User', email='cfw@test.com'
        )
        self.src_job = Job.objects.create(job_number='JOB-SRC-1', contact=self.contact)
        self.ws = EstWorksheet.objects.create(job=self.src_job)
        self.scheme_ac = AccountingCategory.objects.create(name='cfwm-ac', code='CFWM-AC')
        self.scheme = RateScheme.objects.create(
            name='S-cfwm', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('1'), unit_label='ea',
            accounting_category=self.scheme_ac,
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='pt',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        PlanMaterial.objects.create(
            plan_task=self.pt, est_worksheet=self.ws,
            description='x', quantity=Decimal('3'), inventory_item=self.pli,
        )

    def test_task_attached_materials_copy_with_earmark_upsert(self):
        dst = Job.objects.create(job_number='JOB-DST-1', contact=self.contact,
                                 status=Job.STATUS_APPROVED)
        JobService.copy_from_worksheet(dst.pk, self.ws.pk)
        mats = Material.objects.filter(job=dst, task__isnull=False)
        self.assertEqual(mats.count(), 1)
        e = Earmark.objects.get(inventory_item=self.pli, job=dst)
        self.assertEqual(e.quantity, Decimal('3'))
        # Concern: copied task-attached inventoried material must be CONSUMPTION_STATE_PENDING
        self.assertEqual(mats.first().consumption_state, Material.CONSUMPTION_STATE_PENDING,
                         'copied inventoried material should have consumption_state=pending')

    def test_taskless_plan_materials_copy_to_taskless_materials(self):
        PlanMaterial.objects.create(
            plan_task=None, est_worksheet=self.ws,
            description='loose', quantity=Decimal('2'), inventory_item=self.pli,
        )
        dst = Job.objects.create(job_number='JOB-DST-2', contact=self.contact,
                                 status=Job.STATUS_APPROVED)
        JobService.copy_from_worksheet(dst.pk, self.ws.pk)
        loose = Material.objects.filter(job=dst, task__isnull=True)
        self.assertEqual(loose.count(), 1)
        self.assertEqual(loose.first().description, 'loose')
        e = Earmark.objects.get(inventory_item=self.pli, job=dst)
        self.assertEqual(e.quantity, Decimal('5'))
