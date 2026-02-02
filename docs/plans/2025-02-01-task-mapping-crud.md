# TaskMapping and ProductBundlingRule CRUD Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.  Also use the Test Driven Development superpower.

**Goal:** Add full CRUD views for TaskMapping and ProductBundlingRule in the Settings area, with user-friendly explanations.

**Architecture:** Follow the existing LineItemType CRUD pattern (apps/core). Views in apps/jobs, forms in apps/jobs/forms.py, templates in templates/jobs/. Each list page includes explanatory text about what the model does and how it fits into the workflow.

**Tech Stack:** Django function-based views, ModelForms with help_text, Bootstrap-less HTML tables

---

## Background: What These Models Do

### TaskMapping
Defines how worksheet tasks transform into estimate line items. Each TaskTemplate links to a TaskMapping. Key fields:
- **task_type_id**: Identifier for this mapping type
- **step_type**: What the task represents (product, component, labor, material, overhead)
- **mapping_strategy**: How it becomes a line item (direct, bundle_to_product, bundle_to_service, exclude)
- **default_product_type**: For bundling - what product type (e.g., "cabinet", "table")
- **output_line_item_type**: The LineItemType assigned to generated line items

### ProductBundlingRule
Defines how bundled components are combined into a single line item. Key fields:
- **product_type**: Which tasks to bundle (matches TaskMapping.default_product_type)
- **line_item_template**: Display name template (e.g., "Custom {product_type} - {product_identifier}")
- **pricing_method**: How to calculate price (sum_components, template_base, custom)
- **combine_instances**: Whether to show "4x Chair" or 4 separate line items

---

## Task 1: TaskMapping Create View and Form

**Files:**
- Modify: `apps/jobs/forms.py` (add TaskMappingForm)
- Modify: `apps/jobs/views.py` (add task_mapping_create)
- Modify: `apps/jobs/urls.py` (add URL)
- Create: `templates/jobs/task_mapping_form.html`
- Test: `tests/test_task_mapping_views.py`

**Step 1: Write failing test for TaskMapping create**

```python
# tests/test_task_mapping_views.py
from django.test import TestCase
from django.urls import reverse
from apps.jobs.models import TaskMapping
from apps.core.models import LineItemType


class TestTaskMappingCreateView(TestCase):
    def test_create_view_renders_form(self):
        """GET task_mapping_create shows the form."""
        response = self.client.get(reverse('jobs:task_mapping_create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Task Mapping')
        self.assertContains(response, 'mapping_strategy')

    def test_create_view_saves_mapping(self):
        """POST with valid data creates a TaskMapping."""
        line_item_type = LineItemType.objects.create(
            code='TST', name='Test Type', taxable=True
        )
        data = {
            'task_type_id': 'TEST-MAPPING',
            'step_type': 'labor',
            'mapping_strategy': 'direct',
            'default_product_type': '',
            'line_item_name': 'Test Service',
            'line_item_description': 'A test service',
            'output_line_item_type': line_item_type.pk,
            'breakdown_of_task': '',
        }
        response = self.client.post(reverse('jobs:task_mapping_create'), data)
        self.assertEqual(response.status_code, 302)  # Redirect on success
        self.assertTrue(TaskMapping.objects.filter(task_type_id='TEST-MAPPING').exists())
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_task_mapping_views.TestTaskMappingCreateView -v 2`
Expected: FAIL with "NoReverseMatch: 'task_mapping_create' is not a valid view function or pattern name"

**Step 3: Add TaskMappingForm to forms.py**

```python
# In apps/jobs/forms.py, add:

class TaskMappingForm(forms.ModelForm):
    """Form for creating/editing TaskMappings with explanatory help text."""

    class Meta:
        model = TaskMapping
        fields = [
            'task_type_id', 'step_type', 'mapping_strategy',
            'default_product_type', 'line_item_name', 'line_item_description',
            'output_line_item_type', 'breakdown_of_task'
        ]
        help_texts = {
            'task_type_id': 'Unique identifier for this mapping (e.g., "CABINET-DOOR", "DELIVERY")',
            'step_type': 'What type of work this represents in the production process',
            'mapping_strategy': 'How tasks using this mapping appear on estimates',
            'default_product_type': 'Product type for bundling (e.g., "cabinet", "table"). Required for bundle strategies.',
            'line_item_name': 'Name shown on estimate line item when using "direct" mapping',
            'line_item_description': 'Description for the line item on estimates',
            'output_line_item_type': 'Determines taxability and categorization of generated line items',
            'breakdown_of_task': 'Internal notes about what this task involves',
        }
        widgets = {
            'line_item_description': forms.Textarea(attrs={'rows': 3}),
            'breakdown_of_task': forms.Textarea(attrs={'rows': 3}),
        }
```

**Step 4: Add task_mapping_create view**

```python
# In apps/jobs/views.py, add:

def task_mapping_create(request):
    """Create a new TaskMapping."""
    if request.method == 'POST':
        form = TaskMappingForm(request.POST)
        if form.is_valid():
            mapping = form.save()
            messages.success(request, f'Task mapping "{mapping.task_type_id}" created successfully.')
            return redirect('jobs:task_mapping_list')
    else:
        form = TaskMappingForm()

    return render(request, 'jobs/task_mapping_form.html', {
        'form': form,
        'title': 'Create Task Mapping',
        'submit_label': 'Create',
    })
```

**Step 5: Add URL pattern**

```python
# In apps/jobs/urls.py, add after task_mapping_list:
path('task-mappings/create/', views.task_mapping_create, name='task_mapping_create'),
```

**Step 6: Create template with explanatory text**

