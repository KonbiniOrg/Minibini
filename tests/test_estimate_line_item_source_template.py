from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import Estimate, EstimateLineItem, ServiceItem
from apps.jobs.models import Job, RateScheme


class EstimateLineItemSourceTemplateTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.category = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='j@example.com', mobile_number='555-0001',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.estimate = Estimate.objects.create(job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-0001')
        self.scheme = RateScheme.objects.create(
            name='S-elist', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.category,
        )
        self.template = ServiceItem.objects.create(
            template_name='Setup',
            rate_scheme=self.scheme,
        )

    def test_source_template_can_be_null(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate,
            qty=Decimal('1'), units='each', price=Decimal('100.00'),
            description='manual', accounting_category=self.category,
        )
        self.assertIsNone(li.source_template)

    def test_source_template_fk_to_service_item(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate,
            qty=Decimal('1'), units='hours', price=Decimal('95.00'),
            description='setup', accounting_category=self.category,
            source_template=self.template,
        )
        li.refresh_from_db()
        self.assertEqual(li.source_template, self.template)

    def test_template_deletion_sets_null(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate,
            qty=Decimal('1'), units='hours', price=Decimal('95.00'),
            description='setup', accounting_category=self.category,
            source_template=self.template,
        )
        self.template.delete()
        li.refresh_from_db()
        self.assertIsNone(li.source_template)
