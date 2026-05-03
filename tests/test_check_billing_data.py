from io import StringIO
from decimal import Decimal
from django.core.management import call_command
from tests.base import BaseTestCase


class CheckBillingDataTest(BaseTestCase):
    fixtures = []

    def test_clean_db_reports_all_clear(self):
        out = StringIO()
        call_command('check_billing_data', stdout=out)
        text = out.getvalue()
        self.assertIn('All clear', text)

    def test_reports_ratescheme_without_ac(self):
        from apps.jobs.models import RateScheme
        # Bypass clean() because that's the very condition we're checking.
        # Use objects.create with full_clean off — but RateScheme.save() now
        # invokes full_clean (per A4), so we use bulk_create to skip it.
        RateScheme.objects.bulk_create([RateScheme(
            name='NoAC', algorithm='flat_fee', rate=Decimal('1'),
            unit_label='ea',
        )])
        out = StringIO()
        call_command('check_billing_data', stdout=out)
        text = out.getvalue()
        self.assertIn('RateScheme', text)
        self.assertIn('without accounting_category', text)

    def test_reports_planTask_without_scheme(self):
        from apps.jobs.models import PlanTask, Job
        from apps.estimates.models import EstWorksheet
        from apps.contacts.models import Business, Contact
        contact = Contact.objects.create(
            first_name='F', last_name='L', email='f-cbd@l.test',
        )
        biz = Business.objects.create(
            business_name='B-cbd', default_contact=contact,
        )
        contact.business = biz
        contact.save()
        job = Job.objects.create(job_number='J-cbd', contact=contact)
        ws = EstWorksheet.objects.create(job=job)
        # Direct create, bypassing service-layer guards
        PlanTask.objects.create(est_worksheet=ws, name='no scheme')
        out = StringIO()
        call_command('check_billing_data', stdout=out)
        self.assertIn('PlanTask', out.getvalue())
