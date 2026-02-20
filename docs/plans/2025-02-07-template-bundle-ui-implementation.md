# Template Bundle UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add UI for creating TemplateBundles within WorkOrderTemplates via checkbox multi-select.

**Architecture:** Update the work_order_template_detail view to handle bundle creation, update the template to show checkboxes and visual grouping, update fixtures with bundling examples.

**Tech Stack:** Django views, Django templates, HTML/CSS for visual grouping

---

### Task 1: Add bundle context to view

**Files:**
- Modify: `apps/jobs/views.py:360-416` (work_order_template_detail function)

**Step 1: Update the view to include bundles and line_item_types in context**

In `apps/jobs/views.py`, update the `work_order_template_detail` function. Add these imports at the top of the function and update the context:

```python
def work_order_template_detail(request, template_id):
    template = get_object_or_404(WorkOrderTemplate, template_id=template_id)

    # ... existing POST handlers ...

    # Get task template associations with bundle info
    from .models import TemplateTaskAssociation, TemplateBundle
    from apps.core.models import LineItemType

    associations = TemplateTaskAssociation.objects.filter(
        work_order_template=template,
        task_template__is_active=True
    ).select_related('task_template', 'bundle').order_by('sort_order', 'task_template__template_name')

    # Group associations: bundled first (grouped by bundle), then direct, then excluded
    bundled = []
    direct = []
    excluded = []

    for assoc in associations:
        if assoc.mapping_strategy == 'bundle' and assoc.bundle:
            bundled.append(assoc)
        elif assoc.mapping_strategy == 'exclude':
            excluded.append(assoc)
        else:
            direct.append(assoc)

    # Group bundled associations by their bundle
    from itertools import groupby
    bundled_sorted = sorted(bundled, key=lambda a: (a.bundle.sort_order, a.bundle.name))
    bundled_groups = []
    for bundle, group in groupby(bundled_sorted, key=lambda a: a.bundle):
        bundled_groups.append({
            'bundle': bundle,
            'associations': list(group)
        })

    # Get available task templates (not yet associated)
    associated_task_ids = associations.values_list('task_template_id', flat=True)
    available_templates = TaskTemplate.objects.filter(is_active=True).exclude(template_id__in=associated_task_ids)

    # Get line item types for bundle form
    line_item_types = LineItemType.objects.all().order_by('name')

    return render(request, 'jobs/work_order_template_detail.html', {
        'template': template,
        'bundled_groups': bundled_groups,
        'direct_associations': direct,
        'excluded_associations': excluded,
        'associations': associations,  # Keep for backward compat
        'available_templates': available_templates,
        'line_item_types': line_item_types,
    })
```

**Step 2: Run Django check**

Run: `python manage.py check`
Expected: No errors

**Step 3: Commit**

```bash
git add apps/jobs/views.py
git commit -m "feat: add bundle context to work_order_template_detail view"
```

---

### Task 2: Add bundle creation POST handler

**Files:**
- Modify: `apps/jobs/views.py:360-416` (work_order_template_detail function)

**Step 1: Add the bundle_tasks POST handler**

Add this handler after the existing `remove_task` handler (around line 399):

