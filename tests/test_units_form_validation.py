# tests/test_units_form_validation.py
from tests.base import BaseTestCase
from apps.estimates.forms import TaskTemplateForm, ManualLineItemForm
from apps.jobs.forms import TaskEditForm
from apps.purchasing.forms import POManualLineItemForm
from apps.core.models import AccountingCategory


class UnitsDropdownFormTest(BaseTestCase):

    # NOTE: TaskTemplateForm no longer exposes a 'units' field — TaskTemplate
    # dropped 'units' and 'rate' in B6. The previous units widget/validation
    # tests for this form have been removed accordingly.

    def test_task_edit_form_has_name_field(self):
        """TaskEditForm (PlanTask) no longer has units; verify name field is present."""
        form = TaskEditForm()
        self.assertIn('name', form.fields)
        self.assertNotIn('units', form.fields)

    def test_manual_line_item_form_has_select_widget(self):
        form = ManualLineItemForm()
        widget = form.fields['units'].widget
        self.assertEqual(widget.__class__.__name__, 'Select')

    def test_po_manual_form_has_select_widget(self):
        form = POManualLineItemForm()
        widget = form.fields['units'].widget
        self.assertEqual(widget.__class__.__name__, 'Select')
