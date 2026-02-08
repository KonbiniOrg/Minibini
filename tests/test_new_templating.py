"""
Tests for the new simplified templating system.
Tests TemplateBundle, TaskTemplate.line_item_type, and TemplateTaskAssociation mapping.
"""
from decimal import Decimal
from django.test import TestCase
from django.db.models import ProtectedError
from django.core.exceptions import ValidationError

from apps.jobs.models import TaskTemplate, WorkOrderTemplate, TemplateTaskAssociation, TemplateBundle
from apps.core.models import LineItemType
from django.db import IntegrityError


class TestTaskTemplateLineItemType(TestCase):
    """Tests for TaskTemplate.line_item_type field"""

    def test_task_template_can_have_line_item_type(self):
        """TaskTemplate can have a line_item_type"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        tt = TaskTemplate.objects.create(
            template_name="Sand Surface",
            line_item_type=lit
        )
        self.assertEqual(tt.line_item_type, lit)

    def test_task_template_line_item_type_protected(self):
        """Cannot delete LineItemType if TaskTemplate references it"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        TaskTemplate.objects.create(template_name="Sand", line_item_type=lit)

        with self.assertRaises(ProtectedError):
            lit.delete()

    def test_task_template_line_item_type_nullable(self):
        """TaskTemplate.line_item_type can be null (for migration)"""
        tt = TaskTemplate.objects.create(
            template_name="Sand Surface",
            line_item_type=None
        )
        self.assertIsNone(tt.line_item_type)
