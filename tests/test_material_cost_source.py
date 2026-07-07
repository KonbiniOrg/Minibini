"""Material.cost_source — the single provenance enum (spec §cost_source)."""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.inventory.models import Material
from apps.jobs.models import Job


class CostSourceFieldTests(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='5')
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-0001')

    def test_defaults_null_and_accepts_choices(self):
        m = Material(job=self.job, description='x', quantity=Decimal('1'),
                     accounting_category=self.cat)
        m.save()
        self.assertIsNone(m.cost_source)
        for value in (Material.COST_SOURCE_ESTIMATED, Material.COST_SOURCE_ENTERED,
                      Material.COST_SOURCE_PO, Material.COST_SOURCE_EXPENSE,
                      Material.COST_SOURCE_CUSTOMER):
            m.cost_source = value
            m.save()
            m.refresh_from_db()
            self.assertEqual(m.cost_source, value)

    def test_is_customer_supplied_property(self):
        m = Material(job=self.job, description='x', quantity=Decimal('1'),
                     accounting_category=self.cat)
        m.save()
        self.assertFalse(m.is_customer_supplied)
        m.cost_source = Material.COST_SOURCE_CUSTOMER
        self.assertTrue(m.is_customer_supplied)
