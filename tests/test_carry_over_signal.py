from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import Estimate, EstimateLineItem, EstWorksheet
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import PlanMaterial
from apps.jobs.models import Job, PlanTask, RateScheme, Task


class CarryOverSignalTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001',
        )
        self.ws = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        self.pt = PlanTask.objects.create(
            est_worksheet=self.ws, name='Setup', units='hours',
            est_qty=Decimal('2'), accounting_category=self.cat,
            rate_scheme=self.scheme, estimated_billable_qty=Decimal('2'),
        )
        self.estimate = EstimateWizardService.open_for_worksheet(self.ws)
        EstimateLineItem.objects.create(
            estimate=self.estimate, description='Setup labor',
            price=Decimal('200.00'),
        )

    def test_carry_over_fires_on_estimate_accepted(self):
        # Walk the estimate through draft → open → accepted
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        self.estimate.status = Estimate.STATUS_ACCEPTED
        self.estimate.save()

        # Carry-over should have fired and created a Task on the job
        self.assertEqual(Task.objects.filter(job=self.job).count(), 1)
