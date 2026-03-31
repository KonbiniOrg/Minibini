# Configurable Units Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace free-text `units` fields with a controlled vocabulary validated against a JSON list in Configuration.

**Architecture:** Units remain CharFields on models (no ForeignKeys/joins). A `units_list` Configuration entry stores the allowed values as a JSON array. Forms use `<select>` dropdowns, serializers validate against the list, and a shared helper in `apps/core/units.py` provides the lookup.

**Tech Stack:** Django 5.2, DRF, Svelte 5, MySQL

**Design spec:** `docs/designs/2026-03-30-configurable-units.md`

---

### Task 1: Core units helper module

**Files:**
- Create: `apps/core/units.py`
- Create: `tests/test_units.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_units.py
import json
from tests.base import BaseTestCase
from apps.core.models import Configuration
from apps.core.units import get_units_list, validate_unit


class GetUnitsListTest(BaseTestCase):

    def test_returns_list_from_config(self):
        result = get_units_list()
        self.assertIsInstance(result, list)
        self.assertEqual(result[0], 'none')

    def test_raises_if_config_missing(self):
        Configuration.objects.filter(key='units_list').delete()
        with self.assertRaises(Configuration.DoesNotExist):
            get_units_list()


class ValidateUnitTest(BaseTestCase):

    def test_valid_unit_passes(self):
        validate_unit('hours')  # should not raise

    def test_invalid_unit_raises(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            validate_unit('invalid_unit_xyz')

    def test_none_is_valid(self):
        validate_unit('none')  # should not raise
```

- [ ] **Step 2: Add `units_list` to the test fixture**

Add this entry to `fixtures/unit_test_data.json` after the `board_closed_retention_days` entry (after line 272):

```json
{
    "model": "core.configuration",
    "pk": "units_list",
    "fields": {
        "value": "[\"none\", \"hours\", \"ea\", \"sq ft\", \"ft\", \"yd\", \"m\", \"sheets\", \"pcs\", \"lbs\", \"kg\", \"gal\", \"qt\", \"L\", \"bd ft\", \"ln ft\"]"
    }
}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python manage.py test tests.test_units -v2`
Expected: FAIL — `apps.core.units` does not exist yet.

- [ ] **Step 4: Write the implementation**

```python
# apps/core/units.py
import json
from django.core.exceptions import ValidationError
from apps.core.models import Configuration


def get_units_list():
    """Load the allowed units list from Configuration.

    Returns a list of strings. Raises Configuration.DoesNotExist
    if the units_list key has not been set up.
    """
    config = Configuration.objects.get(key='units_list')
    return json.loads(config.value)


def validate_unit(value):
    """Validate that a units value is in the configured list."""
    allowed = get_units_list()
    if value not in allowed:
        raise ValidationError(
            f'"{value}" is not a configured unit.',
            code='invalid_unit',
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_units -v2`
Expected: All 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/core/units.py tests/test_units.py fixtures/unit_test_data.json
git commit -m "feat: add core units helper with get_units_list and validate_unit"
```

---

### Task 2: Model field migrations

**Files:**
- Modify: `apps/core/models.py:205` (BaseLineItem.units)
- Modify: `apps/jobs/models.py:188` (Task.units)
- Modify: `apps/estimates/models.py:444` (TaskTemplate.units)
- Modify: `apps/inventory/models.py:38` (PriceListItem.units)
- Create: migration files via `makemigrations`
- Create: `tests/test_units_model_defaults.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_units_model_defaults.py
from tests.base import BaseTestCase
from apps.jobs.models import Task, Job
from apps.estimates.models import TaskTemplate
from apps.inventory.models import PriceListItem
from apps.invoicing.models import InvoiceLineItem