```python
    # Handle bundle creation
    if request.method == 'POST' and 'bundle_tasks' in request.POST:
        from .models import TemplateTaskAssociation, TemplateBundle
        from apps.core.models import LineItemType

        # Get selected association IDs
        selected_ids = request.POST.getlist('selected_tasks')
        bundle_name = request.POST.get('bundle_name', '').strip()
        bundle_description = request.POST.get('bundle_description', '').strip()
        line_item_type_id = request.POST.get('line_item_type')

        if len(selected_ids) < 2:
            messages.error(request, 'Please select at least 2 tasks to bundle.')
        elif not bundle_name:
            messages.error(request, 'Bundle name is required.')
        elif not line_item_type_id:
            messages.error(request, 'Line item type is required.')
        else:
            line_item_type = get_object_or_404(LineItemType, pk=line_item_type_id)

            # Get next sort order for bundles
            max_sort = TemplateBundle.objects.filter(
                work_order_template=template
            ).aggregate(models.Max('sort_order'))['sort_order__max']
            next_sort = (max_sort or 0) + 1

            # Create the bundle
            bundle = TemplateBundle.objects.create(
                work_order_template=template,
                name=bundle_name,
                description=bundle_description,
                line_item_type=line_item_type,
                sort_order=next_sort
            )

            # Update selected associations
            updated = TemplateTaskAssociation.objects.filter(
                pk__in=selected_ids,
                work_order_template=template
            ).update(mapping_strategy='bundle', bundle=bundle)

            messages.success(request, f'Bundle "{bundle_name}" created with {updated} tasks.')

        return redirect('jobs:work_order_template_detail', template_id=template_id)
```

**Step 2: Run Django check**

Run: `python manage.py check`
Expected: No errors

**Step 3: Commit**

```bash
git add apps/jobs/views.py
git commit -m "feat: add bundle_tasks POST handler"
```

---

### Task 3: Update template with checkboxes and bundle form

**Files:**
- Modify: `templates/jobs/work_order_template_detail.html`

**Step 1: Replace the task templates table with new structure**

Replace the entire content of `work_order_template_detail.html` with:

```html
{% extends 'base.html' %}

{% block title %}{{ template.template_name }} - Minibini{% endblock %}

{% block navigation %}
{% include 'includes/settings_navigation.html' %}
{% endblock %}

{% block content %}
<style>
    .bundle-group {
        background-color: #f0f7ff;
        border-left: 4px solid #4a90d9;
        margin: 10px 0;
        padding: 5px 0;
    }
    .bundle-header {
        padding: 5px 10px;
        font-weight: bold;
        color: #2c5282;
    }
    .bundle-group table {
        margin: 0;
        background: transparent;
    }
    .excluded-task {
        opacity: 0.5;
        font-style: italic;
    }
</style>

<h2>Work Order Template: {{ template.template_name }}</h2>

<table border="1">
    <tr><th>Field</th><th>Value</th></tr>
    <tr><td>Template ID</td><td>{{ template.template_id }}</td></tr>
    <tr><td>Template Name</td><td>{{ template.template_name }}</td></tr>
    <tr><td>Description</td><td>{{ template.description|default:"-" }}</td></tr>
    <tr><td>Active</td><td>{{ template.is_active|yesno:"Yes,No" }}</td></tr>
    <tr><td>Created Date</td><td>{{ template.created_date }}</td></tr>
</table>

<h3>Task Templates</h3>

<form method="post" id="task-form">
    {% csrf_token %}

    {% if bundled_groups %}
    {% for group in bundled_groups %}
    <div class="bundle-group">
        <div class="bundle-header">
            Bundle: "{{ group.bundle.name }}" ({{ group.bundle.line_item_type.name }})
        </div>
        <table border="1">
            <tr>
                <th style="width: 30px;"></th>
                <th>Task Name</th>
                <th>Description</th>
                <th>Units</th>
                <th>Rate</th>
                <th>Est. Qty</th>
                <th>Action</th>
            </tr>
            {% for association in group.associations %}
            <tr>
                <td><input type="checkbox" name="selected_tasks" value="{{ association.pk }}"></td>
                <td>{{ association.task_template.template_name }}</td>
                <td>{{ association.task_template.description|truncatewords:10|default:"-" }}</td>
                <td>{{ association.task_template.units|default:"-" }}</td>
                <td>${{ association.task_template.rate|default:"0.00" }}</td>
                <td>{{ association.est_qty }}</td>
                <td>
                    <button type="submit" name="remove_task" value="{{ association.task_template.template_id }}"
                            onclick="return confirm('Remove this task template?')">Remove</button>
                    <input type="hidden" name="task_template_id" value="{{ association.task_template.template_id }}">
                </td>
            </tr>
            {% endfor %}
        </table>
    </div>
    {% endfor %}
    {% endif %}

    {% if direct_associations %}
    <table border="1">
        <tr>
            <th style="width: 30px;"></th>
            <th>Task Name</th>
            <th>Description</th>
            <th>Units</th>
            <th>Rate</th>
            <th>Est. Qty</th>
            <th>Mapping</th>
            <th>Action</th>
        </tr>
        {% for association in direct_associations %}
        <tr>
            <td><input type="checkbox" name="selected_tasks" value="{{ association.pk }}"></td>
            <td>{{ association.task_template.template_name }}</td>
            <td>{{ association.task_template.description|truncatewords:10|default:"-" }}</td>
            <td>{{ association.task_template.units|default:"-" }}</td>
            <td>${{ association.task_template.rate|default:"0.00" }}</td>
            <td>{{ association.est_qty }}</td>
            <td>Direct</td>
            <td>
                <button type="submit" name="remove_task" value="{{ association.task_template.template_id }}"
                        onclick="return confirm('Remove this task template?')">Remove</button>
                <input type="hidden" name="task_template_id" value="{{ association.task_template.template_id }}">
            </td>
        </tr>
        {% endfor %}
    </table>
    {% endif %}

    {% if excluded_associations %}
    <h4>Excluded (Internal Only)</h4>
    <table border="1">
        <tr>
            <th style="width: 30px;"></th>
            <th>Task Name</th>
            <th>Description</th>
            <th>Units</th>
            <th>Rate</th>
            <th>Est. Qty</th>
            <th>Action</th>
        </tr>
        {% for association in excluded_associations %}
        <tr class="excluded-task">
            <td><input type="checkbox" name="selected_tasks" value="{{ association.pk }}"></td>
            <td>{{ association.task_template.template_name }}</td>
            <td>{{ association.task_template.description|truncatewords:10|default:"-" }}</td>
            <td>{{ association.task_template.units|default:"-" }}</td>
            <td>${{ association.task_template.rate|default:"0.00" }}</td>
            <td>{{ association.est_qty }}</td>
            <td>
                <button type="submit" name="remove_task" value="{{ association.task_template.template_id }}"
                        onclick="return confirm('Remove this task template?')">Remove</button>
                <input type="hidden" name="task_template_id" value="{{ association.task_template.template_id }}">
            </td>
        </tr>
        {% endfor %}
    </table>
    {% endif %}

    {% if not bundled_groups and not direct_associations and not excluded_associations %}
    <p>No task templates found for this work order template.</p>
    {% endif %}

    <h4>Create Bundle from Selected Tasks</h4>
    <div style="border: 1px solid #ccc; padding: 10px; margin: 10px 0;">
        <div>
            <label for="bundle_name">Bundle Name:</label>
            <input type="text" name="bundle_name" id="bundle_name" style="width: 200px;">
        </div>
        <div>
            <label for="bundle_description">Description (optional):</label>
            <input type="text" name="bundle_description" id="bundle_description" style="width: 300px;">
        </div>
        <div>
            <label for="line_item_type">Line Item Type:</label>
            <select name="line_item_type" id="line_item_type">
                <option value="">-- Select Type --</option>
                {% for lit in line_item_types %}
                <option value="{{ lit.pk }}">{{ lit.name }}</option>
                {% endfor %}
            </select>
        </div>
        <div style="margin-top: 10px;">
            <button type="submit" name="bundle_tasks">Bundle Selected Tasks</button>
        </div>
    </div>
</form>

{% if available_templates %}
<h4>Associate Existing Task Template</h4>
<form method="post">
    {% csrf_token %}
    <div>
        <label for="task_template_id">Task Template:</label>
        <select name="task_template_id" required>
            <option value="">-- Select Task Template --</option>
            {% for task in available_templates %}
            <option value="{{ task.template_id }}">{{ task.template_name }} ({{ task.units|default:"no units" }}, ${{ task.rate|default:"0.00" }})</option>
            {% endfor %}
        </select>
    </div>
    <div>
        <label for="est_qty">Estimated Quantity:</label>
        <input type="number" name="est_qty" step="0.01" value="1.00" min="0" required>
    </div>
    <button type="submit" name="associate_task">Associate Task Template</button>
</form>
{% else %}
<h4>All available task templates are already associated with this work order template.</h4>
{% endif %}

<p>
    <a href="{% url 'jobs:work_order_template_list' %}">Back to Templates List</a>
</p>

{% endblock %}
```