```html
<!-- templates/jobs/task_mapping_form.html -->
{% extends 'base.html' %}

{% block title %}{{ title }} - Minibini{% endblock %}

{% block navigation %}
{% include 'includes/settings_navigation.html' %}
{% endblock %}

{% block content %}
<h2>{{ title }}</h2>

<div style="background-color: #f0f0f0; padding: 10px; margin-bottom: 20px; border-left: 4px solid #007bff;">
    <strong>What is a Task Mapping?</strong>
    <p>Task Mappings define how worksheet tasks become estimate line items. Each Task Template uses a Task Mapping to determine:</p>
    <ul>
        <li><strong>How tasks appear on estimates</strong> - directly as individual items, bundled together, or hidden</li>
        <li><strong>What type of work it represents</strong> - product, component, labor, material, or overhead</li>
        <li><strong>Tax treatment</strong> - through the assigned Line Item Type</li>
    </ul>
</div>

<form method="post">
    {% csrf_token %}
    <table>
        {% for field in form %}
        <tr>
            <th><label for="{{ field.id_for_label }}">{{ field.label }}</label></th>
            <td>
                {{ field }}
                {% if field.help_text %}<br><small>{{ field.help_text }}</small>{% endif %}
                {% if field.errors %}<br><span style="color: red;">{{ field.errors }}</span>{% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>
    <p>
        <button type="submit">{{ submit_label }}</button>
        <a href="{% url 'jobs:task_mapping_list' %}">Cancel</a>
    </p>
</form>
{% endblock %}
```

**Step 7: Add import for TaskMappingForm in views.py**

Add to imports: `from .forms import TaskMappingForm`

**Step 8: Run tests to verify they pass**

Run: `python manage.py test tests.test_task_mapping_views.TestTaskMappingCreateView -v 2`
Expected: PASS


---

## Task 2: TaskMapping Detail View

**Files:**
- Modify: `apps/jobs/views.py` (add task_mapping_detail)
- Modify: `apps/jobs/urls.py` (add URL)
- Create: `templates/jobs/task_mapping_detail.html`
- Modify: `tests/test_task_mapping_views.py` (add tests)

**Step 1: Write failing test for detail view**

```python
# Add to tests/test_task_mapping_views.py:

class TestTaskMappingDetailView(TestCase):
    def setUp(self):
        self.mapping = TaskMapping.objects.create(
            task_type_id='DETAIL-TEST',
            step_type='labor',
            mapping_strategy='direct',
            line_item_name='Test Service'
        )

    def test_detail_view_shows_mapping(self):
        """GET task_mapping_detail shows the mapping details."""
        response = self.client.get(
            reverse('jobs:task_mapping_detail', args=[self.mapping.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'DETAIL-TEST')
        self.assertContains(response, 'Test Service')
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_task_mapping_views.TestTaskMappingDetailView -v 2`
Expected: FAIL with "NoReverseMatch"

**Step 3: Add view**

```python
# In apps/jobs/views.py, add:

def task_mapping_detail(request, pk):
    """Display TaskMapping details and linked templates."""
    mapping = get_object_or_404(TaskMapping, pk=pk)
    linked_templates = TaskTemplate.objects.filter(task_mapping=mapping)
    return render(request, 'jobs/task_mapping_detail.html', {
        'mapping': mapping,
        'linked_templates': linked_templates,
    })
```

**Step 4: Add URL pattern**

```python
# In apps/jobs/urls.py, add:
path('task-mappings/<int:pk>/', views.task_mapping_detail, name='task_mapping_detail'),
```

**Step 5: Create detail template**

```html
<!-- templates/jobs/task_mapping_detail.html -->
{% extends 'base.html' %}

{% block title %}Task Mapping: {{ mapping.task_type_id }} - Minibini{% endblock %}

{% block navigation %}
{% include 'includes/settings_navigation.html' %}
{% endblock %}

{% block content %}
<h2>Task Mapping: {{ mapping.task_type_id }}</h2>

<table border="1">
    <tr><th>Task Type ID</th><td>{{ mapping.task_type_id }}</td></tr>
    <tr><th>Step Type</th><td>{{ mapping.get_step_type_display }}</td></tr>
    <tr><th>Mapping Strategy</th><td>{{ mapping.get_mapping_strategy_display }}</td></tr>
    <tr><th>Default Product Type</th><td>{{ mapping.default_product_type|default:"-" }}</td></tr>
    <tr><th>Line Item Name</th><td>{{ mapping.line_item_name|default:"-" }}</td></tr>
    <tr><th>Line Item Description</th><td>{{ mapping.line_item_description|default:"-" }}</td></tr>
    <tr><th>Output Line Item Type</th><td>{% if mapping.output_line_item_type %}{{ mapping.output_line_item_type.name }} ({{ mapping.output_line_item_type.code }}){% else %}-{% endif %}</td></tr>
    <tr><th>Breakdown of Task</th><td>{{ mapping.breakdown_of_task|default:"-" }}</td></tr>
</table>

<p>
    <a href="{% url 'jobs:task_mapping_edit' mapping.pk %}">Edit</a> |
    <a href="{% url 'jobs:task_mapping_list' %}">Back to List</a>
</p>

<h3>Linked Task Templates</h3>
{% if linked_templates %}
<p>These templates use this mapping:</p>
<ul>
    {% for template in linked_templates %}
    <li><a href="{% url 'jobs:task_template_detail' template.pk %}">{{ template.template_name }}</a></li>
    {% endfor %}
</ul>
{% else %}
<p>No task templates are using this mapping yet.</p>
{% endif %}

{% endblock %}
```

**Step 6: Run tests**

Run: `python manage.py test tests.test_task_mapping_views.TestTaskMappingDetailView -v 2`
Expected: PASS

---

## Task 3: TaskMapping Edit View

**Files:**
- Modify: `apps/jobs/views.py` (add task_mapping_edit)
- Modify: `apps/jobs/urls.py` (add URL)
- Modify: `tests/test_task_mapping_views.py` (add tests)

**Step 1: Write failing test**

```python
# Add to tests/test_task_mapping_views.py:

class TestTaskMappingEditView(TestCase):
    def setUp(self):
        self.mapping = TaskMapping.objects.create(
            task_type_id='EDIT-TEST',
            step_type='labor',
            mapping_strategy='direct',
            line_item_name='Original Name'
        )

    def test_edit_view_renders_form(self):
        """GET task_mapping_edit shows form with existing data."""
        response = self.client.get(
            reverse('jobs:task_mapping_edit', args=[self.mapping.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'EDIT-TEST')
        self.assertContains(response, 'Original Name')

    def test_edit_view_updates_mapping(self):
        """POST with valid data updates the TaskMapping."""
        data = {
            'task_type_id': 'EDIT-TEST',
            'step_type': 'material',
            'mapping_strategy': 'direct',
            'default_product_type': '',
            'line_item_name': 'Updated Name',
            'line_item_description': '',
            'breakdown_of_task': '',
        }
        response = self.client.post(
            reverse('jobs:task_mapping_edit', args=[self.mapping.pk]),
            data
        )
        self.assertEqual(response.status_code, 302)
        self.mapping.refresh_from_db()
        self.assertEqual(self.mapping.line_item_name, 'Updated Name')
        self.assertEqual(self.mapping.step_type, 'material')
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_task_mapping_views.TestTaskMappingEditView -v 2`
Expected: FAIL with "NoReverseMatch"