class UnitsDefaultTest(BaseTestCase):

    def test_task_defaults_to_none(self):
        job = Job.objects.first()
        task = Task.objects.create(
            name='Test Task',
            work_order=job.work_orders.first() if job and job.work_orders.exists() else None,
        )
        self.assertEqual(task.units, 'none')

    def test_task_template_defaults_to_none(self):
        tt = TaskTemplate.objects.create(template_name='Test Template')
        self.assertEqual(tt.units, 'none')

    def test_price_list_item_defaults_to_none(self):
        pli = PriceListItem.objects.create(code='TEST-UNIT-PLI')
        self.assertEqual(pli.units, 'none')

    def test_line_item_defaults_to_none(self):
        """BaseLineItem default via InvoiceLineItem as a concrete subclass."""
        from apps.invoicing.models import Invoice
        job = Job.objects.first()
        if job:
            invoice = Invoice.objects.create(job=job)
            li = InvoiceLineItem.objects.create(invoice=invoice)
            self.assertEqual(li.units, 'none')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_units_model_defaults -v2`
Expected: FAIL — units defaults to `''` not `'none'`.

- [ ] **Step 3: Update model fields**

In `apps/core/models.py:205`, change:
```python
units = models.CharField(max_length=50, blank=True)
```
to:
```python
units = models.CharField(max_length=50, default='none')
```

In `apps/jobs/models.py:188`, change:
```python
units = models.CharField(max_length=50, blank=True)
```
to:
```python
units = models.CharField(max_length=50, default='none')
```

In `apps/estimates/models.py:444`, change:
```python
units = models.CharField(max_length=50, blank=True)
```
to:
```python
units = models.CharField(max_length=50, default='none')
```

In `apps/inventory/models.py:38`, change:
```python
units = models.CharField(max_length=50, blank=True)
```
to:
```python
units = models.CharField(max_length=50, default='none')
```

- [ ] **Step 4: Create migrations**

Run: `python manage.py makemigrations core jobs estimates inventory`

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_units_model_defaults -v2`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/core/models.py apps/jobs/models.py apps/estimates/models.py apps/inventory/models.py apps/*/migrations/ tests/test_units_model_defaults.py
git commit -m "feat: change units fields to default='none' instead of blank=True"
```

---

### Task 3: API endpoint for units list

**Files:**
- Modify: `apps/api/templates_config/views.py`
- Modify: `apps/api/urls.py`
- Create: `tests/test_units_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_units_api.py
import json
from django.urls import reverse
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import Configuration, User


class UnitsListEndpointTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin_user')
        self.client.force_authenticate(user=self.user)

    def test_get_units_list(self):
        response = self.client.get('/api/settings/units/')
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data, list)
        self.assertEqual(response.data[0], 'none')

    def test_get_units_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/settings/units/')
        self.assertEqual(response.status_code, 403)


class UnitsUpdateEndpointTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        # Need a user with can_manage_config permission
        self.admin = User.objects.get(username='admin_user')
        self.worker = User.objects.get(username='worker_user')

    def test_put_units_list(self):
        self.client.force_authenticate(user=self.admin)
        new_list = ['none', 'hours', 'ea', 'custom_unit']
        response = self.client.put('/api/settings/units/', new_list, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, new_list)
        # Verify persisted
        config = Configuration.objects.get(key='units_list')
        self.assertEqual(json.loads(config.value), new_list)

    def test_put_requires_none_first(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.put('/api/settings/units/', ['hours', 'ea'], format='json')
        self.assertEqual(response.status_code, 400)

    def test_put_rejects_empty_list(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.put('/api/settings/units/', [], format='json')
        self.assertEqual(response.status_code, 400)

    def test_put_rejects_duplicates(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.put('/api/settings/units/', ['none', 'hours', 'hours'], format='json')
        self.assertEqual(response.status_code, 400)

    def test_put_requires_can_manage_config(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.put('/api/settings/units/', ['none', 'hours'], format='json')
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_units_api -v2`
Expected: FAIL — 404 on `/api/settings/units/`.

- [ ] **Step 3: Write the units view**

Add to `apps/api/templates_config/views.py`, after the existing imports:

```python
import json
```

Add the view function after `settings_view`:

```python
@api_view(['GET', 'PUT'])
def units_view(request):
    if request.method == 'GET':
        if not request.user.is_authenticated:
            return Response(status=403)
        config = Configuration.objects.get(key='units_list')
        return Response(json.loads(config.value))

    # PUT — replace the units list
    if not request.user.has_perm('core.can_manage_config'):
        return Response(status=403)

    units = request.data
    if not isinstance(units, list) or len(units) == 0:
        return Response({'error': 'Units must be a non-empty list.'}, status=400)
    if units[0] != 'none':
        return Response({'error': '"none" must be the first entry.'}, status=400)
    if len(units) != len(set(units)):
        return Response({'error': 'Duplicate units are not allowed.'}, status=400)

    Configuration.objects.update_or_create(
        key='units_list',
        defaults={'value': json.dumps(units)},
    )
    return Response(units)
```

- [ ] **Step 4: Add the URL**

In `apps/api/urls.py`, add the import:

```python
from apps.api.templates_config.views import (
    WorkOrderTemplateViewSet, TaskTemplateViewSet,
    AccountingCategoryViewSet, settings_view, units_view,
)
```

Add the URL pattern in `urlpatterns` (after the `settings/` line):

```python
path('settings/units/', units_view, name='api-settings-units'),
```

**Important:** This must come BEFORE the `settings/` path, or Django will match `settings/` first. Move the new line above `path('settings/', settings_view, name='api-settings')`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test tests.test_units_api -v2`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/api/templates_config/views.py apps/api/urls.py tests/test_units_api.py
git commit -m "feat: add GET/PUT /api/settings/units/ endpoint"
```

---

### Task 4: Django form validation — units dropdown

**Files:**
- Modify: `apps/inventory/forms.py` (InventoryItemForm, PriceListItemForm)
- Modify: `apps/estimates/forms.py` (TaskTemplateForm, ManualLineItemForm)
- Modify: `apps/purchasing/forms.py` (POManualLineItemForm, BillLineItemForm)
- Modify: `apps/jobs/forms.py` (TaskEditForm)
- Create: `tests/test_units_form_validation.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_units_form_validation -v2`
Expected: FAIL — widgets are TextInput, not Select.

- [ ] **Step 3: Create a shared form mixin**

Add to `apps/core/units.py`:

```python
from django import forms


def units_choices():
    """Return units as Django form choices: list of (value, label) tuples."""
    return [(u, u) for u in get_units_list()]


class UnitsFieldMixin:
    """Mixin for ModelForms that have a 'units' field.
    Replaces the default CharField widget with a Select dropdown
    populated from the configured units list.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'units' in self.fields:
            self.fields['units'] = forms.ChoiceField(
                choices=units_choices(),
                initial='none',
            )
```

- [ ] **Step 4: Update TaskTemplateForm**

In `apps/estimates/forms.py`, add import at top:

```python
from apps.core.units import UnitsFieldMixin
```

Change `TaskTemplateForm` to use the mixin:

```python
class TaskTemplateForm(UnitsFieldMixin, forms.ModelForm):
    class Meta:
        model = TaskTemplate
        fields = ['template_name', 'description', 'units', 'rate', 'accounting_category']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'rate': forms.NumberInput(attrs={'step': '0.01', 'placeholder': '0.00'}),
        }
```

Remove the `'units': forms.TextInput(...)` entry from the `widgets` dict.

Change `ManualLineItemForm` similarly:

```python
class ManualLineItemForm(UnitsFieldMixin, forms.ModelForm):
    class Meta:
        model = EstimateLineItem
        fields = ['description', 'qty', 'units', 'price', 'accounting_category']
        widgets = {
            'qty': forms.NumberInput(attrs={'step': '0.01'}),
            'price': forms.NumberInput(attrs={'step': '0.01'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }
```

- [ ] **Step 5: Update TaskEditForm**

In `apps/jobs/forms.py`, add import:

```python
from apps.core.units import UnitsFieldMixin
```

Change:

```python
class TaskEditForm(UnitsFieldMixin, forms.ModelForm):
    class Meta:
        model = Task
        fields = ['name', 'description', 'units', 'rate', 'est_qty', 'accounting_category']
        widgets = {
            'est_qty': forms.NumberInput(attrs={'step': '0.01'}),
            'rate': forms.NumberInput(attrs={'step': '0.01'}),
        }
```

- [ ] **Step 6: Update POManualLineItemForm**

In `apps/purchasing/forms.py`, add import:

```python
from apps.core.units import UnitsFieldMixin
```

Change:

```python
class POManualLineItemForm(UnitsFieldMixin, forms.ModelForm):
    """Form for creating a manual PO line item (not linked to a Price List Item)"""
    class Meta:
        model = PurchaseOrderLineItem
        fields = ['description', 'qty', 'units', 'price', 'accounting_category']
        widgets = {
            'qty': forms.NumberInput(attrs={'step': '0.01'}),
            'price': forms.NumberInput(attrs={'step': '0.01'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            'price': 'Price',
            'accounting_category': 'Type',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['accounting_category'].queryset = AccountingCategory.objects.filter(is_active=True)
        self.fields['accounting_category'].required = True
```

- [ ] **Step 7: Update BillLineItemForm**

`BillLineItemForm` is a plain `forms.Form` (not ModelForm), so it needs the `units` field replaced directly. In `apps/purchasing/forms.py`, add to the existing import:

```python
from apps.core.units import units_choices
```

Replace the `units` field definition (lines 120-124):

```python
    units = forms.ChoiceField(
        choices=[],  # populated in __init__
        initial='none',
        label="Units",
    )
```

In `BillLineItemForm.__init__`, after `super().__init__(*args, **kwargs)` and the existing `price_list_item` queryset line, add:

```python
        self.fields['units'].choices = units_choices()
```

- [ ] **Step 8: Update InventoryItemForm**

In `apps/inventory/forms.py`, replace the entire top of the file. Remove the `UNIT_CHOICES` constant (lines 5-21). Add import:

```python
from apps.core.units import UnitsFieldMixin
```

Replace `InventoryItemForm` — remove `units_select` and `units_custom` fields, the `__init__` logic for units, and the `save` logic for units. The form becomes:

```python
class InventoryItemForm(UnitsFieldMixin, forms.ModelForm):
    """Form for adding and editing inventoried price list items."""

    class Meta:
        model = PriceListItem
        fields = [
            'code',
            'units',
            'description',
            'qty_on_hand',
            'purchase_price',
            'selling_price',
        ]

    def clean_code(self):
        code = self.cleaned_data['code']
        existing_query = PriceListItem.objects.filter(code=code, is_inventoried=True)
        if self.instance.pk:
            existing_query = existing_query.exclude(pk=self.instance.pk)
        if existing_query.exists():
            raise forms.ValidationError(f'Inventoried item with code "{code}" already exists.')
        return code

    def clean_purchase_price(self):
        purchase_price = self.cleaned_data['purchase_price']
        if purchase_price < 0:
            raise forms.ValidationError('Purchase price cannot be negative.')
        return purchase_price

    def clean_selling_price(self):
        selling_price = self.cleaned_data['selling_price']
        if selling_price < 0:
            raise forms.ValidationError('Selling price cannot be negative.')
        return selling_price

    def clean_qty_on_hand(self):
        qty_on_hand = self.cleaned_data['qty_on_hand']
        if qty_on_hand < 0:
            raise forms.ValidationError('Quantity on hand cannot be negative.')
        return qty_on_hand

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.is_inventoried = True
        if commit:
            instance.save()
        return instance
```

Also add `UnitsFieldMixin` to `PriceListItemForm`:

```python
class PriceListItemForm(UnitsFieldMixin, forms.ModelForm):
```

(The rest of PriceListItemForm stays the same.)

- [ ] **Step 9: Run tests to verify they pass**

Run: `python manage.py test tests.test_units_form_validation -v2`
Expected: All tests PASS.

- [ ] **Step 10: Run existing test suite to check for regressions**

Run: `python manage.py test -v2`
Expected: Existing tests may fail due to hardcoded unit strings no longer valid. Note which tests fail — they'll be fixed in Task 7.

- [ ] **Step 11: Commit**

```bash
git add apps/core/units.py apps/inventory/forms.py apps/estimates/forms.py apps/purchasing/forms.py apps/jobs/forms.py tests/test_units_form_validation.py
git commit -m "feat: replace free-text units inputs with validated select dropdowns"
```

---

### Task 5: DRF serializer validation

**Files:**
- Modify: `apps/api/estimates/serializers.py`
- Modify: `apps/api/invoicing/serializers.py`
- Modify: `apps/api/work_orders/serializers.py`
- Modify: `apps/api/inventory/serializers.py`
- Modify: `apps/api/purchasing/serializers.py`
- Modify: `apps/api/templates_config/serializers.py`
- Create: `tests/test_units_serializer_validation.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_units_serializer_validation.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job


class TaskSerializerUnitsValidationTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin_user')
        self.client.force_authenticate(user=self.user)

    def test_create_task_with_valid_unit(self):
        job = Job.objects.first()
        if not job:
            self.skipTest('No job in fixture')
        wo = job.work_orders.first()
        if not wo:
            self.skipTest('No work order in fixture')
        response = self.client.post(
            f'/api/work-orders/{wo.pk}/tasks/',
            {'name': 'Test Task', 'units': 'hours'},
            format='json',
        )
        self.assertIn(response.status_code, [200, 201])

    def test_create_task_with_invalid_unit(self):
        job = Job.objects.first()
        if not job:
            self.skipTest('No job in fixture')
        wo = job.work_orders.first()
        if not wo:
            self.skipTest('No work order in fixture')
        response = self.client.post(
            f'/api/work-orders/{wo.pk}/tasks/',
            {'name': 'Test Task', 'units': 'invalid_xyz'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_task_template_serializer_rejects_invalid_unit(self):
        response = self.client.post(
            '/api/task-templates/',
            {'template_name': 'Test', 'units': 'invalid_xyz'},
            format='json',
        )
        self.assertEqual(response.status_code, 400)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_units_serializer_validation -v2`
Expected: FAIL — invalid units currently accepted (status 200/201 instead of 400).

- [ ] **Step 3: Add units validation to serializers**

Add a shared serializer field in `apps/core/units.py`:

```python
from rest_framework import serializers as drf_serializers


class UnitsField(drf_serializers.ChoiceField):
    """DRF field that validates units against the configured list."""
    def __init__(self, **kwargs):
        kwargs.setdefault('default', 'none')
        super().__init__(choices=[], **kwargs)

    def _get_choices(self):
        try:
            return [(u, u) for u in get_units_list()]
        except Configuration.DoesNotExist:
            return []

    def _set_choices(self, choices):
        pass

    choices = property(_get_choices, _set_choices)
```

In each serializer file, add the import and override the `units` field:

**`apps/api/work_orders/serializers.py`:**
```python
from apps.core.units import UnitsField

class TaskSerializer(serializers.ModelSerializer):
    units = UnitsField()
    # ... rest unchanged
```

**`apps/api/estimates/serializers.py`:**
```python
from apps.core.units import UnitsField

class EstimateLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    # ... rest unchanged
```

**`apps/api/invoicing/serializers.py`:**
```python
from apps.core.units import UnitsField

class InvoiceLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    # ... rest unchanged
```

**`apps/api/inventory/serializers.py`:**
```python
from apps.core.units import UnitsField

class PriceListItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    # ... rest unchanged
```

**`apps/api/purchasing/serializers.py`:**
```python
from apps.core.units import UnitsField

class POLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    # ... rest unchanged

class BillLineItemSerializer(serializers.ModelSerializer):
    units = UnitsField()
    # ... rest unchanged
```

**`apps/api/templates_config/serializers.py`:**
```python
from apps.core.units import UnitsField

class TaskTemplateSerializer(serializers.ModelSerializer):
    units = UnitsField()
    # ... rest unchanged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_units_serializer_validation -v2`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/core/units.py apps/api/*/serializers.py tests/test_units_serializer_validation.py
