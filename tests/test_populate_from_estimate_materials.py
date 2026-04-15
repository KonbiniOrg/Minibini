from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory, Configuration
from apps.contacts.models import Contact
from apps.jobs.models import Job, PlanTask
from apps.estimates.models import EstWorksheet, Estimate
from apps.estimates.services import EstimateGenerationService
from apps.inventory.models import PriceListItem, PlanMaterial, Material
from apps.jobs.services import JobService


class PopulateFromEstimateLooseMaterialTest(TestCase):
    def setUp(self):
        Configuration.objects.get_or_create(
            key='estimate_number_sequence',
            defaults={'value': 'EST-{year}-{counter:05d}'}
        )
        Configuration.objects.get_or_create(
            key='estimate_counter',
            defaults={'value': '0'}
        )
        self.contact = Contact.objects.create(first_name='Test', last_name='User')

    def test_taskless_plan_material_lands_as_taskless_material(self):
        cat = AccountingCategory.objects.create(name='c', code='PE1')
        pli = PriceListItem.objects.create(
            code='I-PE', accounting_category=cat, is_inventoried=True,
        )
        ws_job = Job.objects.create(job_number='JOB-PE-SRC-1', contact=self.contact)
        ws = EstWorksheet.objects.create(job=ws_job)
        PlanMaterial.objects.create(
            plan_task=None, est_worksheet=ws,
            description='loose', quantity=Decimal('2'),
            price_list_item=pli,
        )
        # EstimateGenerationService may need at least one PlanTask too.
        PlanTask.objects.create(est_worksheet=ws, name='dummy', est_qty=Decimal('1'), rate=Decimal('0'))
        est = EstimateGenerationService().generate_estimate_from_worksheet(ws)
        est.status = Estimate.STATUS_OPEN
        est.save(update_fields=['status'])
        est.status = Estimate.STATUS_ACCEPTED
        est.save(update_fields=['status'])

        dst = Job.objects.create(job_number='JOB-PE-DST-1', contact=self.contact)
        JobService.populate_from_estimate(dst, est)

        loose = Material.objects.filter(job=dst, task__isnull=True)
        self.assertEqual(loose.count(), 1)
        self.assertEqual(loose.first().description, 'loose')