**Step 3: Add view**

```python
# In apps/jobs/views.py, add:

def task_mapping_edit(request, pk):
    """Edit an existing TaskMapping."""
    mapping = get_object_or_404(TaskMapping, pk=pk)

    if request.method == 'POST':
        form = TaskMappingForm(request.POST, instance=mapping)
        if form.is_valid():
            form.save()
            messages.success(request, f'Task mapping "{mapping.task_type_id}" updated successfully.')
            return redirect('jobs:task_mapping_detail', pk=mapping.pk)
    else:
        form = TaskMappingForm(instance=mapping)

    return render(request, 'jobs/task_mapping_form.html', {
        'form': form,
        'mapping': mapping,
        'title': f'Edit Task Mapping: {mapping.task_type_id}',
        'submit_label': 'Save Changes',
    })
```

**Step 4: Add URL pattern**

```python
# In apps/jobs/urls.py, add:
path('task-mappings/<int:pk>/edit/', views.task_mapping_edit, name='task_mapping_edit'),
```

**Step 5: Run tests**

Run: `python manage.py test tests.test_task_mapping_views.TestTaskMappingEditView -v 2`
Expected: PASS


---

## Task 4: Update TaskMapping List with Links

**Files:**
- Modify: `templates/jobs/task_mapping_list.html` (add View/Edit links, Add button)
- Modify: `tests/test_task_mapping_views.py` (add list view tests)

**Step 1: Write failing test**

```python
# Add to tests/test_task_mapping_views.py:

class TestTaskMappingListView(TestCase):
    def setUp(self):
        self.mapping = TaskMapping.objects.create(
            task_type_id='LIST-TEST',
            step_type='labor',
            mapping_strategy='direct'
        )

    def test_list_view_shows_add_button(self):
        """List view should have Add New Mapping button."""
        response = self.client.get(reverse('jobs:task_mapping_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add New Mapping')
        self.assertContains(response, reverse('jobs:task_mapping_create'))

    def test_list_view_shows_actions(self):
        """List view should have View/Edit links for each mapping."""
        response = self.client.get(reverse('jobs:task_mapping_list'))
        self.assertContains(response, 'View')
        self.assertContains(response, 'Edit')
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_task_mapping_views.TestTaskMappingListView -v 2`
Expected: FAIL (no "Add New Mapping" text)

**Step 3: Update template**

```html
<!-- Replace templates/jobs/task_mapping_list.html with: -->
{% extends 'base.html' %}

{% block title %}Task Mappings - Minibini{% endblock %}

{% block navigation %}
{% include 'includes/settings_navigation.html' %}
{% endblock %}

{% block content %}
<h2>Task Mappings</h2>

<div style="background-color: #f0f0f0; padding: 10px; margin-bottom: 20px; border-left: 4px solid #007bff;">
    <strong>About Task Mappings</strong>
    <p>Task Mappings are reusable configuration templates that define how worksheet tasks transform into estimate line items. Each Task Template links to a Task Mapping.</p>
</div>

<p>
    <a href="{% url 'jobs:task_mapping_create' %}" style="background-color: #007bff; color: white; padding: 5px 10px; text-decoration: none;">Add New Mapping</a>
</p>

{% if mappings %}
    <table border="1">
        <tr>
            <th>Task Type</th>
            <th>Step Type</th>
            <th>Mapping Strategy</th>
            <th>Default Product Type</th>
            <th>Line Item Type</th>
            <th>Actions</th>
        </tr>
        {% for mapping in mappings %}
        <tr>
            <td>{{ mapping.task_type_id }}</td>
            <td>{{ mapping.get_step_type_display }}</td>
            <td>{{ mapping.get_mapping_strategy_display }}</td>
            <td>{{ mapping.default_product_type|default:"-" }}</td>
            <td>{% if mapping.output_line_item_type %}{{ mapping.output_line_item_type.code }}{% else %}-{% endif %}</td>
            <td>
                <a href="{% url 'jobs:task_mapping_detail' mapping.pk %}">View</a> |
                <a href="{% url 'jobs:task_mapping_edit' mapping.pk %}">Edit</a>
            </td>
        </tr>
        {% endfor %}
    </table>
{% else %}
    <p>No task mappings found. <a href="{% url 'jobs:task_mapping_create' %}">Create your first mapping</a>.</p>
{% endif %}

<h3>Mapping Strategy Reference</h3>
<ul>
    <li><strong>Direct</strong> - One task becomes one line item (e.g., consultation becomes "Design Consultation")</li>
    <li><strong>Bundle into product</strong> - Multiple component tasks bundled into one product (e.g., cut + assemble + finish = "Custom Table")</li>
    <li><strong>Bundle into service</strong> - Multiple tasks bundled into one service (e.g., delivery tasks = "Delivery & Installation")</li>
    <li><strong>Exclude from estimate</strong> - Internal tasks not shown to customer (e.g., shop overhead, quality checks)</li>
</ul>

<p><a href="{% url 'settings' %}">Back to Settings</a></p>
{% endblock %}
```

**Step 4: Run tests**

Run: `python manage.py test tests.test_task_mapping_views.TestTaskMappingListView -v 2`
Expected: PASS


---

## Task 5: TaskMapping Delete View

**Files:**
- Modify: `apps/jobs/views.py` (add task_mapping_delete)
- Modify: `apps/jobs/urls.py` (add URL)
- Modify: `templates/jobs/task_mapping_detail.html` (add delete link)
- Modify: `templates/jobs/task_mapping_list.html` (add delete link)
- Modify: `tests/test_task_mapping_views.py` (add tests)

**Note:** TaskMappings are configuration objects used only during estimate generation. They are NOT stored with line items or other output data, so they can be permanently deleted rather than archived.