git commit -m "feat: add DRF units validation to all serializers"
```

---

### Task 6: Replace hardcoded 'each' defaults in services

**Files:**
- Modify: `apps/estimates/services.py:714,739,764`
- Create: `tests/test_units_service_defaults.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_units_service_defaults.py
from decimal import Decimal
from tests.base import BaseTestCase
from apps.jobs.models import Job, Task, WorkOrder
from apps.estimates.models import EstWorksheet, Estimate
from apps.estimates.services import EstimateGenerationService
from apps.core.models import AccountingCategory


class EstimateGenerationUnitsDefaultTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.job = Job.objects.first()
        if not self.job:
            self.skipTest('No job in fixture')
        # Create a worksheet and task with no units set explicitly
        self.worksheet = EstWorksheet.objects.filter(job=self.job).first()
        if not self.worksheet:
            self.skipTest('No worksheet in fixture')

    def test_direct_task_line_item_uses_task_units(self):
        """When a task has units set, the line item should use those units."""
        task = self.worksheet.tasks.first()
        if not task:
            self.skipTest('No task in fixture')
        task.units = 'hours'
        task.save()
        # Generate estimate and check units
        service = EstimateGenerationService(self.worksheet)
        estimate = service.generate()
        line_items = estimate.line_items.filter(task=task)
        if line_items.exists():
            self.assertEqual(line_items.first().units, 'hours')

    def test_direct_task_line_item_defaults_to_none(self):
        """When a task has default units, the line item should use 'none'."""
        task = self.worksheet.tasks.first()
        if not task:
            self.skipTest('No task in fixture')
        task.units = 'none'
        task.save()
        service = EstimateGenerationService(self.worksheet)
        estimate = service.generate()
        line_items = estimate.line_items.filter(task=task)
        if line_items.exists():
            self.assertEqual(line_items.first().units, 'none')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_units_service_defaults -v2`
Expected: The default case fails — `'each'` instead of `'none'`.

- [ ] **Step 3: Update the service**

In `apps/estimates/services.py`:

Line 714, change:
```python
units=task.units or 'each',
```
to:
```python
units=task.units or 'none',
```

Line 739, change:
```python
units='each',
```
to:
```python
units='none',
```

Line 764, change:
```python
units='each',
```
to:
```python
units='none',
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test tests.test_units_service_defaults -v2`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/services.py tests/test_units_service_defaults.py
git commit -m "fix: replace hardcoded 'each' unit defaults with 'none'"
```

