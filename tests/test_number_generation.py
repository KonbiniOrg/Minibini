from datetime import datetime
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.core.services import NumberGenerationService
from apps.estimates.models import Estimate
from apps.invoicing.models import Invoice
from apps.jobs.models import Job


class CollisionRecoveryTest(TestCase):
    """generate_next_number must advance past existing rows to handle
    counters that have drifted out of sync with the table (e.g. after a
    fixture reload that reset the counter but kept the data)."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-PREEXIST',
        )

    def test_estimate_skips_single_collision(self):
        year = datetime.now().year
        Estimate.objects.create(
            job=self.job, estimate_number=f'EST-{year}-0001',
            status=Estimate.STATUS_DRAFT,
        )
        # Counter still at 0; next would be 0001 which collides → service advances.
        result = NumberGenerationService.generate_next_number('estimate')
        self.assertEqual(result, f'EST-{year}-0002')
        counter = Configuration.objects.get(key='estimate_counter')
        self.assertEqual(counter.value, '2')

    def test_estimate_skips_multiple_collisions(self):
        year = datetime.now().year
        # Create three pre-existing drafts on three different jobs (one-draft-per-job)
        for i, num in enumerate(['0001', '0002', '0003'], start=2):
            other_job = Job.objects.create(
                contact=self.contact, status=Job.STATUS_DRAFT,
                job_number=f'JOB-COLL-{i}',
            )
            Estimate.objects.create(
                job=other_job, estimate_number=f'EST-{year}-{num}',
                status=Estimate.STATUS_DRAFT,
            )
        result = NumberGenerationService.generate_next_number('estimate')
        self.assertEqual(result, f'EST-{year}-0004')
        counter = Configuration.objects.get(key='estimate_counter')
        self.assertEqual(counter.value, '4')

    def test_invoice_skips_collision(self):
        year = datetime.now().year
        Invoice.objects.create(
            job=self.job, invoice_number=f'INV-{year}-0001',
            status=Invoice.STATUS_OPEN,
        )
        result = NumberGenerationService.generate_next_number('invoice')
        self.assertEqual(result, f'INV-{year}-0002')

    def test_no_collision_returns_next_normally(self):
        """Sanity: when there's no collision, behavior is unchanged."""
        year = datetime.now().year
        result = NumberGenerationService.generate_next_number('estimate')
        self.assertEqual(result, f'EST-{year}-0001')
        counter = Configuration.objects.get(key='estimate_counter')
        self.assertEqual(counter.value, '1')
