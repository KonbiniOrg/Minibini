"""
Tests for the simplified templating system.
Tests TaskTemplate.accounting_category and TemplateTaskAssociation.
"""
from decimal import Decimal
from django.test import TestCase
from django.db.models import ProtectedError
from django.core.exceptions import ValidationError

from apps.jobs.models import Job, PlanTask, RateScheme
from apps.estimates.models import TaskTemplate, WorkTemplate, TemplateTaskAssociation, EstWorksheet, Estimate, EstimateLineItem
from apps.core.models import AccountingCategory
from apps.contacts.models import Contact
from django.db import IntegrityError


def _make_scheme(suffix, ac):
    return RateScheme.objects.create(
        name=f'S-nt-{suffix}', algorithm=RateScheme.FLAT_FEE,
        rate=Decimal('1'), unit_label='ea', accounting_category=ac,
    )


class TestTaskTemplateAccountingCategory(TestCase):
    """Tests for TaskTemplate.accounting_category field"""

    def test_task_template_can_have_accounting_category(self):
        """TaskTemplate can have a accounting_category"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        scheme = _make_scheme('hac', lit)
        tt = TaskTemplate.objects.create(
            template_name="Sand Surface",
            accounting_category=lit,
            rate_scheme=scheme, default_billable_qty=Decimal('1.00'),
        )
        self.assertEqual(tt.accounting_category, lit)

    def test_task_template_accounting_category_protected(self):
        """Cannot delete AccountingCategory if TaskTemplate references it"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        ac_other = AccountingCategory.objects.create(name="Other", code="OTH")
        scheme = _make_scheme('prot', ac_other)
        TaskTemplate.objects.create(
            template_name="Sand", accounting_category=lit,
            rate_scheme=scheme, default_billable_qty=Decimal('1.00'),
        )

        with self.assertRaises(ProtectedError):
            lit.delete()

    def test_task_template_accounting_category_nullable(self):
        """TaskTemplate.accounting_category can be null (for migration)"""
        ac = AccountingCategory.objects.create(name="Other", code="OTH-N")
        scheme = _make_scheme('null', ac)
        tt = TaskTemplate.objects.create(
            template_name="Sand Surface",
            accounting_category=None,
            rate_scheme=scheme, default_billable_qty=Decimal('1.00'),
        )
        self.assertIsNone(tt.accounting_category)


class TestTemplateTaskAssociation(TestCase):
    """Tests for TemplateTaskAssociation"""

    def test_association_direct(self):
        """Association can be created linking a task template to a work template"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        scheme = _make_scheme('ad', lit)
        wot = WorkTemplate.objects.create(template_name="Cabinet Refinish")
        tt = TaskTemplate.objects.create(
            template_name="Sand", accounting_category=lit,
            rate_scheme=scheme, default_billable_qty=Decimal('1.00'),
        )

        assoc = TemplateTaskAssociation.objects.create(
            work_template=wot,
            task_template=tt,
            est_qty=1,
        )

        self.assertEqual(assoc.work_template, wot)
        self.assertEqual(assoc.task_template, tt)
        self.assertEqual(assoc.est_qty, 1)

    def test_association_unique_per_template(self):
        """Each task template can only be associated once per work template"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        scheme = _make_scheme('aup', lit)
        wot = WorkTemplate.objects.create(template_name="Cabinet Refinish")
        tt = TaskTemplate.objects.create(
            template_name="Sand", accounting_category=lit,
            rate_scheme=scheme, default_billable_qty=Decimal('1.00'),
        )

        TemplateTaskAssociation.objects.create(work_template=wot, task_template=tt, est_qty=1)

        with self.assertRaises(IntegrityError):
            TemplateTaskAssociation.objects.create(work_template=wot, task_template=tt, est_qty=2)