---

### Task 7: Update fixtures and existing tests

**Files:**
- Modify: `fixtures/unit_test_data.json`
- Modify: `fixtures/core_base_data.json`
- Modify: `fixtures/contacts_base_data.json`
- Modify: `fixtures/purchasing_data.json`
- Modify: `fixtures/webserver_test_data.json`
- Modify: `fixtures/email_workflow_test_data.json`
- Modify: All `fixtures/featuredata/*.json` files that have units values
- Modify: `fixtures/workorder_from_estimate.json`
- Modify: `fixtures/template_test_data.json`
- Modify: `fixtures/jobs_basic_data.json`
- Modify: `fixtures/invoicing_data.json`
- Modify: All test files with hardcoded unit strings

This is a large find-and-replace task. The goal: every `units` value in fixtures and tests must be a value from the configured units list: `["none", "hours", "ea", "sq ft", "ft", "yd", "m", "sheets", "pcs", "lbs", "kg", "gal", "qt", "L", "bd ft", "ln ft"]`.

- [ ] **Step 1: Map old values to new values**

| Old value | New value |
|---|---|
| `""` (empty) | `"none"` |
| `"each"` | `"ea"` |
| `"hour"` | `"hours"` |
| `"hrs"` | `"hours"` |
| `"sqft"` | `"sq ft"` |
| `"square_feet"` | `"sq ft"` |
| `"linear_feet"` | `"ln ft"` |
| `"linear feet"` | `"ln ft"` |
| `"sheet"` | `"sheets"` |
| `"piece"` | `"pcs"` |
| `"pieces"` | `"pcs"` |
| `"box"` | `"ea"` |
| `"outlets"` | `"ea"` |
| `"pallets"` | `"ea"` |
| `"board_foot"` | `"bd ft"` |
| `"lf"` | `"ln ft"` |
| `"sf"` | `"sq ft"` |

