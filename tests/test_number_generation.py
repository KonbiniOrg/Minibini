from datetime import datetime
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import Configuration, AppState
from apps.core.services import NumberGenerationService
from apps.invoicing.models import Invoice
from apps.jobs.models import Job


class CollisionRecoveryTest(TestCase):
    """generate_next_number must advance past existing rows to handle
    counters that have drifted out of sync with the table (e.g. after a
    fixture reload that reset the counter but kept the data).

    (Estimates are not numbered via this service — they derive {job}-{ver} —
    so only job/invoice/po use generate_next_number; patterns live in
    Configuration, counters in AppState.)"""

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-PREEXIST',
        )

    def test_invoice_skips_single_collision(self):
        year = datetime.now().year
        Invoice.objects.create(
            job=self.job, invoice_number=f'INV-{year}-0001',
            status=Invoice.STATUS_OPEN,
        )
        # Counter still at 0; next would be 0001 which collides → service advances.
        result = NumberGenerationService.generate_next_number('invoice')
        self.assertEqual(result, f'INV-{year}-0002')
        counter = AppState.objects.get(key='invoice_counter')
        self.assertEqual(counter.value, '2')

    def test_invoice_skips_multiple_collisions(self):
        year = datetime.now().year
        for num in ['0001', '0002', '0003']:
            Invoice.objects.create(
                job=self.job, invoice_number=f'INV-{year}-{num}',
                status=Invoice.STATUS_OPEN,
            )
        result = NumberGenerationService.generate_next_number('invoice')
        self.assertEqual(result, f'INV-{year}-0004')
        counter = AppState.objects.get(key='invoice_counter')
        self.assertEqual(counter.value, '4')

    def test_no_collision_returns_next_normally(self):
        """Sanity: when there's no collision, behavior is unchanged."""
        year = datetime.now().year
        result = NumberGenerationService.generate_next_number('invoice')
        self.assertEqual(result, f'INV-{year}-0001')
        counter = AppState.objects.get(key='invoice_counter')
        self.assertEqual(counter.value, '1')

    def test_counter_lives_in_appstate_not_configuration(self):
        """The counter is machine state — it must not be a Configuration row."""
        NumberGenerationService.generate_next_number('job')
        self.assertTrue(AppState.objects.filter(key='job_counter').exists())
        self.assertFalse(Configuration.objects.filter(key='job_counter').exists())
