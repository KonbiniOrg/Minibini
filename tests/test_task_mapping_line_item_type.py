"""
Tests for TaskMapping.output_line_item_type field - TDD approach.
Testing linking TaskMapping to LineItemType for automatic line item type assignment.
"""
from django.test import TestCase
from django.db.models import ProtectedError
from apps.core.models import LineItemType
from apps.jobs.models import TaskMapping


class TaskMappingLineItemTypeTest(TestCase):
    """Tests for output_line_item_type field on TaskMapping model."""

    @classmethod
    def setUpTestData(cls):
        """Set up test data."""
        cls.service_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )
        cls.material_type, _ = LineItemType.objects.get_or_create(
            code='MAT',
            defaults={'name': 'Material', 'taxable': True}
        )

    def test_output_line_item_type_null_by_default(self):
        """Test that output_line_item_type is null by default."""
        mapping = TaskMapping.objects.create(
            task_type_id='test_mapping',
            step_type='labor',
            mapping_strategy='direct'
        )

        self.assertIsNone(mapping.output_line_item_type)

    def test_output_line_item_type_can_be_assigned(self):
        """Test that output_line_item_type can be assigned."""
        mapping = TaskMapping.objects.create(
            task_type_id='service_mapping',
            step_type='labor',
            mapping_strategy='direct',
            output_line_item_type=self.service_type
        )

        self.assertEqual(mapping.output_line_item_type, self.service_type)

    def test_output_line_item_type_can_be_updated(self):
        """Test that output_line_item_type can be updated."""
        mapping = TaskMapping.objects.create(
            task_type_id='updateable_mapping',
            step_type='labor',
            mapping_strategy='direct',
            output_line_item_type=self.service_type
        )

        mapping.output_line_item_type = self.material_type
        mapping.save()

        mapping.refresh_from_db()
        self.assertEqual(mapping.output_line_item_type, self.material_type)

    def test_output_line_item_type_protect_on_delete(self):
        """Test that deleting a LineItemType is protected if TaskMappings reference it."""
        test_type = LineItemType.objects.create(
            code='TST',
            name='Test Type'
        )

        TaskMapping.objects.create(
            task_type_id='protected_mapping',
            step_type='labor',
            mapping_strategy='direct',
            output_line_item_type=test_type
        )

        with self.assertRaises(ProtectedError):
            test_type.delete()