- [ ] **Step 2: Update all fixture files**

For each fixture file, find `"units":` entries and replace values using the mapping above. Also ensure every fixture file that has Configuration entries includes the `units_list` config entry.

- [ ] **Step 3: Update all test files**

Search across `tests/` for patterns like `units='...'` and `"units": "..."` and replace using the mapping above.

Run: `grep -rn "units=" tests/ | grep -v ".pyc"` to find all instances.

- [ ] **Step 4: Run the full test suite**

Run: `python manage.py test -v2`
Expected: All tests PASS. If any still fail due to unit string mismatches, fix them.

- [ ] **Step 5: Commit**

```bash
git add fixtures/ tests/
git commit -m "chore: normalize all unit strings to match configured units list"
```

---

### Task 8: Reusable Svelte UnitsSelect component

**Files:**
- Create: `frontend/src/components/UnitsSelect.svelte`
- Modify: `frontend/src/lib/api.js` (add `put` method)

- [ ] **Step 1: Add `put` to the API client**

In `frontend/src/lib/api.js`, add to the export:

```javascript
export const api = {
  get: (url) => request('GET', url),
  post: (url, data) => request('POST', url, data),
  put: (url, data) => request('PUT', url, data),
  patch: (url, data) => request('PATCH', url, data),
  delete: (url) => request('DELETE', url),
};
```

