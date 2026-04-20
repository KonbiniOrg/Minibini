from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.estimates.models import EstWorksheet
from apps.inventory.models import Material, PlanMaterial
from apps.jobs.models import Job


class MaterialComputeAmountTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Materials', is_active=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.ws = EstWorksheet.objects.create(job=self.job)

    def test_material_compute_amount(self):
        m = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('3'),
            sell_price=Decimal('10.50'), accounting_category=self.cat,
        )
        self.assertEqual(m.compute_amount(), Decimal('31.50'))

    def test_plan_material_compute_amount(self):
        pm = PlanMaterial.objects.create(
            est_worksheet=self.ws, description='steel', quantity=Decimal('2'),
            sell_price=Decimal('5.00'), accounting_category=self.cat,
        )
        self.assertEqual(pm.compute_amount(), Decimal('10.00'))

    def test_compute_amount_ignores_active_modifiers(self):
        m = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('1'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )
        # Materials don't have modifiers; the parameter is accepted for uniform interface.
        self.assertEqual(m.compute_amount(active_modifiers=['rush']), Decimal('5'))
