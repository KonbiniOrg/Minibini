"""
Tests for the new simplified templating system.
Tests TemplateBundle, TaskTemplate.accounting_category, and TemplateTaskAssociation mapping.
"""
from decimal import Decimal
from django.test import TestCase
from django.db.models import ProtectedError
from django.core.exceptions import ValidationError

from apps.jobs.models import PlanBundle, Job, PlanTask
from apps.estimates.models import TaskTemplate, WorkTemplate, TemplateTaskAssociation, TemplateBundle, EstWorksheet, Estimate, EstimateLineItem
from apps.core.models import AccountingCategory
from apps.contacts.models import Contact
from django.db import IntegrityError


class TestTaskTemplateAccountingCategory(TestCase):
    """Tests for TaskTemplate.accounting_category field"""

    def test_task_template_can_have_accounting_category(self):
        """TaskTemplate can have a accounting_category"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        tt = TaskTemplate.objects.create(
            template_name="Sand Surface",
            accounting_category=lit
        )
        self.assertEqual(tt.accounting_category, lit)

    def test_task_template_accounting_category_protected(self):
        """Cannot delete AccountingCategory if TaskTemplate references it"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        TaskTemplate.objects.create(template_name="Sand", accounting_category=lit)

        with self.assertRaises(ProtectedError):
            lit.delete()

    def test_task_template_accounting_category_nullable(self):
        """TaskTemplate.accounting_category can be null (for migration)"""
        tt = TaskTemplate.objects.create(
            template_name="Sand Surface",
            accounting_category=None
        )
        self.assertIsNone(tt.accounting_category)


class TestTemplateBundle(TestCase):
    """Tests for TemplateBundle model"""

    def test_create_template_bundle(self):
        """Can create a TemplateBundle attached to WorkTemplate"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        wot = WorkTemplate.objects.create(template_name="Cabinet Refinish")

        bundle = TemplateBundle.objects.create(
            work_template=wot,
            name="Prep Work",
            accounting_category=lit
        )

        self.assertEqual(bundle.work_template, wot)
        self.assertEqual(bundle.name, "Prep Work")
        self.assertEqual(bundle.accounting_category, lit)

    def test_bundle_name_unique_per_template(self):
        """Bundle names must be unique within a WorkTemplate"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        wot = WorkTemplate.objects.create(template_name="Cabinet Refinish")

        TemplateBundle.objects.create(work_template=wot, name="Prep", accounting_category=lit)

        with self.assertRaises(IntegrityError):
            TemplateBundle.objects.create(work_template=wot, name="Prep", accounting_category=lit)

    def test_bundle_cascades_on_template_delete(self):
        """Deleting WorkTemplate deletes its bundles"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        wot = WorkTemplate.objects.create(template_name="Cabinet Refinish")
        TemplateBundle.objects.create(work_template=wot, name="Prep", accounting_category=lit)

        wot.delete()
        self.assertEqual(TemplateBundle.objects.count(), 0)

    def test_bundle_accounting_category_protected(self):
        """Cannot delete AccountingCategory if TemplateBundle references it"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        wot = WorkTemplate.objects.create(template_name="Cabinet Refinish")
        TemplateBundle.objects.create(work_template=wot, name="Prep", accounting_category=lit)

        with self.assertRaises(ProtectedError):
            lit.delete()


class TestTemplateTaskAssociationMapping(TestCase):
    """Tests for TemplateTaskAssociation mapping fields"""

    def test_association_direct_mapping(self):
        """Association can have direct mapping strategy"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        wot = WorkTemplate.objects.create(template_name="Cabinet Refinish")
        tt = TaskTemplate.objects.create(template_name="Sand", accounting_category=lit)

        assoc = TemplateTaskAssociation.objects.create(
            work_template=wot,
            task_template=tt,
            est_qty=1,
            mapping_strategy='direct'
        )

        self.assertEqual(assoc.mapping_strategy, 'direct')
        self.assertIsNone(assoc.bundle)

    def test_association_bundle_mapping(self):
        """Association can point to a bundle"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        wot = WorkTemplate.objects.create(template_name="Cabinet Refinish")
        tt = TaskTemplate.objects.create(template_name="Sand", accounting_category=lit)
        bundle = TemplateBundle.objects.create(work_template=wot, name="Prep", accounting_category=lit)

        assoc = TemplateTaskAssociation.objects.create(
            work_template=wot,
            task_template=tt,
            est_qty=1,
            mapping_strategy='bundle',
            bundle=bundle
        )

        self.assertEqual(assoc.mapping_strategy, 'bundle')
        self.assertEqual(assoc.bundle, bundle)

    def test_bundle_must_belong_to_same_template(self):
        """Cannot assign a bundle from a different WorkTemplate"""
        lit = AccountingCategory.objects.create(name="Labor", code="LBR")
        wot1 = WorkTemplate.objects.create(template_name="Cabinet Refinish")
        wot2 = WorkTemplate.objects.create(template_name="Table Refinish")
        tt = TaskTemplate.objects.create(template_name="Sand", accounting_category=lit)
        bundle = TemplateBundle.objects.create(work_template=wot2, name="Prep", accounting_category=lit)

        assoc = TemplateTaskAssociation(
            work_template=wot1,
            task_template=tt,
            est_qty=1,
            mapping_strategy='bundle',
            bundle=bundle  # Wrong template!
        )

        with self.assertRaises(ValidationError):
            assoc.full_clean()