- [ ] **Step 2: Create the UnitsSelect component**

```svelte
<!-- frontend/src/components/UnitsSelect.svelte -->
<script>
  import { api } from '../lib/api.js';

  let {
    value = $bindable('none'),
    name = 'units',
    id = '',
    disabled = false,
  } = $props();

  let units = $state([]);
  let loading = $state(true);

  async function loadUnits() {
    try {
      units = await api.get('/api/settings/units/');
    } catch (e) {
      units = ['none'];
    } finally {
      loading = false;
    }
  }

  loadUnits();
</script>

<select
  {name}
  id={id || name}
  bind:value
  {disabled}
>
  {#each units as unit}
    <option value={unit}>{unit}</option>
  {/each}
</select>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/UnitsSelect.svelte frontend/src/lib/api.js
git commit -m "feat: add reusable UnitsSelect Svelte component and api.put"
```

---

### Task 9: Svelte settings UI for units management

**Files:**
- Create: `frontend/src/components/UnitsManager.svelte`
- Modify: `frontend/src/routes/SettingsPage.svelte`

- [ ] **Step 1: Create the UnitsManager component**

```svelte
<!-- frontend/src/components/UnitsManager.svelte -->
<script>
  import { api } from '../lib/api.js';

  let units = $state([]);
  let newUnit = $state('');
  let error = $state('');
  let saving = $state(false);
  let loading = $state(true);

  async function loadUnits() {
    try {
      units = await api.get('/api/settings/units/');
    } catch (e) {
      error = 'Failed to load units.';
    } finally {
      loading = false;
    }
  }

  async function saveUnits() {
    saving = true;
    error = '';
    try {
      units = await api.put('/api/settings/units/', units);
    } catch (e) {
      error = e.data?.error || e.message || 'Failed to save.';
    } finally {
      saving = false;
    }
  }

  function addUnit() {
    const trimmed = newUnit.trim();
    if (!trimmed) return;
    if (units.includes(trimmed)) {
      error = `"${trimmed}" already exists.`;
      return;
    }
    error = '';
    units = [...units, trimmed];
    newUnit = '';
    saveUnits();
  }

  function removeUnit(index) {
    if (units[index] === 'none') return;
    units = units.filter((_, i) => i !== index);
    saveUnits();
  }

  function moveUp(index) {
    if (index <= 1) return;  // can't move above "none" at index 0
    const copy = [...units];
    [copy[index - 1], copy[index]] = [copy[index], copy[index - 1]];
    units = copy;
    saveUnits();
  }

  function moveDown(index) {
    if (index === 0 || index >= units.length - 1) return;
    const copy = [...units];
    [copy[index], copy[index + 1]] = [copy[index + 1], copy[index]];
    units = copy;
    saveUnits();
  }

  loadUnits();
</script>

<h3>Units</h3>
<p>Manage the list of available units. Removing a unit does not update existing records — they keep their current value, but the unit won't be available for selection going forward unless re-added.</p>

{#if error}
  <p><strong>Error:</strong> {error}</p>
{/if}

{#if loading}
  <p>Loading...</p>
{:else}
  <table>
    <thead>
      <tr>
        <th>Unit</th>
        <th>Order</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {#each units as unit, i}
        <tr>
          <td>{unit}</td>
          <td>
            {#if i > 1}
              <button onclick={() => moveUp(i)} disabled={saving}>↑</button>
            {/if}
            {#if i > 0 && i < units.length - 1}
              <button onclick={() => moveDown(i)} disabled={saving}>↓</button>
            {/if}
          </td>
          <td>
            {#if unit !== 'none'}
              <button onclick={() => removeUnit(i)} disabled={saving}>Remove</button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>

  <p>
    <input
      type="text"
      bind:value={newUnit}
      placeholder="New unit name"
      onkeydown={(e) => { if (e.key === 'Enter') addUnit(); }}
    />
    <button onclick={addUnit} disabled={saving || !newUnit.trim()}>Add</button>
  </p>
{/if}
```