**Step 2: Run Django check**

Run: `python manage.py check`
Expected: No errors

**Step 3: Commit**

```bash
git add templates/jobs/work_order_template_detail.html
git commit -m "feat: add checkbox selection and bundle form to template detail"
```

---

### Task 4: Write tests for bundle creation

**Files:**
- Create: `tests/test_template_bundle_ui.py`

**Step 1: Create the test file**

```python
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.jobs.models import (
    WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation, TemplateBundle
)
from apps.core.models import LineItemType

User = get_user_model()


class TemplateBundleUITest(TestCase):
    """Test the Template Bundle UI functionality"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')

        # Create a line item type
        self.line_item_type = LineItemType.objects.create(
            name="Labor", code="LBR"
        )

        # Create work order template
        self.wo_template = WorkOrderTemplate.objects.create(
            template_name="Test WO Template"
        )

        # Create task templates
        self.task1 = TaskTemplate.objects.create(
            template_name="Task 1", rate=50
        )
        self.task2 = TaskTemplate.objects.create(
            template_name="Task 2", rate=75
        )
        self.task3 = TaskTemplate.objects.create(
            template_name="Task 3", rate=100
        )

        # Create associations
        self.assoc1 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task1,
            est_qty=1,
            sort_order=1
        )
        self.assoc2 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task2,
            est_qty=2,
            sort_order=2
        )
        self.assoc3 = TemplateTaskAssociation.objects.create(
            work_order_template=self.wo_template,
            task_template=self.task3,
            est_qty=3,
            sort_order=3
        )

    def test_bundle_creation_success(self):
        """Test successfully creating a bundle from selected tasks"""
        url = reverse('jobs:work_order_template_detail',
                      kwargs={'template_id': self.wo_template.template_id})

        response = self.client.post(url, {
            'bundle_tasks': 'true',
            'selected_tasks': [self.assoc1.pk, self.assoc2.pk],
            'bundle_name': 'Test Bundle',
            'bundle_description': 'A test bundle',
            'line_item_type': self.line_item_type.pk
        }, follow=True)

        self.assertEqual(response.status_code, 200)

        # Verify bundle was created
        bundle = TemplateBundle.objects.get(
            work_order_template=self.wo_template,
            name='Test Bundle'
        )
        self.assertEqual(bundle.line_item_type, self.line_item_type)
        self.assertEqual(bundle.description, 'A test bundle')

        # Verify associations were updated
        self.assoc1.refresh_from_db()
        self.assoc2.refresh_from_db()
        self.assoc3.refresh_from_db()

        self.assertEqual(self.assoc1.mapping_strategy, 'bundle')
        self.assertEqual(self.assoc1.bundle, bundle)
        self.assertEqual(self.assoc2.mapping_strategy, 'bundle')
        self.assertEqual(self.assoc2.bundle, bundle)
        # assoc3 should remain unchanged
        self.assertEqual(self.assoc3.mapping_strategy, 'direct')
        self.assertIsNone(self.assoc3.bundle)

    def test_bundle_creation_requires_two_tasks(self):
        """Test that bundling requires at least 2 tasks"""
        url = reverse('jobs:work_order_template_detail',
                      kwargs={'template_id': self.wo_template.template_id})

        response = self.client.post(url, {
            'bundle_tasks': 'true',
            'selected_tasks': [self.assoc1.pk],  # Only 1 task
            'bundle_name': 'Test Bundle',
            'line_item_type': self.line_item_type.pk
        }, follow=True)

        # Should show error message
        messages = list(response.context['messages'])
        self.assertTrue(any('at least 2 tasks' in str(m) for m in messages))

        # No bundle should be created
        self.assertEqual(TemplateBundle.objects.count(), 0)

    def test_bundle_creation_requires_name(self):
        """Test that bundle name is required"""
        url = reverse('jobs:work_order_template_detail',
                      kwargs={'template_id': self.wo_template.template_id})

        response = self.client.post(url, {
            'bundle_tasks': 'true',
            'selected_tasks': [self.assoc1.pk, self.assoc2.pk],
            'bundle_name': '',  # Empty name
            'line_item_type': self.line_item_type.pk
        }, follow=True)

        messages = list(response.context['messages'])
        self.assertTrue(any('name is required' in str(m) for m in messages))
        self.assertEqual(TemplateBundle.objects.count(), 0)

    def test_bundle_creation_requires_line_item_type(self):
        """Test that line item type is required"""
        url = reverse('jobs:work_order_template_detail',
                      kwargs={'template_id': self.wo_template.template_id})

        response = self.client.post(url, {
            'bundle_tasks': 'true',
            'selected_tasks': [self.assoc1.pk, self.assoc2.pk],
            'bundle_name': 'Test Bundle',
            'line_item_type': ''  # No type
        }, follow=True)

        messages = list(response.context['messages'])
        self.assertTrue(any('Line item type is required' in str(m) for m in messages))
        self.assertEqual(TemplateBundle.objects.count(), 0)

    def test_bundled_tasks_display_grouped(self):
        """Test that bundled tasks appear grouped in the UI"""
        # Create a bundle first
        bundle = TemplateBundle.objects.create(
            work_order_template=self.wo_template,
            name="Existing Bundle",
            line_item_type=self.line_item_type
        )
        self.assoc1.mapping_strategy = 'bundle'
        self.assoc1.bundle = bundle
        self.assoc1.save()
        self.assoc2.mapping_strategy = 'bundle'
        self.assoc2.bundle = bundle
        self.assoc2.save()

        url = reverse('jobs:work_order_template_detail',
                      kwargs={'template_id': self.wo_template.template_id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Existing Bundle')
        self.assertContains(response, 'bundle-group')
```