**Step 1: Write failing test**

```python
# Add to tests/test_task_mapping_views.py:

class TestTaskMappingDeleteView(TestCase):
    def setUp(self):
        self.mapping = TaskMapping.objects.create(
            task_type_id='DELETE-TEST',
            step_type='labor',
            mapping_strategy='direct'
        )

    def test_delete_view_shows_confirmation(self):
        """GET task_mapping_delete shows confirmation page."""
        response = self.client.get(
            reverse('jobs:task_mapping_delete', args=[self.mapping.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'DELETE-TEST')
        self.assertContains(response, 'Are you sure')

    def test_delete_view_deletes_mapping(self):
        """POST deletes the TaskMapping."""
        response = self.client.post(
            reverse('jobs:task_mapping_delete', args=[self.mapping.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(TaskMapping.objects.filter(pk=self.mapping.pk).exists())

    def test_delete_blocked_when_templates_linked(self):
        """Cannot delete mapping if TaskTemplates are using it."""
        from apps.jobs.models import TaskTemplate
        TaskTemplate.objects.create(
            template_name='Linked Template',
            task_mapping=self.mapping,
            units='each',
            rate='100.00'
        )
        response = self.client.post(
            reverse('jobs:task_mapping_delete', args=[self.mapping.pk])
        )
        # Should redirect back with error, mapping still exists
        self.assertTrue(TaskMapping.objects.filter(pk=self.mapping.pk).exists())
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_task_mapping_views.TestTaskMappingDeleteView -v 2`
Expected: FAIL with "NoReverseMatch"

**Step 3: Add view**

```python
# In apps/jobs/views.py, add:

def task_mapping_delete(request, pk):
    """Delete a TaskMapping (only if no templates are using it)."""
    mapping = get_object_or_404(TaskMapping, pk=pk)
    linked_templates = TaskTemplate.objects.filter(task_mapping=mapping)

    if request.method == 'POST':
        if linked_templates.exists():
            messages.error(
                request,
                f'Cannot delete "{mapping.task_type_id}" - it is used by {linked_templates.count()} task template(s). '
                'Remove the mapping from those templates first.'
            )
            return redirect('jobs:task_mapping_detail', pk=mapping.pk)

        task_type_id = mapping.task_type_id
        mapping.delete()
        messages.success(request, f'Task mapping "{task_type_id}" deleted.')
        return redirect('jobs:task_mapping_list')

    return render(request, 'jobs/task_mapping_confirm_delete.html', {
        'mapping': mapping,
        'linked_templates': linked_templates,
    })
```

**Step 4: Add URL pattern**

```python
# In apps/jobs/urls.py, add:
path('task-mappings/<int:pk>/delete/', views.task_mapping_delete, name='task_mapping_delete'),
```

**Step 5: Create confirmation template**

```html
<!-- templates/jobs/task_mapping_confirm_delete.html -->
{% extends 'base.html' %}

{% block title %}Delete Task Mapping - Minibini{% endblock %}

{% block navigation %}
{% include 'includes/settings_navigation.html' %}
{% endblock %}

{% block content %}
<h2>Delete Task Mapping: {{ mapping.task_type_id }}</h2>

{% if linked_templates %}
<div style="background-color: #ffcccc; padding: 10px; margin-bottom: 20px; border-left: 4px solid #cc0000;">
    <strong>Cannot Delete</strong>
    <p>This mapping is used by the following Task Templates:</p>
    <ul>
        {% for template in linked_templates %}
        <li><a href="{% url 'jobs:task_template_detail' template.pk %}">{{ template.template_name }}</a></li>
        {% endfor %}
    </ul>
    <p>Remove the mapping from these templates before deleting.</p>
</div>
<p><a href="{% url 'jobs:task_mapping_detail' mapping.pk %}">Back to Detail</a></p>
{% else %}
<div style="background-color: #fff3cd; padding: 10px; margin-bottom: 20px; border-left: 4px solid #ffc107;">
    <strong>Are you sure you want to delete this task mapping?</strong>
    <p>This action cannot be undone. The mapping "{{ mapping.task_type_id }}" will be permanently removed.</p>
    <p><em>Note: This is safe because TaskMappings are only used during estimate generation and are not stored with line items.</em></p>
</div>

<form method="post">
    {% csrf_token %}
    <button type="submit" style="background-color: #dc3545; color: white; padding: 5px 15px;">Delete</button>
    <a href="{% url 'jobs:task_mapping_detail' mapping.pk %}">Cancel</a>
</form>
{% endif %}
{% endblock %}
```

**Step 6: Update detail template to add delete link**

In `templates/jobs/task_mapping_detail.html`, update the actions paragraph:
```html
<p>
    <a href="{% url 'jobs:task_mapping_edit' mapping.pk %}">Edit</a> |
    <a href="{% url 'jobs:task_mapping_delete' mapping.pk %}" style="color: #dc3545;">Delete</a> |
    <a href="{% url 'jobs:task_mapping_list' %}">Back to List</a>
</p>
```

**Step 7: Update list template to add delete link**

In `templates/jobs/task_mapping_list.html`, update the Actions column:
```html
<td>
    <a href="{% url 'jobs:task_mapping_detail' mapping.pk %}">View</a> |
    <a href="{% url 'jobs:task_mapping_edit' mapping.pk %}">Edit</a> |
    <a href="{% url 'jobs:task_mapping_delete' mapping.pk %}" style="color: #dc3545;">Delete</a>
</td>
```

**Step 8: Run tests**

Run: `python manage.py test tests.test_task_mapping_views.TestTaskMappingDeleteView -v 2`
Expected: PASS


---

## Task 6: ProductBundlingRule List View

**Files:**
- Modify: `apps/jobs/views.py` (add bundling_rule_list)
- Modify: `apps/jobs/urls.py` (add URL)
- Modify: `templates/settings.html` (add link)
- Create: `templates/jobs/bundling_rule_list.html`
- Create: `tests/test_bundling_rule_views.py`

**Step 1: Write failing test**

