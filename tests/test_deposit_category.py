from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.models import AccountingCategory
from apps.core.services import ConfigurationService


class DepositCategoryInvariantTest(TestCase):
    def test_is_deposit_requires_non_taxable(self):
        cat = AccountingCategory(code='DEP', name='Deposits',
                                 taxable=True, is_deposit=True)
        with self.assertRaises(ValidationError) as ctx:
            cat.full_clean()
        self.assertIn('is_deposit', ctx.exception.message_dict)

    def test_non_taxable_deposit_category_validates(self):
        cat = AccountingCategory(code='DEP', name='Deposits',
                                 taxable=False, is_deposit=True)
        cat.full_clean()  # must not raise

    def test_is_referenced_false_when_unused(self):
        cat = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        self.assertFalse(cat.is_referenced())

    def test_is_referenced_true_via_rate_scheme(self):
        from decimal import Decimal
        from apps.jobs.models import RateScheme
        cat = AccountingCategory.objects.create(
            code='SVC2', name='Service2', taxable=True)
        RateScheme.objects.create(
            name='Hourly-dep', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hour',
            accounting_category=cat)
        self.assertTrue(cat.is_referenced())

    def test_is_referenced_true_via_estimate_line_adjustment_target(self):
        """A category used ONLY as an adjustment_target_categories entry
        (a hidden related_name='+' M2M) must still count as referenced —
        the freeze invariant has to cover it too."""
        from decimal import Decimal
        from apps.contacts.models import Contact
        from apps.jobs.models import Job
        from apps.estimates.models import Estimate, EstimateLineItem

        cat = AccountingCategory.objects.create(
            code='ADJTGT', name='Adj Target', taxable=True)
        other_cat = AccountingCategory.objects.create(
            code='ADJOTH', name='Adj Other', taxable=True)
        contact = Contact.objects.create(first_name='Adj', last_name='Target')
        job = Job.objects.create(job_number='ADJ-DEP-1', contact=contact)
        est = Estimate.objects.create(
            job=job, estimate_number='EST-ADJ-DEP-1', version=1,
            status=Estimate.STATUS_DRAFT)
        line = EstimateLineItem.objects.create(
            estimate=est, line_number=1,
            qty=Decimal('1'), price=Decimal('0.00'),
            accounting_category=other_cat)
        line.adjustment_target_categories.set([cat.pk])

        self.assertTrue(cat.is_referenced())
        with self.assertRaises(ValidationError):
            ConfigurationService.update_accounting_category(
                cat.pk, taxable=False)


class DepositCategoryFreezeTest(TestCase):
    def setUp(self):
        from decimal import Decimal
        from apps.jobs.models import RateScheme
        self.cat = AccountingCategory.objects.create(
            code='SVC3', name='Service3', taxable=True)
        RateScheme.objects.create(
            name='Hourly-frz', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hour',
            accounting_category=self.cat)

    def test_taxable_frozen_once_referenced(self):
        with self.assertRaises(ValidationError):
            ConfigurationService.update_accounting_category(
                self.cat.pk, taxable=False)

    def test_is_deposit_frozen_once_referenced(self):
        with self.assertRaises(ValidationError):
            ConfigurationService.update_accounting_category(
                self.cat.pk, is_deposit=True)

    def test_name_editable_while_referenced(self):
        updated = ConfigurationService.update_accounting_category(
            self.cat.pk, name='Shop Service')
        self.assertEqual(updated.name, 'Shop Service')

    def test_taxable_editable_while_unreferenced(self):
        free = AccountingCategory.objects.create(
            code='FREE', name='Free', taxable=True)
        updated = ConfigurationService.update_accounting_category(
            free.pk, taxable=False, is_deposit=True)
        self.assertTrue(updated.is_deposit)

    def test_unchanged_frozen_values_pass_through(self):
        # Sending the same values (whole-form PATCH) must not trip the freeze.
        updated = ConfigurationService.update_accounting_category(
            self.cat.pk, taxable=True, is_deposit=False, name='Still Fine')
        self.assertEqual(updated.name, 'Still Fine')
