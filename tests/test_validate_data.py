import unittest
from decimal import Decimal
from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from apps.core.models import AccountingCategory
from apps.jobs.models import RateScheme, Job, Task
from apps.contacts.models import Contact


class ValidateDataRateSchemeTest(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(name='Svc', code='SVC')
        self.contact = Contact.objects.create(first_name='Test', last_name='User')

    def _run(self):
        out = StringIO()
        call_command('validate_data', stdout=out, stderr=out)
        return out.getvalue()

    def _make_sp(self, name='Sp', rate=Decimal('10.00'), algorithm=None):
        if algorithm is None:
            algorithm = RateScheme.ENTERED_QTY
        return RateScheme.objects.create(
            name=name, algorithm=algorithm,
            rate=rate, unit_label='each', accounting_category=self.ac,
        )

    def _make_job(self, number='J-VDT-001'):
        return Job.objects.create(
            job_number=number, name='Test Job', contact=self.contact,
        )

    # ── Flat-fee rate checks ──────────────────────────────────────

    @unittest.skip(
        "flat_fee removed; flat-fee rate check dropped from validate_data — "
        "fixed charges are the Fee atom"
    )
    def test_flags_zero_rate_flat_fee(self):
        pass

    @unittest.skip(
        "flat_fee removed; flat-fee rate check dropped from validate_data — "
        "fixed charges are the Fee atom"
    )
    def test_flags_negative_rate_flat_fee(self):
        pass

    @unittest.skip(
        "flat_fee removed; flat-fee rate check dropped from validate_data — "
        "fixed charges are the Fee atom"
    )
    def test_valid_flat_fee_not_flagged(self):
        pass

    # ── active_modifiers dict-shape checks ───────────────────────

    def test_flags_dict_active_modifiers_on_task(self):
        sp = self._make_sp(name='Sp-task')
        job = self._make_job('J-VDT-002')
        # Bypass full_clean to force a dict into the JSONField
        Task.objects.filter(pk=Task.objects.create(
            name='Bad task', job=job, rate_scheme=sp,
            active_modifiers=[],
        ).pk).update(active_modifiers={'key': 'val'})
        output = self._run()
        self.assertIn('active_modifiers', output.lower())

    def test_flags_dict_default_active_modifiers_on_service_item(self):
        from apps.estimates.models import ServiceItem
        sp = self._make_sp(name='Sp-tt')
        tt = ServiceItem.objects.create(
            template_name='Bad Template',
            rate_scheme=sp,
            default_active_modifiers=[],
        )
        ServiceItem.objects.filter(pk=tt.pk).update(default_active_modifiers={'key': 'val'})
        output = self._run()
        self.assertIn('default_active_modifiers', output.lower())

    # ── Negative rate / percentage checks ───────────────────────

    def test_negative_rate_only_allowed_for_percentage(self):
        """A percentage RateScheme with a negative rate (discount) is OK."""
        RateScheme.objects.create(
            name='disc', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('-10'), unit_label='%', accounting_category=self.ac,
        )
        output = self._run()
        self.assertNotIn('disc', output)

    def test_negative_rate_non_percentage_is_flagged(self):
        """A non-percentage RateScheme with a negative rate is an error."""
        RateScheme.objects.create(
            name='bad-elapsed', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('-5.00'), unit_label='hr', accounting_category=self.ac,
        )
        output = self._run()
        self.assertIn('bad-elapsed', output)
        self.assertIn('negative rate', output)

    def test_valid_list_active_modifiers_not_flagged(self):
        sp = self._make_sp(name='Sp-list')
        job = self._make_job('J-VDT-004')
        Task.objects.create(
            name='Good task', job=job, rate_scheme=sp,
            active_modifiers=['mod1'],
        )
        output = self._run()
        self.assertNotIn('active_modifiers', output.lower())
