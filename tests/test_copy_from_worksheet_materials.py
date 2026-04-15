from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, PlanTask
from apps.estimates.models import EstWorksheet
from apps.inventory.models import PriceListItem, PlanMaterial, Material, Earmark
from apps.jobs.services import JobService


class CopyFromWorksheetMaterialsTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c', code='CW1')
        self.pli = PriceListItem.objects.create(
            code='I-CW', accounting_category=self.cat, is_inventoried=True,
        )
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User', email='cfw@test.com'
        )
        self.src_job = Job.objects.create(job_number='JOB-SRC-1', contact=self.contact)
        self.ws = EstWorksheet.objects.create(job=self.src_job)
        self.pt = PlanTask.objects.create(est_worksheet=self.ws, name='pt')
        PlanMaterial.objects.create(
            plan_task=self.pt, est_worksheet=self.ws,
            description='x', quantity=Decimal('3'), price_list_item=self.pli,
        )

    def test_task_attached_materials_copy_with_earmark_upsert(self):
        dst = Job.objects.create(job_number='JOB-DST-1', contact=self.contact)
        JobService.copy_from_worksheet(dst.pk, self.ws.pk)
        mats = Material.objects.filter(job=dst, task__isnull=False)
        self.assertEqual(mats.count(), 1)
        e = Earmark.objects.get(price_list_item=self.pli, job=dst)
        self.assertEqual(e.quantity, Decimal('3'))
        # Concern: copied task-attached inventoried material must be CONSUMPTION_STATE_PENDING
        self.assertEqual(mats.first().consumption_state, Material.CONSUMPTION_STATE_PENDING,
                         'copied inventoried material should have consumption_state=pending')

    def test_taskless_plan_materials_copy_to_taskless_materials(self):
        PlanMaterial.objects.create(
            plan_task=None, est_worksheet=self.ws,
            description='loose', quantity=Decimal('2'), price_list_item=self.pli,
        )
        dst = Job.objects.create(job_number='JOB-DST-2', contact=self.contact)
        JobService.copy_from_worksheet(dst.pk, self.ws.pk)
        loose = Material.objects.filter(job=dst, task__isnull=True)
        self.assertEqual(loose.count(), 1)
        self.assertEqual(loose.first().description, 'loose')
        e = Earmark.objects.get(price_list_item=self.pli, job=dst)
        self.assertEqual(e.quantity, Decimal('5'))