**Step 2: Run the tests**

Run: `python manage.py test tests.test_template_bundle_ui --keepdb -v 2`
Expected: All tests pass

**Step 3: Commit**

```bash
git add tests/test_template_bundle_ui.py
git commit -m "test: add tests for template bundle UI"
```

---

### Task 5: Update fixtures with bundling examples

**Files:**
- Modify: `fixtures/template_test_data.json`

**Step 1: Update the fixture to include a TemplateBundle and mapping_strategy**

Add these entries to the fixture. Insert the LineItemType and TemplateBundle before the associations, then update some associations:

Add after the TaskTemplate entries (before TemplateTaskAssociation entries):

```json
    {
        "model": "core.lineitemtype",
        "pk": 100,
        "fields": {
            "name": "Electrical Work",
            "code": "ELEC"
        }
    },
    {
        "model": "core.lineitemtype",
        "pk": 101,
        "fields": {
            "name": "Plumbing Work",
            "code": "PLMB"
        }
    },
    {
        "model": "jobs.templatebundle",
        "pk": 1,
        "fields": {
            "work_order_template": 1,
            "name": "Complete Electrical",
            "description": "All electrical installation tasks bundled together",
            "line_item_type": 100,
            "sort_order": 1
        }
    },
    {
        "model": "jobs.templatebundle",
        "pk": 2,
        "fields": {
            "work_order_template": 1,
            "name": "Complete Plumbing",
            "description": "All plumbing installation tasks bundled together",
            "line_item_type": 101,
            "sort_order": 2
        }
    },
```

