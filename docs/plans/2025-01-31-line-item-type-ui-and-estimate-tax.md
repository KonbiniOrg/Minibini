# Line Item Type UI and Estimate Tax Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create CRUD views for LineItemType, add LineItemType to all line item forms, and display tax calculations on Estimates.

**Architecture:** Follow existing Minibini CRUD patterns (function-based views, plain HTML templates, Django messages). Tax is calculated using TaxCalculationService and displayed in Estimate detail/list views. Customer tax exemption comes from Job > Contact > Business.tax_multiplier.

**Tech Stack:** Django 5.2, MySQL, Plain HTML templates, Django Forms

---

## Phase 1: LineItemType CRUD Views

### Task 1: Create LineItemType Admin Registration

**Files:**
- Create: `apps/core/admin.py`

**Step 1: Write the admin registration**

```python
from django.contrib import admin
from .models import User, Configuration, LineItemType


@admin.register(LineItemType)
class LineItemTypeAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'taxable', 'default_units', 'is_active']
    list_filter = ['taxable', 'is_active']
    search_fields = ['code', 'name']
    ordering = ['name']
```

**Step 2: Verify in admin**

Run: `python manage.py runserver`
Visit: `/admin/core/lineitemtype/`

---

### Task 2: Create LineItemType List View

**Files:**
- Modify: `apps/core/views.py` (create if needed)
- Create: `templates/core/line_item_type_list.html`
- Modify: `apps/core/urls.py` (create if needed)
- Test: `tests/test_line_item_type_views.py`

**Step 1: Write failing test**

```python
# tests/test_line_item_type_views.py
"""Tests for LineItemType CRUD views."""
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import LineItemType


class LineItemTypeListViewTest(TestCase):
    """Tests for line item type list view."""

    def setUp(self):
        self.client = Client()

    def test_list_view_returns_200(self):
        """Test that list view returns 200."""
        response = self.client.get(reverse('core:line_item_type_list'))
        self.assertEqual(response.status_code, 200)

    def test_list_view_shows_line_item_types(self):
        """Test that list view displays line item types."""
        LineItemType.objects.create(code='TST', name='Test Type')
        response = self.client.get(reverse('core:line_item_type_list'))
        self.assertContains(response, 'Test Type')
        self.assertContains(response, 'TST')

    def test_list_view_only_shows_active_by_default(self):
        """Test that inactive types are hidden by default."""
        LineItemType.objects.create(code='ACT', name='Active', is_active=True)
        LineItemType.objects.create(code='INA', name='Inactive', is_active=False)
        response = self.client.get(reverse('core:line_item_type_list'))
        self.assertContains(response, 'Active')
        self.assertNotContains(response, 'Inactive')

    def test_list_view_shows_all_with_param(self):
        """Test that show_all=1 displays inactive types."""
        LineItemType.objects.create(code='INA', name='Inactive', is_active=False)
        response = self.client.get(reverse('core:line_item_type_list') + '?show_all=1')
        self.assertContains(response, 'Inactive')
```

**Step 2: Run test to verify it fails**

