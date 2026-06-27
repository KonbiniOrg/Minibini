"""
Tests for the simplified templating system.
Tests TemplateTaskAssociation. (ServiceItem.accounting_category was
dropped in B6; the effective category is now derived from rate_scheme.)
"""
from decimal import Decimal
from django.test import TestCase

from apps.jobs.models import RateScheme
from apps.estimates.models import ServiceItem, WorkTemplate, TemplateTaskAssociation
from apps.core.models import AccountingCategory
from django.db import IntegrityError


def _make_scheme(suffix, ac):
    return RateScheme.objects.create(
        name=f'S-nt-{suffix}', algorithm=RateScheme.FLAT_FEE,
        rate=Decimal('1'), unit_label='ea', accounting_category=ac,
    )


class TestTemplateTaskAssociation(TestCase):
    """Tests for TemplateTaskAssociation"""

    def test_association_direct(self):
        """Association can be created linking a task template to a work template"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        scheme = _make_scheme('ad', lit)
        wot = WorkTemplate.objects.create(template_name="Cabinet Refinish")
        tt = ServiceItem.objects.create(
            template_name="Sand",
            rate_scheme=scheme,
        )

        assoc = TemplateTaskAssociation.objects.create(
            work_template=wot,
            service_item=tt,
            est_qty=1,
        )

        self.assertEqual(assoc.work_template, wot)
        self.assertEqual(assoc.service_item, tt)
        self.assertEqual(assoc.est_qty, 1)

    def test_association_unique_per_template(self):
        """Each task template can only be associated once per work template"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        scheme = _make_scheme('aup', lit)
        wot = WorkTemplate.objects.create(template_name="Cabinet Refinish")
        tt = ServiceItem.objects.create(
            template_name="Sand",
            rate_scheme=scheme,
        )

        TemplateTaskAssociation.objects.create(work_template=wot, service_item=tt, est_qty=1)

        with self.assertRaises(IntegrityError):
            TemplateTaskAssociation.objects.create(work_template=wot, service_item=tt, est_qty=2)

    def test_flat_fee_template_needs_no_price_in_modifiers(self):
        """A flat-fee ServiceItem with empty default_active_modifiers validates cleanly."""
        ac = AccountingCategory.objects.create(name="Setup AC", code="STP")
        svc = RateScheme.objects.create(
            name='Setup fee', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('100.00'), unit_label='job',
            accounting_category=ac,
        )
        tt = ServiceItem(
            template_name='Setup', rate_scheme=svc,
            default_active_modifiers=[],
        )
        tt.full_clean()  # must not raise
