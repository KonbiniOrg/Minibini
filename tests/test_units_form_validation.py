# tests/test_units_form_validation.py
from tests.base import BaseTestCase
from apps.estimates.forms import TaskTemplateForm, ManualLineItemForm
from apps.jobs.forms import TaskEditForm
from apps.purchasing.forms import POManualLineItemForm
from apps.core.models import AccountingCategory


class UnitsDropdownFormTest(BaseTestCase):

    def test_task_template_form_has_select_widget(self):
        form = TaskTemplateForm()
        widget = form.fields['units'].widget
        self.assertEqual(widget.__class__.__name__, 'Select')

    def test_task_template_form_valid_unit(self):
        cat = AccountingCategory.objects.first()
        form = TaskTemplateForm(data={
            'template_name': 'Test',
            'units': 'hours',
            'rate': '10.00',
            'accounting_category': cat.pk if cat else '',
        })
        self.assertTrue(form.is_valid(), form.errors)

    def test_task_template_form_invalid_unit(self):
        form = TaskTemplateForm(data={
            'template_name': 'Test',
            'units': 'invalid_xyz',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('units', form.errors)

    def test_task_edit_form_has_select_widget(self):
        form = TaskEditForm()
        widget = form.fields['units'].widget
        self.assertEqual(widget.__class__.__name__, 'Select')

    def test_manual_line_item_form_has_select_widget(self):
        form = ManualLineItemForm()
        widget = form.fields['units'].widget
        self.assertEqual(widget.__class__.__name__, 'Select')

    def test_po_manual_form_has_select_widget(self):
        form = POManualLineItemForm()
        widget = form.fields['units'].widget
        self.assertEqual(widget.__class__.__name__, 'Select')