Update the TemplateTaskAssociation entries to include mapping_strategy and bundle:

```json
    {
        "model": "jobs.templatetaskassociation",
        "pk": 1,
        "fields": {
            "work_order_template": 1,
            "task_template": 1,
            "est_qty": "10.00",
            "sort_order": 1,
            "mapping_strategy": "bundle",
            "bundle": 1
        }
    },
    {
        "model": "jobs.templatetaskassociation",
        "pk": 2,
        "fields": {
            "work_order_template": 1,
            "task_template": 2,
            "est_qty": "150.00",
            "sort_order": 2,
            "mapping_strategy": "bundle",
            "bundle": 1
        }
    },
    {
        "model": "jobs.templatetaskassociation",
        "pk": 3,
        "fields": {
            "work_order_template": 1,
            "task_template": 3,
            "est_qty": "5.00",
            "sort_order": 3,
            "mapping_strategy": "bundle",
            "bundle": 2
        }
    },
    {
        "model": "jobs.templatetaskassociation",
        "pk": 4,
        "fields": {
            "work_order_template": 1,
            "task_template": 4,
            "est_qty": "200.00",
            "sort_order": 4,
            "mapping_strategy": "bundle",
            "bundle": 2
        }
    },
    {
        "model": "jobs.templatetaskassociation",
        "pk": 5,
        "fields": {
            "work_order_template": 1,
            "task_template": 5,
            "est_qty": "400.00",
            "sort_order": 5,
            "mapping_strategy": "direct",
            "bundle": null
        }
    },
    {
        "model": "jobs.templatetaskassociation",
        "pk": 6,
        "fields": {
            "work_order_template": 1,
            "task_template": 6,
            "est_qty": "400.00",
            "sort_order": 6,
            "mapping_strategy": "direct",
            "bundle": null
        }
    },
    {
        "model": "jobs.templatetaskassociation",
        "pk": 7,
        "fields": {
            "work_order_template": 2,
            "task_template": 1,
            "est_qty": "2.00",
            "sort_order": 1,
            "mapping_strategy": "direct",
            "bundle": null
        }
    },
    {
        "model": "jobs.templatetaskassociation",
        "pk": 8,
        "fields": {
            "work_order_template": 2,
            "task_template": 3,
            "est_qty": "1.00",
            "sort_order": 2,
            "mapping_strategy": "direct",
            "bundle": null
        }
    }
```

**Step 2: Verify fixture loads correctly**

Run: `python manage.py loaddata fixtures/template_test_data.json --verbosity 2`
Expected: Fixture loads without errors

**Step 3: Commit**

```bash
git add fixtures/template_test_data.json
git commit -m "feat: add bundling examples to template_test_data fixture"
```

---

### Task 6: Manual verification

**Step 1: Start the development server**

Run: `python manage.py runserver`

**Step 2: Test the workflow**

1. Navigate to `/settings/` and click "Work Order Templates"
2. Click on "Standard Installation" template
3. Verify:
   - "Complete Electrical" bundle appears with grouped tasks (Install Electrical Outlets, Run Electrical Wiring)
   - "Complete Plumbing" bundle appears with grouped tasks (Install Plumbing Fixtures, Run Water Lines)
   - "Frame Walls" and "Install Drywall" appear as Direct tasks
4. Select two Direct tasks using checkboxes
5. Fill in bundle form (name, description, line item type)
6. Click "Bundle Selected Tasks"
7. Verify the new bundle appears with the selected tasks grouped

**Step 3: Run full test suite**

Run: `python manage.py test --keepdb`
Expected: All tests pass

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete template bundle UI implementation"
```