```python
# tests/test_bundling_rule_views.py
from django.test import TestCase
from django.urls import reverse
from apps.jobs.models import ProductBundlingRule


class TestBundlingRuleListView(TestCase):
    def test_list_view_renders(self):
        """GET bundling_rule_list shows the list."""
        response = self.client.get(reverse('jobs:bundling_rule_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Product Bundling Rules')

    def test_list_view_shows_rules(self):
        """List view displays existing rules."""
        rule = ProductBundlingRule.objects.create(
            rule_name='Test Rule',
            product_type='cabinet',
            line_item_template='Custom {product_type}',
            pricing_method='sum_components'
        )
        response = self.client.get(reverse('jobs:bundling_rule_list'))
        self.assertContains(response, 'Test Rule')
        self.assertContains(response, 'cabinet')
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_bundling_rule_views.TestBundlingRuleListView -v 2`
Expected: FAIL with "NoReverseMatch"

**Step 3: Add view**

```python
# In apps/jobs/views.py, add:

def bundling_rule_list(request):
    """List all ProductBundlingRules."""
    show_all = request.GET.get('show_all', '0') == '1'

    if show_all:
        rules = ProductBundlingRule.objects.all()
    else:
        rules = ProductBundlingRule.objects.filter(is_active=True)

    return render(request, 'jobs/bundling_rule_list.html', {
        'rules': rules,
        'show_all': show_all,
    })
```

**Step 4: Add URL pattern**

```python
# In apps/jobs/urls.py, add:
path('bundling-rules/', views.bundling_rule_list, name='bundling_rule_list'),
```

**Step 5: Add import for ProductBundlingRule in views.py**

Add to imports: `from .models import ProductBundlingRule`

**Step 6: Create template**

```html
<!-- templates/jobs/bundling_rule_list.html -->
{% extends 'base.html' %}

{% block title %}Product Bundling Rules - Minibini{% endblock %}

{% block navigation %}
{% include 'includes/settings_navigation.html' %}
{% endblock %}

{% block content %}
<h2>Product Bundling Rules</h2>

<div style="background-color: #f0f0f0; padding: 10px; margin-bottom: 20px; border-left: 4px solid #007bff;">
    <strong>About Bundling Rules</strong>
    <p>Bundling Rules define how multiple worksheet tasks combine into a single estimate line item. They work with Task Mappings that use "bundle_to_product" or "bundle_to_service" strategies.</p>
    <p><strong>Example:</strong> A cabinet has separate tasks for frame, doors, and hardware. A bundling rule combines these into one line item "Custom Cabinet - cabinet_001" with a total price.</p>
</div>

<p>
    <a href="{% url 'jobs:bundling_rule_create' %}" style="background-color: #007bff; color: white; padding: 5px 10px; text-decoration: none;">Add New Rule</a>
    {% if show_all %}
        | <a href="{% url 'jobs:bundling_rule_list' %}">Hide Inactive</a>
    {% else %}
        | <a href="{% url 'jobs:bundling_rule_list' %}?show_all=1">Show All</a>
    {% endif %}
</p>

{% if rules %}
<table border="1">
    <thead>
        <tr>
            <th>Rule Name</th>
            <th>Product Type</th>
            <th>Line Item Template</th>
            <th>Pricing Method</th>
            <th>Combine?</th>
            <th>Active</th>
            <th>Actions</th>
        </tr>
    </thead>
    <tbody>
        {% for rule in rules %}
        <tr{% if not rule.is_active %} style="opacity: 0.5;"{% endif %}>
            <td>{{ rule.rule_name }}</td>
            <td>{{ rule.product_type }}</td>
            <td>{{ rule.line_item_template }}</td>
            <td>{{ rule.get_pricing_method_display }}</td>
            <td>{% if rule.combine_instances %}Yes{% else %}No{% endif %}</td>
            <td>{% if rule.is_active %}Yes{% else %}No{% endif %}</td>
            <td>
                <a href="{% url 'jobs:bundling_rule_detail' rule.pk %}">View</a> |
                <a href="{% url 'jobs:bundling_rule_edit' rule.pk %}">Edit</a>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p>No bundling rules found. <a href="{% url 'jobs:bundling_rule_create' %}">Create your first rule</a>.</p>
{% endif %}

<h3>How Bundling Works</h3>
<ol>
    <li>Tasks with <code>bundle_to_product</code> mapping strategy are grouped by product_identifier</li>
    <li>The bundling rule matching the product_type is applied</li>
    <li>Component prices are combined based on the pricing method</li>
    <li>One line item is created with the template name (e.g., "Custom Cabinet - cabinet_001")</li>
</ol>

<p><a href="{% url 'settings' %}">Back to Settings</a></p>
{% endblock %}
```

**Step 7: Update settings.html to add link**

Add under Templates section:
```html
<li><a href="{% url 'jobs:bundling_rule_list' %}">Product Bundling Rules</a></li>
```

**Step 8: Run tests**