Run: `echo 'yes' | python manage.py test tests.test_line_item_type_views.LineItemTypeListViewTest -v 2`
Expected: FAIL (NoReverseMatch - URL doesn't exist)

**Step 3: Create URL configuration**

```python
# apps/core/urls.py
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('line-item-types/', views.line_item_type_list, name='line_item_type_list'),
]
```

**Step 4: Register core URLs in main urls.py**

Add to `minibini/urls.py`:
```python
path('core/', include('apps.core.urls')),
```

**Step 5: Create view**

```python
# apps/core/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from .models import LineItemType


def line_item_type_list(request):
    """List all line item types."""
    show_all = request.GET.get('show_all', '0') == '1'

    if show_all:
        line_item_types = LineItemType.objects.all()
    else:
        line_item_types = LineItemType.objects.filter(is_active=True)

    return render(request, 'core/line_item_type_list.html', {
        'line_item_types': line_item_types,
        'show_all': show_all,
    })
```

**Step 6: Create template**

```html
<!-- templates/core/line_item_type_list.html -->
{% extends 'base.html' %}

{% block title %}Line Item Types - Minibini{% endblock %}

{% block content %}
<h2>Line Item Types</h2>

<p>
    <a href="{% url 'core:line_item_type_create' %}" style="background-color: #007bff; color: white; padding: 5px 10px; text-decoration: none;">Add New Type</a>
    {% if show_all %}
        | <a href="{% url 'core:line_item_type_list' %}">Hide Inactive</a>
    {% else %}
        | <a href="{% url 'core:line_item_type_list' %}?show_all=1">Show All (Including Inactive)</a>
    {% endif %}
</p>

{% if line_item_types %}
<table border="1">
    <thead>
        <tr>
            <th>Code</th>
            <th>Name</th>
            <th>Taxable</th>
            <th>Default Units</th>
            <th>Active</th>
            <th>Actions</th>
        </tr>
    </thead>
    <tbody>
        {% for type in line_item_types %}
        <tr{% if not type.is_active %} style="opacity: 0.5;"{% endif %}>
            <td>{{ type.code }}</td>
            <td>{{ type.name }}</td>
            <td>{% if type.taxable %}Yes{% else %}No{% endif %}</td>
            <td>{{ type.default_units|default:"—" }}</td>
            <td>{% if type.is_active %}Yes{% else %}No{% endif %}</td>
            <td>
                <a href="{% url 'core:line_item_type_detail' type.pk %}">View</a> |
                <a href="{% url 'core:line_item_type_edit' type.pk %}">Edit</a>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p>No line item types found.</p>
{% endif %}

<p><a href="{% url 'settings' %}">Back to Settings</a></p>
{% endblock %}
```

**Step 7: Run test to verify it passes**

Run: `echo 'yes' | python manage.py test tests.test_line_item_type_views.LineItemTypeListViewTest -v 2`
Expected: PASS (may need to add placeholder URLs for create/detail/edit first)

---

### Task 3: Create LineItemType Detail View

**Files:**
- Modify: `apps/core/views.py`
- Create: `templates/core/line_item_type_detail.html`
- Modify: `apps/core/urls.py`
- Test: `tests/test_line_item_type_views.py`

**Step 1: Write failing test**

```python
class LineItemTypeDetailViewTest(TestCase):
    """Tests for line item type detail view."""

    def setUp(self):
        self.client = Client()
        self.line_item_type = LineItemType.objects.create(
            code='TST',
            name='Test Type',
            taxable=True,
            default_units='each',
            default_description='Test description'
        )

    def test_detail_view_returns_200(self):
        """Test that detail view returns 200."""
        response = self.client.get(
            reverse('core:line_item_type_detail', args=[self.line_item_type.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_detail_view_shows_all_fields(self):
        """Test that detail view displays all fields."""
        response = self.client.get(
            reverse('core:line_item_type_detail', args=[self.line_item_type.pk])
        )
        self.assertContains(response, 'TST')
        self.assertContains(response, 'Test Type')
        self.assertContains(response, 'each')
        self.assertContains(response, 'Test description')

    def test_detail_view_404_for_invalid_id(self):
        """Test that detail view returns 404 for invalid ID."""
        response = self.client.get(
            reverse('core:line_item_type_detail', args=[99999])
        )
        self.assertEqual(response.status_code, 404)
```

**Step 2: Run test to verify it fails**

Run: `echo 'yes' | python manage.py test tests.test_line_item_type_views.LineItemTypeDetailViewTest -v 2`
Expected: FAIL

**Step 3: Add URL**

```python
# In apps/core/urls.py, add:
path('line-item-types/<int:pk>/', views.line_item_type_detail, name='line_item_type_detail'),
```

**Step 4: Add view**

```python
def line_item_type_detail(request, pk):
    """Display line item type details."""
    line_item_type = get_object_or_404(LineItemType, pk=pk)
    return render(request, 'core/line_item_type_detail.html', {
        'line_item_type': line_item_type,
    })
```

**Step 5: Create template**

```html
<!-- templates/core/line_item_type_detail.html -->
{% extends 'base.html' %}

{% block title %}{{ line_item_type.name }} - Line Item Type - Minibini{% endblock %}

{% block content %}
<h2>Line Item Type: {{ line_item_type.name }}</h2>

<table border="1">
    <tr><th>Field</th><th>Value</th></tr>
    <tr><td>Code</td><td>{{ line_item_type.code }}</td></tr>
    <tr><td>Name</td><td>{{ line_item_type.name }}</td></tr>
    <tr><td>Taxable by Default</td><td>{% if line_item_type.taxable %}Yes{% else %}No{% endif %}</td></tr>
    <tr><td>Default Units</td><td>{{ line_item_type.default_units|default:"—" }}</td></tr>
    <tr><td>Default Description</td><td>{{ line_item_type.default_description|default:"—" }}</td></tr>
    <tr><td>Active</td><td>{% if line_item_type.is_active %}Yes{% else %}No{% endif %}</td></tr>
</table>

<p>
    <a href="{% url 'core:line_item_type_edit' line_item_type.pk %}">Edit</a> |
    <a href="{% url 'core:line_item_type_list' %}">Back to List</a>
</p>
{% endblock %}
```

**Step 6: Run test and verify**

Run: `echo 'yes' | python manage.py test tests.test_line_item_type_views.LineItemTypeDetailViewTest -v 2`
Expected: PASS

---

### Task 4: Create LineItemType Create View

**Files:**
- Modify: `apps/core/views.py`
- Create: `apps/core/forms.py`
- Create: `templates/core/line_item_type_form.html`
- Modify: `apps/core/urls.py`
- Test: `tests/test_line_item_type_views.py`

**Step 1: Write failing test**

```python
class LineItemTypeCreateViewTest(TestCase):
    """Tests for line item type create view."""

    def setUp(self):
        self.client = Client()

    def test_create_view_returns_200(self):
        """Test that create view returns 200."""
        response = self.client.get(reverse('core:line_item_type_create'))
        self.assertEqual(response.status_code, 200)

    def test_create_view_creates_line_item_type(self):
        """Test that POST creates a new line item type."""
        response = self.client.post(reverse('core:line_item_type_create'), {
            'code': 'NEW',
            'name': 'New Type',
            'taxable': True,
            'default_units': 'each',
            'default_description': 'New description',
            'is_active': True,
        })
        self.assertEqual(LineItemType.objects.filter(code='NEW').count(), 1)
        self.assertRedirects(response, reverse('core:line_item_type_list'))

    def test_create_view_shows_validation_errors(self):
        """Test that create view shows validation errors."""
        # Create existing type first
        LineItemType.objects.create(code='DUP', name='Duplicate')
        response = self.client.post(reverse('core:line_item_type_create'), {
            'code': 'DUP',  # Duplicate code
            'name': 'Another Type',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
```

**Step 2: Run test to verify it fails**

Run: `echo 'yes' | python manage.py test tests.test_line_item_type_views.LineItemTypeCreateViewTest -v 2`
Expected: FAIL

**Step 3: Create form**

```python
# apps/core/forms.py
from django import forms
from .models import LineItemType


class LineItemTypeForm(forms.ModelForm):
    """Form for creating and editing LineItemTypes."""

    class Meta:
        model = LineItemType
        fields = ['code', 'name', 'taxable', 'default_units', 'default_description', 'is_active']
        widgets = {
            'code': forms.TextInput(attrs={'maxlength': 20}),
            'name': forms.TextInput(attrs={'maxlength': 100}),
            'default_units': forms.TextInput(attrs={'maxlength': 50}),
            'default_description': forms.Textarea(attrs={'rows': 3}),
        }
```

**Step 4: Add URL**

```python
# In apps/core/urls.py, add:
path('line-item-types/create/', views.line_item_type_create, name='line_item_type_create'),
```

**Step 5: Add view**

```python
from .forms import LineItemTypeForm

def line_item_type_create(request):
    """Create a new line item type."""
    if request.method == 'POST':
        form = LineItemTypeForm(request.POST)
        if form.is_valid():
            line_item_type = form.save()
            messages.success(request, f'Line item type "{line_item_type.name}" created successfully.')
            return redirect('core:line_item_type_list')
    else:
        form = LineItemTypeForm()

    return render(request, 'core/line_item_type_form.html', {
        'form': form,
        'title': 'Create Line Item Type',
        'submit_label': 'Create',
    })
```

**Step 6: Create template**

```html
<!-- templates/core/line_item_type_form.html -->
{% extends 'base.html' %}

{% block title %}{{ title }} - Minibini{% endblock %}

{% block content %}
<h2>{{ title }}</h2>

<form method="post">
    {% csrf_token %}

    <p>
        <label for="id_code"><strong>Code *</strong></label><br>
        {{ form.code }}
        {% if form.code.errors %}<br><span style="color: red;">{{ form.code.errors }}</span>{% endif %}
    </p>

    <p>
        <label for="id_name"><strong>Name *</strong></label><br>
        {{ form.name }}
        {% if form.name.errors %}<br><span style="color: red;">{{ form.name.errors }}</span>{% endif %}
    </p>

    <p>
        <label for="id_taxable"><strong>Taxable by Default</strong></label><br>
        {{ form.taxable }}
        {% if form.taxable.errors %}<br><span style="color: red;">{{ form.taxable.errors }}</span>{% endif %}
    </p>

    <p>
        <label for="id_default_units"><strong>Default Units</strong></label><br>
        {{ form.default_units }}
        {% if form.default_units.errors %}<br><span style="color: red;">{{ form.default_units.errors }}</span>{% endif %}
    </p>

    <p>
        <label for="id_default_description"><strong>Default Description</strong></label><br>
        {{ form.default_description }}
        {% if form.default_description.errors %}<br><span style="color: red;">{{ form.default_description.errors }}</span>{% endif %}
    </p>

    <p>
        <label for="id_is_active"><strong>Active</strong></label><br>
        {{ form.is_active }}
        {% if form.is_active.errors %}<br><span style="color: red;">{{ form.is_active.errors }}</span>{% endif %}
    </p>

    <p>
        <button type="submit">{{ submit_label }}</button>
        <a href="{% url 'core:line_item_type_list' %}">Cancel</a>
    </p>
</form>
{% endblock %}
```

**Step 7: Run test and verify**

Run: `echo 'yes' | python manage.py test tests.test_line_item_type_views.LineItemTypeCreateViewTest -v 2`
Expected: PASS

---

### Task 5: Create LineItemType Edit View

**Files:**
- Modify: `apps/core/views.py`
- Modify: `apps/core/urls.py`
- Test: `tests/test_line_item_type_views.py`

**Step 1: Write failing test**

```python
class LineItemTypeEditViewTest(TestCase):
    """Tests for line item type edit view."""

    def setUp(self):
        self.client = Client()
        self.line_item_type = LineItemType.objects.create(
            code='EDT',
            name='Editable Type',
            taxable=False
        )

    def test_edit_view_returns_200(self):
        """Test that edit view returns 200."""
        response = self.client.get(
            reverse('core:line_item_type_edit', args=[self.line_item_type.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_edit_view_updates_line_item_type(self):
        """Test that POST updates the line item type."""
        response = self.client.post(
            reverse('core:line_item_type_edit', args=[self.line_item_type.pk]),
            {
                'code': 'EDT',
                'name': 'Updated Name',
                'taxable': True,
                'default_units': 'hours',
                'default_description': '',
                'is_active': True,
            }
        )
        self.line_item_type.refresh_from_db()
        self.assertEqual(self.line_item_type.name, 'Updated Name')
        self.assertTrue(self.line_item_type.taxable)
        self.assertRedirects(response, reverse('core:line_item_type_detail', args=[self.line_item_type.pk]))

    def test_edit_view_prepopulates_form(self):
        """Test that edit view prepopulates the form with current values."""
        response = self.client.get(
            reverse('core:line_item_type_edit', args=[self.line_item_type.pk])
        )
        self.assertContains(response, 'Editable Type')
        self.assertContains(response, 'EDT')
```

**Step 2: Run test to verify it fails**

Run: `echo 'yes' | python manage.py test tests.test_line_item_type_views.LineItemTypeEditViewTest -v 2`
Expected: FAIL

**Step 3: Add URL**

```python
# In apps/core/urls.py, add:
path('line-item-types/<int:pk>/edit/', views.line_item_type_edit, name='line_item_type_edit'),
```

**Step 4: Add view**

```python
def line_item_type_edit(request, pk):
    """Edit an existing line item type."""
    line_item_type = get_object_or_404(LineItemType, pk=pk)

    if request.method == 'POST':
        form = LineItemTypeForm(request.POST, instance=line_item_type)
        if form.is_valid():
            form.save()
            messages.success(request, f'Line item type "{line_item_type.name}" updated successfully.')
            return redirect('core:line_item_type_detail', pk=line_item_type.pk)
    else:
        form = LineItemTypeForm(instance=line_item_type)

    return render(request, 'core/line_item_type_form.html', {
        'form': form,
        'line_item_type': line_item_type,
        'title': f'Edit Line Item Type: {line_item_type.name}',
        'submit_label': 'Save Changes',
    })
```

**Step 5: Run test and verify**

Run: `echo 'yes' | python manage.py test tests.test_line_item_type_views.LineItemTypeEditViewTest -v 2`
Expected: PASS

---

### Task 6: Add LineItemType Link to Settings Page

**Files:**
- Modify: `templates/settings.html`

**Step 1: Check current settings template**

Read: `templates/settings.html`

**Step 2: Add link to LineItemTypes**

Add a link to the LineItemType list in the settings template.

---

## Phase 2: Add LineItemType to Line Item Forms

### Task 7: Add LineItemType to Manual Line Item Form (Estimate)

**Files:**
- Modify: `apps/jobs/forms.py` - ManualLineItemForm
- Modify: `templates/jobs/estimate_add_line_item.html`
- Test: `tests/test_estimate_line_item_type.py`

**Step 1: Write failing test**

```python
# tests/test_estimate_line_item_type.py
"""Tests for LineItemType in Estimate line items."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import LineItemType
from apps.contacts.models import Contact
from apps.jobs.models import Job, Estimate, EstimateLineItem


class EstimateLineItemTypeTest(TestCase):
    """Tests for LineItemType in Estimate line item forms."""

    @classmethod
    def setUpTestData(cls):
        cls.contact = Contact.objects.create(
            first_name='Test',
            last_name='Customer',
            email='test@example.com',
            work_number='555-1234'
        )
        cls.job = Job.objects.create(
            job_number='TEST-001',
            contact=cls.contact
        )
        cls.estimate = Estimate.objects.create(
            job=cls.job,
            estimate_number='EST-001',
            status='draft'
        )
        cls.service_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )

    def setUp(self):
        self.client = Client()

    def test_manual_form_includes_line_item_type_field(self):
        """Test that manual line item form shows LineItemType field."""
        response = self.client.get(
            reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id])
        )
        self.assertContains(response, 'line_item_type')

    def test_manual_form_creates_line_item_with_type(self):
        """Test that manual form creates line item with LineItemType."""
        response = self.client.post(
            reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id]),
            {
                'manual_submit': '1',
                'description': 'Test Service',
                'qty': '2.00',
                'units': 'hours',
                'price_currency': '50.00',
                'line_item_type': self.service_type.pk,
            }
        )
        line_item = EstimateLineItem.objects.filter(estimate=self.estimate).first()
        self.assertIsNotNone(line_item)
        self.assertEqual(line_item.line_item_type, self.service_type)

    def test_manual_form_requires_line_item_type(self):
        """Test that manual form requires LineItemType."""
        response = self.client.post(
            reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id]),
            {
                'manual_submit': '1',
                'description': 'Test Service',
                'qty': '2.00',
                'units': 'hours',
                'price_currency': '50.00',
                # No line_item_type
            }
        )
        # Should stay on page with error
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EstimateLineItem.objects.filter(estimate=self.estimate).count(), 0)
```

**Step 2: Run test to verify it fails**

Run: `echo 'yes' | python manage.py test tests.test_estimate_line_item_type -v 2`
Expected: FAIL

**Step 3: Update ManualLineItemForm**

```python
# In apps/jobs/forms.py, update ManualLineItemForm:
class ManualLineItemForm(forms.ModelForm):
    class Meta:
        model = EstimateLineItem
        fields = ['line_item_type', 'description', 'qty', 'units', 'price_currency']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show active line item types
        self.fields['line_item_type'].queryset = LineItemType.objects.filter(is_active=True)
        self.fields['line_item_type'].required = True
```

**Step 4: Update template**

Add line_item_type field to `templates/jobs/estimate_add_line_item.html` manual form section.

**Step 5: Run test and verify**

Run: `echo 'yes' | python manage.py test tests.test_estimate_line_item_type -v 2`
Expected: PASS

---

### Task 8: Add LineItemType Auto-Copy from PriceListItem

**Files:**
- Modify: `apps/jobs/views.py` - estimate_add_line_item
- Test: `tests/test_estimate_line_item_type.py`

**Step 1: Write failing test**

```python
class EstimateLineItemFromPriceListTest(TestCase):
    """Tests for LineItemType when adding from PriceList."""

    @classmethod
    def setUpTestData(cls):
        cls.contact = Contact.objects.create(
            first_name='Test',
            last_name='Customer',
            email='test@example.com',
            work_number='555-1234'
        )
        cls.job = Job.objects.create(
            job_number='TEST-001',
            contact=cls.contact
        )
        cls.estimate = Estimate.objects.create(
            job=cls.job,
            estimate_number='EST-001',
            status='draft'
        )
        cls.product_type, _ = LineItemType.objects.get_or_create(
            code='PRD',
            defaults={'name': 'Product', 'taxable': True}
        )
        # Import here to avoid circular import
        from apps.invoicing.models import PriceListItem
        cls.price_list_item = PriceListItem.objects.create(
            code='ITEM-001',
            description='Test Product',
            selling_price=Decimal('100.00'),
            line_item_type=cls.product_type
        )

    def setUp(self):
        self.client = Client()

    def test_pricelist_form_copies_line_item_type(self):
        """Test that adding from price list copies the LineItemType."""
        response = self.client.post(
            reverse('jobs:estimate_add_line_item', args=[self.estimate.estimate_id]),
            {
                'pricelist_submit': '1',
                'price_list_item': self.price_list_item.pk,
                'qty': '1.00',
            }
        )
        line_item = EstimateLineItem.objects.filter(estimate=self.estimate).first()
        self.assertIsNotNone(line_item)
        self.assertEqual(line_item.line_item_type, self.product_type)
```

**Step 2: Run test to verify it fails**

Run: `echo 'yes' | python manage.py test tests.test_estimate_line_item_type.EstimateLineItemFromPriceListTest -v 2`
Expected: FAIL

**Step 3: Update view to copy line_item_type from PriceListItem**

```python
# In apps/jobs/views.py, update the pricelist_submit section:
line_item = EstimateLineItem.objects.create(
    estimate=estimate,
    price_list_item=price_list_item,
    description=price_list_item.description,
    qty=qty,
    units=price_list_item.units,
    price_currency=price_list_item.selling_price,
    line_item_type=price_list_item.line_item_type,  # Copy from PriceListItem
)
```

**Step 4: Run test and verify**

Run: `echo 'yes' | python manage.py test tests.test_estimate_line_item_type.EstimateLineItemFromPriceListTest -v 2`
Expected: PASS

---

## Phase 3: Tax Calculation Display on Estimates

### Task 9: Update Estimate Detail View with Tax Calculation

**Files:**
- Modify: `apps/jobs/views.py` - estimate_detail
- Modify: `templates/jobs/estimate_detail.html`
- Test: `tests/test_estimate_tax_display.py`

**Step 1: Write failing test**

```python
# tests/test_estimate_tax_display.py
"""Tests for tax display on Estimates."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import Configuration, LineItemType
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job, Estimate, EstimateLineItem


class EstimateTaxDisplayTest(TestCase):
    """Tests for tax calculation display on Estimate detail."""

    @classmethod
    def setUpTestData(cls):
        # Set up tax rate
        Configuration.objects.create(key='default_tax_rate', value='0.10')  # 10%

        cls.contact = Contact.objects.create(
            first_name='Test',
            last_name='Customer',
            email='test@example.com',
            work_number='555-1234'
        )
        cls.job = Job.objects.create(
            job_number='TEST-001',
            contact=cls.contact
        )
        cls.estimate = Estimate.objects.create(
            job=cls.job,
            estimate_number='EST-001',
            status='draft'
        )
        cls.taxable_type, _ = LineItemType.objects.get_or_create(
            code='MAT',
            defaults={'name': 'Material', 'taxable': True}
        )
        cls.nontaxable_type, _ = LineItemType.objects.get_or_create(
            code='SVC',
            defaults={'name': 'Service', 'taxable': False}
        )

    def setUp(self):
        self.client = Client()
        # Clear line items between tests
        EstimateLineItem.objects.filter(estimate=self.estimate).delete()

    def test_estimate_detail_shows_subtotal(self):
        """Test that estimate detail shows subtotal."""
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            description='Test Item',
            qty=Decimal('2.00'),
            price_currency=Decimal('50.00')
        )
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        )
        self.assertContains(response, 'Subtotal')
        self.assertContains(response, '100.00')

    def test_estimate_detail_shows_tax(self):
        """Test that estimate detail shows tax amount."""
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            description='Taxable Item',
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00')
        )
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        )
        self.assertContains(response, 'Tax')
        self.assertContains(response, '10.00')  # 10% of $100

    def test_estimate_detail_shows_total_with_tax(self):
        """Test that estimate detail shows total including tax."""
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.taxable_type,
            description='Taxable Item',
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00')
        )
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        )
        self.assertContains(response, 'Total')
        self.assertContains(response, '110.00')  # $100 + $10 tax

    def test_nontaxable_items_excluded_from_tax(self):
        """Test that non-taxable items don't contribute to tax."""
        EstimateLineItem.objects.create(
            estimate=self.estimate,
            line_item_type=self.nontaxable_type,  # Non-taxable
            description='Service Item',
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00')
        )
        response = self.client.get(
            reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
        )
        # Tax should be $0
        self.assertContains(response, '$0.00')


class EstimateCustomerExemptionTest(TestCase):
    """Tests for customer tax exemption on Estimates."""

    @classmethod
    def setUpTestData(cls):
        Configuration.objects.create(key='default_tax_rate', value='0.10')  # 10%

        cls.taxable_type, _ = LineItemType.objects.get_or_create(
            code='MAT',
            defaults={'name': 'Material', 'taxable': True}
        )

    def setUp(self):
        self.client = Client()

    def test_exempt_customer_shows_zero_tax(self):
        """Test that tax-exempt customer shows $0 tax."""
        # Create exempt business
        contact = Contact.objects.create(
            first_name='Exempt',
            last_name='Customer',
            email='exempt@example.com',
            work_number='555-0000'
        )
        exempt_business = Business.objects.create(
            business_name='Tax Exempt Corp',
            default_contact=contact,
            tax_multiplier=Decimal('0.00')
        )
        contact.business = exempt_business
        contact.save()

        job = Job.objects.create(
            job_number='EXEMPT-001',
            contact=contact
        )
        estimate = Estimate.objects.create(
            job=job,
            estimate_number='EST-EXEMPT',
            status='draft'
        )
        EstimateLineItem.objects.create(
            estimate=estimate,
            line_item_type=self.taxable_type,
            description='Taxable Item',
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00')
        )

        response = self.client.get(
            reverse('jobs:estimate_detail', args=[estimate.estimate_id])
        )
        # Should show exemption info and $0 tax
        self.assertContains(response, 'exempt')  # Some indicator of exemption
```

**Step 2: Run test to verify it fails**

Run: `echo 'yes' | python manage.py test tests.test_estimate_tax_display -v 2`
Expected: FAIL

**Step 3: Update estimate_detail view**

```python
# In apps/jobs/views.py, update estimate_detail:
from apps.core.services import TaxCalculationService

def estimate_detail(request, estimate_id):
    estimate = get_object_or_404(Estimate, estimate_id=estimate_id)

    # ... existing status update handling ...

    line_items = EstimateLineItem.objects.filter(estimate=estimate).order_by('line_item_id')
    subtotal = sum(item.total_amount for item in line_items)

    # Get customer business for tax calculation
    customer = None
    if estimate.job.contact.business:
        customer = estimate.job.contact.business

    # Calculate tax
    tax_amount = TaxCalculationService.calculate_document_tax(estimate, customer=customer)
    total_with_tax = subtotal + tax_amount

    # Check if customer is tax exempt
    is_tax_exempt = customer and customer.tax_multiplier == Decimal('0.00')

    # ... rest of view ...

    return render(request, 'jobs/estimate_detail.html', {
        'estimate': estimate,
        'line_items': line_items,
        'subtotal': subtotal,
        'tax_amount': tax_amount,
        'total_with_tax': total_with_tax,
        'is_tax_exempt': is_tax_exempt,
        'customer': customer,
        # ... other context ...
    })
```

**Step 4: Update template**

```html
<!-- In templates/jobs/estimate_detail.html, update the footer section -->
<tfoot>
    <tr style="background-color: #f5f5f5;">
        <td colspan="{% if estimate.status == 'draft' %}6{% else %}5{% endif %}" style="text-align: right;">Subtotal:</td>
        <td>${{ subtotal|floatformat:2 }}</td>
        {% if estimate.status == 'draft' %}<td></td>{% endif %}
    </tr>
    <tr style="background-color: #f5f5f5;">
        <td colspan="{% if estimate.status == 'draft' %}6{% else %}5{% endif %}" style="text-align: right;">
            Tax{% if is_tax_exempt %} (Customer Exempt){% endif %}:
        </td>
        <td>${{ tax_amount|floatformat:2 }}</td>
        {% if estimate.status == 'draft' %}<td></td>{% endif %}
    </tr>
    <tr style="background-color: #f0f0f0; font-weight: bold;">
        <td colspan="{% if estimate.status == 'draft' %}6{% else %}5{% endif %}" style="text-align: right;">Total:</td>
        <td>${{ total_with_tax|floatformat:2 }}</td>
        {% if estimate.status == 'draft' %}<td></td>{% endif %}
    </tr>
</tfoot>
```

**Step 5: Run test and verify**

Run: `echo 'yes' | python manage.py test tests.test_estimate_tax_display -v 2`
Expected: PASS

---

### Task 10: Add LineItemType Column to Estimate Line Items Table

**Files:**
- Modify: `templates/jobs/estimate_detail.html`
- Test: `tests/test_estimate_tax_display.py`

**Step 1: Write failing test**

```python
def test_estimate_detail_shows_line_item_type(self):
    """Test that estimate detail shows LineItemType for each item."""
    EstimateLineItem.objects.create(
        estimate=self.estimate,
        line_item_type=self.taxable_type,
        description='Material Item',
        qty=Decimal('1.00'),
        price_currency=Decimal('50.00')
    )
    response = self.client.get(
        reverse('jobs:estimate_detail', args=[self.estimate.estimate_id])
    )
    self.assertContains(response, 'Material')  # The type name
```

**Step 2: Run test**

**Step 3: Update template to add Type column**

Add "Type" column to the line items table, showing `item.line_item_type.name` or "—" if none.

**Step 4: Run test and verify**

---

## Phase 4: Add LineItemType to PriceListItem CRUD

### Task 11: Add LineItemType to PriceListItem Form

**Files:**
- Identify: PriceListItem forms and templates
- Modify: PriceListItem create/edit forms
- Test: `tests/test_price_list_item_type_ui.py`

**Step 1: Explore existing PriceListItem UI**

Find PriceListItem views, forms, and templates.

**Step 2: Write failing test**

```python
# tests/test_price_list_item_type_ui.py
"""Tests for LineItemType in PriceListItem CRUD."""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.core.models import LineItemType
from apps.invoicing.models import PriceListItem


class PriceListItemTypeUITest(TestCase):
    """Tests for LineItemType in PriceListItem forms."""

    @classmethod
    def setUpTestData(cls):
        cls.product_type, _ = LineItemType.objects.get_or_create(
            code='PRD',
            defaults={'name': 'Product', 'taxable': True}
        )

    def setUp(self):
        self.client = Client()

    def test_create_form_includes_line_item_type(self):
        """Test that create form shows LineItemType field."""
        response = self.client.get(reverse('invoicing:price_list_item_create'))
        self.assertContains(response, 'line_item_type')

    def test_create_with_line_item_type(self):
        """Test creating PriceListItem with LineItemType."""
        response = self.client.post(reverse('invoicing:price_list_item_create'), {
            'code': 'TEST-001',
            'description': 'Test Product',
            'selling_price': '100.00',
            'purchase_price': '50.00',
            'line_item_type': self.product_type.pk,
        })
        item = PriceListItem.objects.filter(code='TEST-001').first()
        self.assertIsNotNone(item)
        self.assertEqual(item.line_item_type, self.product_type)
```

**Step 3: Update PriceListItem form**

Add `line_item_type` to the PriceListItem form fields.

**Step 4: Update templates**

Add LineItemType field to create/edit templates.

**Step 5: Run tests and verify**

---

## Phase 5: Add LineItemType to Purchasing Line Items

### Task 12: Add LineItemType to PurchaseOrder Line Item Forms

**Files:**
- Modify: `apps/purchasing/forms.py`
- Modify: PO line item templates
- Test: `tests/test_po_line_item_type.py`

Similar pattern to Estimate line items - add line_item_type field to manual form, copy from PriceListItem when adding from catalog.

---

### Task 13: Add LineItemType to Bill Line Item Forms

**Files:**
- Modify: `apps/purchasing/forms.py`
- Modify: Bill line item templates
- Test: `tests/test_bill_line_item_type.py`

Similar pattern to PO line items.

---

## Phase 6: Configuration and Admin

### Task 14: Add Tax Rate Configuration UI

**Files:**
- Modify: Settings template or create Configuration edit view
- Test: `tests/test_tax_configuration_ui.py`

Add ability to view/edit `default_tax_rate` and `org_tax_multiplier` in settings.

---

### Task 15: Final Integration Testing

**Files:**
- Test: `tests/test_line_item_type_integration.py`

Write integration tests that cover the full flow:
1. Create LineItemType
2. Create PriceListItem with that type
3. Create Estimate, add line item from PriceListItem
4. Verify tax calculation with customer exemption

---

## Summary of Files to Create/Modify

### New Files:
- `apps/core/admin.py`
- `apps/core/views.py`
- `apps/core/urls.py`
- `apps/core/forms.py`
- `templates/core/line_item_type_list.html`
- `templates/core/line_item_type_detail.html`
- `templates/core/line_item_type_form.html`
- `tests/test_line_item_type_views.py`
- `tests/test_estimate_line_item_type.py`
- `tests/test_estimate_tax_display.py`
- `tests/test_price_list_item_type_ui.py`
- `tests/test_po_line_item_type.py`
- `tests/test_bill_line_item_type.py`
- `tests/test_line_item_type_integration.py`

### Modified Files:
- `minibini/urls.py` - Add core URLs
- `apps/jobs/views.py` - Tax calculation in estimate_detail
- `apps/jobs/forms.py` - Add line_item_type to ManualLineItemForm
- `templates/jobs/estimate_detail.html` - Add tax display, type column
- `templates/jobs/estimate_add_line_item.html` - Add line_item_type field
- `templates/settings.html` - Add LineItemType link
- `apps/invoicing/forms.py` - Add line_item_type to PriceListItem form
- `apps/purchasing/forms.py` - Add line_item_type to PO/Bill line item forms
- Related templates for invoicing and purchasing
