from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.jobs.models import Job, Task
from apps.inventory.models import Material, PriceListItem
from apps.core.models import AccountingCategory


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
        self.assertEqual(m.consumption_state, 'na')
        self.assertEqual(m.restocked_qty, Decimal('0.00'))

    def test_material_effective_qty(self):
        m = Material.objects.create(
            task=self.task, job=self.job,
            description='x', quantity=Decimal('5.00'),
        )
        m.restocked_qty = Decimal('2.00')
        m.save()
        self.assertEqual(m.effective_qty, Decimal('3.00'))