Run: `python manage.py test tests.test_bundling_rule_views.TestBundlingRuleListView -v 2`
Expected: PASS (ignoring the URL errors for create/detail/edit which we'll add next)

Note: Template references URLs that don't exist yet. Tests only check list rendering.


---

## Task 7: ProductBundlingRule Create View and Form

**Files:**
- Modify: `apps/jobs/forms.py` (add ProductBundlingRuleForm)
- Modify: `apps/jobs/views.py` (add bundling_rule_create)
- Modify: `apps/jobs/urls.py` (add URL)
- Create: `templates/jobs/bundling_rule_form.html`
- Modify: `tests/test_bundling_rule_views.py` (add tests)

**Step 1: Write failing test**

```python
# Add to tests/test_bundling_rule_views.py:

class TestBundlingRuleCreateView(TestCase):
    def test_create_view_renders_form(self):
        """GET bundling_rule_create shows the form."""
        response = self.client.get(reverse('jobs:bundling_rule_create'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Bundling Rule')

    def test_create_view_saves_rule(self):
        """POST with valid data creates a ProductBundlingRule."""
        data = {
            'rule_name': 'New Test Rule',
            'product_type': 'table',
            'line_item_template': 'Custom {product_type}',
            'combine_instances': True,
            'pricing_method': 'sum_components',
            'include_materials': True,
            'include_labor': True,
            'include_overhead': False,
            'priority': 100,
            'is_active': True,
        }
        response = self.client.post(reverse('jobs:bundling_rule_create'), data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(ProductBundlingRule.objects.filter(rule_name='New Test Rule').exists())
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_bundling_rule_views.TestBundlingRuleCreateView -v 2`
Expected: FAIL with "NoReverseMatch"

**Step 3: Add ProductBundlingRuleForm to forms.py**

```python
# In apps/jobs/forms.py, add:

class ProductBundlingRuleForm(forms.ModelForm):
    """Form for creating/editing ProductBundlingRules with explanatory help text."""

    class Meta:
        model = ProductBundlingRule
        fields = [
            'rule_name', 'product_type', 'work_order_template',
            'line_item_template', 'combine_instances',
            'pricing_method', 'include_materials', 'include_labor', 'include_overhead',
            'priority', 'is_active'
        ]
        help_texts = {
            'rule_name': 'Descriptive name for this rule (e.g., "Cabinet Bundler")',
            'product_type': 'Must match TaskMapping.default_product_type (e.g., "cabinet", "table")',
            'work_order_template': 'Optional. Required if pricing_method is "template_base"',
            'line_item_template': 'Template for line item name. Use {product_type} and {product_identifier} placeholders.',
            'combine_instances': 'If checked, shows "4x Chair" instead of 4 separate line items',
            'pricing_method': 'How to calculate the bundled line item price',
            'include_materials': 'Include material costs in bundle price calculation',
            'include_labor': 'Include labor costs in bundle price calculation',
            'include_overhead': 'Include overhead costs in bundle price calculation (usually excluded from customer-facing price)',
            'priority': 'Lower numbers = higher priority. Used when multiple rules could apply.',
            'is_active': 'Inactive rules are not applied during estimate generation',
        }
```

**Step 4: Add view**

```python
# In apps/jobs/views.py, add:

def bundling_rule_create(request):
    """Create a new ProductBundlingRule."""
    if request.method == 'POST':
        form = ProductBundlingRuleForm(request.POST)
        if form.is_valid():
            rule = form.save()
            messages.success(request, f'Bundling rule "{rule.rule_name}" created successfully.')
            return redirect('jobs:bundling_rule_list')
    else:
        form = ProductBundlingRuleForm()

    return render(request, 'jobs/bundling_rule_form.html', {
        'form': form,
        'title': 'Create Bundling Rule',
        'submit_label': 'Create',
    })
```

**Step 5: Add URL pattern**

```python
# In apps/jobs/urls.py, add:
path('bundling-rules/create/', views.bundling_rule_create, name='bundling_rule_create'),
```

**Step 6: Add import for ProductBundlingRuleForm in views.py**

Add to imports: `from .forms import ProductBundlingRuleForm`

**Step 7: Create template**

```html
<!-- templates/jobs/bundling_rule_form.html -->
{% extends 'base.html' %}

{% block title %}{{ title }} - Minibini{% endblock %}

{% block navigation %}
{% include 'includes/settings_navigation.html' %}
{% endblock %}

{% block content %}
<h2>{{ title }}</h2>

<div style="background-color: #f0f0f0; padding: 10px; margin-bottom: 20px; border-left: 4px solid #007bff;">
    <strong>What is a Bundling Rule?</strong>
    <p>Bundling Rules combine multiple worksheet tasks into a single estimate line item. This is used when you want to show customers a product price rather than itemized components.</p>
    <p><strong>How it works:</strong></p>
    <ol>
        <li>Tasks with Task Mappings set to "bundle_to_product" are grouped by their product_identifier</li>
        <li>This rule's <code>product_type</code> must match the TaskMapping's <code>default_product_type</code></li>
        <li>The <code>line_item_template</code> becomes the display name (e.g., "Custom Cabinet - cabinet_001")</li>
        <li>Component prices are summed based on your pricing settings</li>
    </ol>
</div>

<form method="post">
    {% csrf_token %}
    <table>
        {% for field in form %}
        <tr>
            <th><label for="{{ field.id_for_label }}">{{ field.label }}</label></th>
            <td>
                {{ field }}
                {% if field.help_text %}<br><small>{{ field.help_text }}</small>{% endif %}
                {% if field.errors %}<br><span style="color: red;">{{ field.errors }}</span>{% endif %}
            </td>
        </tr>
        {% endfor %}
    </table>
    <p>
        <button type="submit">{{ submit_label }}</button>
        <a href="{% url 'jobs:bundling_rule_list' %}">Cancel</a>
    </p>
</form>
{% endblock %}
```

**Step 8: Run tests**

Run: `python manage.py test tests.test_bundling_rule_views.TestBundlingRuleCreateView -v 2`
Expected: PASS


---

## Task 8: ProductBundlingRule Detail View

**Files:**
- Modify: `apps/jobs/views.py` (add bundling_rule_detail)
- Modify: `apps/jobs/urls.py` (add URL)
- Create: `templates/jobs/bundling_rule_detail.html`
- Modify: `tests/test_bundling_rule_views.py` (add tests)

**Step 1: Write failing test**

```python
# Add to tests/test_bundling_rule_views.py:

class TestBundlingRuleDetailView(TestCase):
    def setUp(self):
        self.rule = ProductBundlingRule.objects.create(
            rule_name='Detail Test Rule',
            product_type='cabinet',
            line_item_template='Custom {product_type} - {product_identifier}',
            pricing_method='sum_components'
        )

    def test_detail_view_shows_rule(self):
        """GET bundling_rule_detail shows the rule details."""
        response = self.client.get(
            reverse('jobs:bundling_rule_detail', args=[self.rule.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Detail Test Rule')
        self.assertContains(response, 'cabinet')
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_bundling_rule_views.TestBundlingRuleDetailView -v 2`
Expected: FAIL with "NoReverseMatch"

**Step 3: Add view**

```python
# In apps/jobs/views.py, add:

def bundling_rule_detail(request, pk):
    """Display ProductBundlingRule details."""
    rule = get_object_or_404(ProductBundlingRule, pk=pk)
    # Find matching TaskMappings
    matching_mappings = TaskMapping.objects.filter(
        default_product_type=rule.product_type,
        mapping_strategy__in=['bundle_to_product', 'bundle_to_service']
    )
    return render(request, 'jobs/bundling_rule_detail.html', {
        'rule': rule,
        'matching_mappings': matching_mappings,
    })
```

**Step 4: Add URL pattern**

```python
# In apps/jobs/urls.py, add:
path('bundling-rules/<int:pk>/', views.bundling_rule_detail, name='bundling_rule_detail'),
```

**Step 5: Create template**

```html
<!-- templates/jobs/bundling_rule_detail.html -->
{% extends 'base.html' %}

{% block title %}Bundling Rule: {{ rule.rule_name }} - Minibini{% endblock %}

{% block navigation %}
{% include 'includes/settings_navigation.html' %}
{% endblock %}

{% block content %}
<h2>Bundling Rule: {{ rule.rule_name }}</h2>

<table border="1">
    <tr><th>Rule Name</th><td>{{ rule.rule_name }}</td></tr>
    <tr><th>Product Type</th><td>{{ rule.product_type }}</td></tr>
    <tr><th>Work Order Template</th><td>{% if rule.work_order_template %}{{ rule.work_order_template.template_name }}{% else %}-{% endif %}</td></tr>
    <tr><th>Line Item Template</th><td><code>{{ rule.line_item_template }}</code></td></tr>
    <tr><th>Combine Instances</th><td>{% if rule.combine_instances %}Yes - "4x Chair"{% else %}No - separate lines{% endif %}</td></tr>
    <tr><th>Pricing Method</th><td>{{ rule.get_pricing_method_display }}</td></tr>
    <tr><th>Include Materials</th><td>{% if rule.include_materials %}Yes{% else %}No{% endif %}</td></tr>
    <tr><th>Include Labor</th><td>{% if rule.include_labor %}Yes{% else %}No{% endif %}</td></tr>
    <tr><th>Include Overhead</th><td>{% if rule.include_overhead %}Yes{% else %}No{% endif %}</td></tr>
    <tr><th>Priority</th><td>{{ rule.priority }}</td></tr>
    <tr><th>Active</th><td>{% if rule.is_active %}Yes{% else %}No{% endif %}</td></tr>
</table>

<p>
    <a href="{% url 'jobs:bundling_rule_edit' rule.pk %}">Edit</a> |
    <a href="{% url 'jobs:bundling_rule_list' %}">Back to List</a>
</p>

<h3>Matching Task Mappings</h3>
<p>These Task Mappings use product_type "{{ rule.product_type }}" and will apply this bundling rule:</p>
{% if matching_mappings %}
<ul>
    {% for mapping in matching_mappings %}
    <li><a href="{% url 'jobs:task_mapping_detail' mapping.pk %}">{{ mapping.task_type_id }}</a> ({{ mapping.get_mapping_strategy_display }})</li>
    {% endfor %}
</ul>
{% else %}
<p><em>No Task Mappings currently match this product type. Create a Task Mapping with default_product_type="{{ rule.product_type }}" and a bundle mapping strategy.</em></p>
{% endif %}

{% endblock %}
```

**Step 6: Run tests**

Run: `python manage.py test tests.test_bundling_rule_views.TestBundlingRuleDetailView -v 2`
Expected: PASS


---

## Task 9: ProductBundlingRule Edit View

**Files:**
- Modify: `apps/jobs/views.py` (add bundling_rule_edit)
- Modify: `apps/jobs/urls.py` (add URL)
- Modify: `tests/test_bundling_rule_views.py` (add tests)

**Step 1: Write failing test**

```python
# Add to tests/test_bundling_rule_views.py:

class TestBundlingRuleEditView(TestCase):
    def setUp(self):
        self.rule = ProductBundlingRule.objects.create(
            rule_name='Edit Test Rule',
            product_type='table',
            line_item_template='Original Template',
            pricing_method='sum_components'
        )

    def test_edit_view_renders_form(self):
        """GET bundling_rule_edit shows form with existing data."""
        response = self.client.get(
            reverse('jobs:bundling_rule_edit', args=[self.rule.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit Test Rule')

    def test_edit_view_updates_rule(self):
        """POST with valid data updates the ProductBundlingRule."""
        data = {
            'rule_name': 'Updated Rule Name',
            'product_type': 'table',
            'line_item_template': 'Updated Template',
            'combine_instances': False,
            'pricing_method': 'sum_components',
            'include_materials': True,
            'include_labor': True,
            'include_overhead': True,
            'priority': 50,
            'is_active': True,
        }
        response = self.client.post(
            reverse('jobs:bundling_rule_edit', args=[self.rule.pk]),
            data
        )
        self.assertEqual(response.status_code, 302)
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.rule_name, 'Updated Rule Name')
        self.assertEqual(self.rule.priority, 50)
        self.assertTrue(self.rule.include_overhead)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_bundling_rule_views.TestBundlingRuleEditView -v 2`
Expected: FAIL with "NoReverseMatch"

**Step 3: Add view**

```python
# In apps/jobs/views.py, add:

def bundling_rule_edit(request, pk):
    """Edit an existing ProductBundlingRule."""
    rule = get_object_or_404(ProductBundlingRule, pk=pk)

    if request.method == 'POST':
        form = ProductBundlingRuleForm(request.POST, instance=rule)
        if form.is_valid():
            form.save()
            messages.success(request, f'Bundling rule "{rule.rule_name}" updated successfully.')
            return redirect('jobs:bundling_rule_detail', pk=rule.pk)
    else:
        form = ProductBundlingRuleForm(instance=rule)

    return render(request, 'jobs/bundling_rule_form.html', {
        'form': form,
        'rule': rule,
        'title': f'Edit Bundling Rule: {rule.rule_name}',
        'submit_label': 'Save Changes',
    })
```

**Step 4: Add URL pattern**

```python
# In apps/jobs/urls.py, add:
path('bundling-rules/<int:pk>/edit/', views.bundling_rule_edit, name='bundling_rule_edit'),
```

**Step 5: Run tests**

Run: `python manage.py test tests.test_bundling_rule_views.TestBundlingRuleEditView -v 2`
Expected: PASS


---

## Task 10: ProductBundlingRule Delete View

**Files:**
- Modify: `apps/jobs/views.py` (add bundling_rule_delete)
- Modify: `apps/jobs/urls.py` (add URL)
- Modify: `templates/jobs/bundling_rule_detail.html` (add delete link)
- Modify: `templates/jobs/bundling_rule_list.html` (add delete link)
- Modify: `tests/test_bundling_rule_views.py` (add tests)

**Note:** ProductBundlingRules are configuration objects used only during estimate generation. They are NOT stored with line items or other output data, so they can be permanently deleted rather than archived.

**Step 1: Write failing test**

```python
# Add to tests/test_bundling_rule_views.py:

class TestBundlingRuleDeleteView(TestCase):
    def setUp(self):
        self.rule = ProductBundlingRule.objects.create(
            rule_name='Delete Test Rule',
            product_type='chair',
            line_item_template='Custom {product_type}',
            pricing_method='sum_components'
        )

    def test_delete_view_shows_confirmation(self):
        """GET bundling_rule_delete shows confirmation page."""
        response = self.client.get(
            reverse('jobs:bundling_rule_delete', args=[self.rule.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Delete Test Rule')
        self.assertContains(response, 'Are you sure')

    def test_delete_view_deletes_rule(self):
        """POST deletes the ProductBundlingRule."""
        response = self.client.post(
            reverse('jobs:bundling_rule_delete', args=[self.rule.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProductBundlingRule.objects.filter(pk=self.rule.pk).exists())
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_bundling_rule_views.TestBundlingRuleDeleteView -v 2`
Expected: FAIL with "NoReverseMatch"

**Step 3: Add view**

```python
# In apps/jobs/views.py, add:

def bundling_rule_delete(request, pk):
    """Delete a ProductBundlingRule."""
    rule = get_object_or_404(ProductBundlingRule, pk=pk)

    if request.method == 'POST':
        rule_name = rule.rule_name
        rule.delete()
        messages.success(request, f'Bundling rule "{rule_name}" deleted.')
        return redirect('jobs:bundling_rule_list')

    return render(request, 'jobs/bundling_rule_confirm_delete.html', {
        'rule': rule,
    })
```

**Step 4: Add URL pattern**

```python
# In apps/jobs/urls.py, add:
path('bundling-rules/<int:pk>/delete/', views.bundling_rule_delete, name='bundling_rule_delete'),
```

**Step 5: Create confirmation template**

```html
<!-- templates/jobs/bundling_rule_confirm_delete.html -->
{% extends 'base.html' %}

{% block title %}Delete Bundling Rule - Minibini{% endblock %}

{% block navigation %}
{% include 'includes/settings_navigation.html' %}
{% endblock %}

{% block content %}
<h2>Delete Bundling Rule: {{ rule.rule_name }}</h2>

<div style="background-color: #fff3cd; padding: 10px; margin-bottom: 20px; border-left: 4px solid #ffc107;">
    <strong>Are you sure you want to delete this bundling rule?</strong>
    <p>This action cannot be undone. The rule "{{ rule.rule_name }}" will be permanently removed.</p>
    <p><em>Note: This is safe because Bundling Rules are only used during estimate generation and are not stored with line items. Existing estimates will not be affected.</em></p>
</div>

<table border="1" style="margin-bottom: 20px;">
    <tr><th>Rule Name</th><td>{{ rule.rule_name }}</td></tr>
    <tr><th>Product Type</th><td>{{ rule.product_type }}</td></tr>
    <tr><th>Line Item Template</th><td>{{ rule.line_item_template }}</td></tr>
</table>

<form method="post">
    {% csrf_token %}
    <button type="submit" style="background-color: #dc3545; color: white; padding: 5px 15px;">Delete</button>
    <a href="{% url 'jobs:bundling_rule_detail' rule.pk %}">Cancel</a>
</form>
{% endblock %}
```

**Step 6: Update detail template to add delete link**

In `templates/jobs/bundling_rule_detail.html`, update the actions paragraph:
```html
<p>
    <a href="{% url 'jobs:bundling_rule_edit' rule.pk %}">Edit</a> |
    <a href="{% url 'jobs:bundling_rule_delete' rule.pk %}" style="color: #dc3545;">Delete</a> |
    <a href="{% url 'jobs:bundling_rule_list' %}">Back to List</a>
</p>
```

**Step 7: Update list template to add delete link**

In `templates/jobs/bundling_rule_list.html`, update the Actions column:
```html
<td>
    <a href="{% url 'jobs:bundling_rule_detail' rule.pk %}">View</a> |
    <a href="{% url 'jobs:bundling_rule_edit' rule.pk %}">Edit</a> |
    <a href="{% url 'jobs:bundling_rule_delete' rule.pk %}" style="color: #dc3545;">Delete</a>
</td>
```

**Step 8: Run tests**

Run: `python manage.py test tests.test_bundling_rule_views.TestBundlingRuleDeleteView -v 2`
Expected: PASS


---

## Task 11: Final Integration and Cleanup

**Files:**
- Verify all links work in templates
- Run full test suite
- Update settings navigation if needed

**Step 1: Run all new tests**

Run: `python manage.py test tests.test_task_mapping_views tests.test_bundling_rule_views -v 2`
Expected: All tests PASS

**Step 2: Run full test suite**

Run: `python manage.py test`
Expected: All tests PASS

**Step 3: Manual verification**

Visit these URLs and verify they work:
- `/settings/` - Should show links to both Task Mappings and Product Bundling Rules
- `/jobs/task-mappings/` - List with Add/View/Edit links
- `/jobs/task-mappings/create/` - Form with explanatory text
- `/jobs/bundling-rules/` - List with Add/View/Edit links
- `/jobs/bundling-rules/create/` - Form with explanatory text


---

## Summary

This plan adds:
1. **TaskMapping CRUD** - 5 views (list updated with links; create, detail, edit, delete added)
2. **ProductBundlingRule CRUD** - 5 views (list, create, detail, edit, delete)
3. **2 Forms** with comprehensive help_text for every field
4. **8 Templates** with explanatory blocks explaining what each model does
5. **2 Test files** covering all views including delete protection
6. **Settings page update** with link to bundling rules

**Delete behavior:**
- TaskMappings and ProductBundlingRules can be permanently deleted (not just archived) because they are configuration objects used only during estimate generation - they are NOT stored with output data like line items
- TaskMapping delete is blocked if any TaskTemplates are still using it
- ProductBundlingRule delete is allowed freely since rules are matched by product_type, not FK

All forms include inline explanations so users understand the complex relationship between TaskMapping strategy, ProductBundlingRule, and how tasks become line items.