- [ ] **Step 2: Add UnitsManager to the settings page**

In `frontend/src/routes/SettingsPage.svelte`:

```svelte
<script>
  import QBOConnectionCard from '../components/QBOConnectionCard.svelte';
  import AccountingCategoryMapping from '../components/AccountingCategoryMapping.svelte';
  import UnitsManager from '../components/UnitsManager.svelte';
</script>

<h2>Settings</h2>

<QBOConnectionCard />

<AccountingCategoryMapping />

<UnitsManager />
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/UnitsManager.svelte frontend/src/routes/SettingsPage.svelte
git commit -m "feat: add units management UI to Svelte settings page"
```

---

### Task 10: Update Django settings template

**Files:**
- Modify: `templates/settings.html`

- [ ] **Step 1: Add units section to the settings template**

In `templates/settings.html`, add after the "Inventory & Pricing" section (after line 23):

```html
<h3>Units</h3>
<p>Units are managed from the <a href="/#/settings">Svelte settings page</a>.</p>
```

- [ ] **Step 2: Commit**

```bash
git add templates/settings.html
git commit -m "feat: add units link to Django settings page"
```

---

### Task 11: Update InventoryItemForm template

**Files:**
- Modify: `templates/inventory/inventory_item_form.html`

- [ ] **Step 1: Remove the JavaScript for units_select/units_custom toggle**

