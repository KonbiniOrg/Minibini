from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import Estimate, EstimateLineItem, ServiceItem
from apps.jobs.models import Job, RateScheme


class DeferredServiceBase(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')

        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('40'), unit_label='hour', accounting_category=self.cat,
        )
        self.service_item = ServiceItem.objects.create(
            template_name='CAM coding', description='tmpl desc',
            rate_scheme=self.scheme, default_active_modifiers=[],
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_DRAFT,
        )


class ServiceItemFieldTest(DeferredServiceBase):
    def test_line_can_carry_service_item_and_defaults_null(self):
        bare = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='x',
            qty=Decimal('1'), price=Decimal('0'), accounting_category=self.cat,
        )
        self.assertIsNone(bare.service_item)
        line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='CAM coding',
            qty=Decimal('1'), price=Decimal('40'), accounting_category=self.cat,
            service_item=self.service_item,
        )
        line.refresh_from_db()
        self.assertEqual(line.service_item_id, self.service_item.pk)