The template currently has a `<script>` block (lines 18-28) that toggles visibility of the custom units field based on the "other" dropdown selection. Since the form no longer has `units_select`/`units_custom` fields (replaced by a single `units` dropdown in Task 4), this JavaScript is no longer needed and will cause errors.

Replace the entire file with:

```html
{% extends 'base.html' %}

{% block title %}{{ title }} - Inventory - Minibini{% endblock %}

{% block content %}
<h2>{{ title }}</h2>

<form method="post">
    {% csrf_token %}
    <table>
        {{ form.as_table }}
    </table>
    <br>
    <button type="submit">{{ button_text }}</button>
    <a href="{% url 'inventory:inventory_list' %}">Cancel</a>
</form>

{% endblock %}
```

- [ ] **Step 2: Run the full test suite**

Run: `python manage.py test -v2`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add templates/inventory/inventory_item_form.html
git commit -m "fix: remove units_select/units_custom JS from inventory form template"
```

---

### Task 12: Final verification

- [ ] **Step 1: Run the complete test suite**

Run: `python manage.py test -v2`
Expected: All tests PASS.

- [ ] **Step 2: Start dev servers and manually verify**

Run: `python manage.py runserver` and `cd frontend && npm run dev`

Check:
- Settings page (`/#/settings`) shows the units manager
- Units can be added, removed, reordered
- Any form with a units field shows a dropdown (task edit, line item forms, etc.)
- Creating items via API with invalid units returns 400

- [ ] **Step 3: Commit any final fixes**

```bash
git add -A
git commit -m "chore: final cleanup for configurable units"
```
