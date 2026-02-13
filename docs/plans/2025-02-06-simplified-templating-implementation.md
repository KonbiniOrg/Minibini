# Simplified Templating System Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the complex TaskMapping/BundlingRule system with explicit TemplateBundle-based bundling that allows the same TaskTemplate to behave differently in different WorkOrderTemplates.

**Architecture:** New TemplateBundle model groups TemplateTaskAssociations. TaskTemplate gets direct line_item_type. Mapping config (direct/bundle/exclude) moves to TemplateTaskAssociation. Delete TaskMapping, BundlingRule, TaskInstanceMapping models entirely.

**Tech Stack:** Django 4.x, Python 3.11, pytest, SQLite (dev)

**Key Constraint:** This is NOT a deployed system. No data migration needed. Break things freely, fix afterwards.

---

## Phase 1: Scorched Earth - Delete Old System

Delete first, build later. This prevents any temptation to maintain compatibility.

### Task 1: Delete Test Files for Old System

**Files:**
- Delete: `tests/test_task_mapping_views.py`
- Delete: `tests/test_task_mapping_line_item_type.py`
- Delete: `tests/test_bundling_rule_views.py`
- Delete: `tests/test_product_bundling_rule_validation.py`
- Delete: `tests/test_bundling_consolidation.py`
- Delete: `tests/test_hardcoded_descriptions.py`
- Delete: `tests/test_estimate_generation_OLD.py.bak`

**Step 1: Delete the test files**

```bash
rm tests/test_task_mapping_views.py
rm tests/test_task_mapping_line_item_type.py
rm tests/test_bundling_rule_views.py
rm tests/test_product_bundling_rule_validation.py
rm tests/test_bundling_consolidation.py
rm tests/test_hardcoded_descriptions.py
rm tests/test_estimate_generation_OLD.py.bak
```

**Step 2: Commit**

```bash
git add -A
git commit -m "Delete tests for old templating system (TaskMapping, BundlingRule)"
```

---

### Task 2: Delete Template Files for Old System

**Files:**
- Delete: `templates/jobs/task_mapping_list.html`
- Delete: `templates/jobs/task_mapping_detail.html`
- Delete: `templates/jobs/task_mapping_form.html`
- Delete: `templates/jobs/task_mapping_confirm_delete.html`
- Delete: `templates/jobs/bundling_rule_list.html`
- Delete: `templates/jobs/bundling_rule_detail.html`
- Delete: `templates/jobs/bundling_rule_form.html`
- Delete: `templates/jobs/bundling_rule_confirm_delete.html`

**Step 1: Delete the template files**

```bash
rm templates/jobs/task_mapping_*.html
rm templates/jobs/bundling_rule_*.html
```

**Step 2: Commit**

```bash
git add -A
git commit -m "Delete HTML templates for TaskMapping and BundlingRule views"
```

---

### Task 3: Delete Views and URL Routes

**Files:**
- Modify: `apps/jobs/views.py` - Remove task_mapping_* and bundling_rule_* functions
- Modify: `apps/jobs/urls.py` - Remove task_mapping and bundling_rule URL patterns

**Step 1: Remove URL patterns from urls.py**

In `apps/jobs/urls.py`, delete lines 39-48 (the task-mappings and bundling-rules paths):

```python
# DELETE THESE LINES:
    path('task-mappings/', views.task_mapping_list, name='task_mapping_list'),
    path('task-mappings/create/', views.task_mapping_create, name='task_mapping_create'),
    path('task-mappings/<int:pk>/', views.task_mapping_detail, name='task_mapping_detail'),
    path('task-mappings/<int:pk>/edit/', views.task_mapping_edit, name='task_mapping_edit'),
    path('task-mappings/<int:pk>/delete/', views.task_mapping_delete, name='task_mapping_delete'),
    path('bundling-rules/', views.bundling_rule_list, name='bundling_rule_list'),
    path('bundling-rules/create/', views.bundling_rule_create, name='bundling_rule_create'),
    path('bundling-rules/<int:pk>/', views.bundling_rule_detail, name='bundling_rule_detail'),
    path('bundling-rules/<int:pk>/edit/', views.bundling_rule_edit, name='bundling_rule_edit'),
    path('bundling-rules/<int:pk>/delete/', views.bundling_rule_delete, name='bundling_rule_delete'),
```

**Step 2: Remove view functions from views.py**

In `apps/jobs/views.py`, delete the following functions (approximately lines 491-670):
- `task_mapping_list`
- `task_mapping_create`
- `task_mapping_detail`
- `task_mapping_edit`
- `task_mapping_delete`
- `bundling_rule_list`
- `bundling_rule_create`
- `bundling_rule_detail`
- `bundling_rule_edit`
- `bundling_rule_delete`

Also remove imports of `TaskMapping`, `BundlingRule`, `TaskMappingForm`, `BundlingRuleForm` from the top of views.py.

**Step 3: Commit**

```bash
git add apps/jobs/views.py apps/jobs/urls.py
git commit -m "Remove TaskMapping and BundlingRule views and URLs"
```

---

### Task 4: Delete Forms

**Files:**
- Modify: `apps/jobs/forms.py` - Remove TaskMappingForm, BundlingRuleForm, ProductBundlingRuleForm

**Step 1: Remove form classes from forms.py**

Delete:
- `TaskMappingForm` class (around line 366)
- `BundlingRuleForm` class (around line 397)
- `ProductBundlingRuleForm = BundlingRuleForm` alias (around line 465)

Also remove `TaskMapping`, `BundlingRule` from the imports at the top of the file.

**Step 2: Commit**

```bash
git add apps/jobs/forms.py
git commit -m "Remove TaskMappingForm and BundlingRuleForm"
```

---

### Task 5: Delete Models (Part 1 - Remove FKs First)

**Files:**
- Modify: `apps/jobs/models.py` - Remove FK references before deleting models

**Step 1: Remove task_mapping FK from TaskTemplate**

In TaskTemplate class, delete this line:
```python
task_mapping = models.ForeignKey(TaskMapping, on_delete=models.SET_NULL, null=True, blank=True)
```

**Step 2: Remove helper methods from TaskTemplate that reference TaskMapping**

Delete these methods from TaskTemplate:
```python
def get_mapping_strategy(self):
    """Get the mapping strategy for this template"""
    return self.task_mapping.mapping_strategy if self.task_mapping else 'direct'

def get_step_type(self):
    """Get the step type for this template"""
    return self.task_mapping.step_type if self.task_mapping else 'labor'

def get_product_type(self):
    """Get the default product type for this template"""
    return self.task_mapping.default_product_type if self.task_mapping else ''
```

**Step 3: Remove helper methods from Task that delegate to template**

In the Task class, find and delete any `get_step_type()`, `get_product_type()`, `get_mapping_strategy()` methods.

**Step 4: Remove work_order_template FK from BundlingRule**

This FK will be removed when we delete the model, but note it exists.

**Step 5: Commit**

```bash
git add apps/jobs/models.py
git commit -m "Remove TaskMapping FK and helper methods from TaskTemplate"
```

---

### Task 6: Delete Models (Part 2 - Delete Model Classes)

**Files:**
- Modify: `apps/jobs/models.py` - Delete TaskMapping, TaskInstanceMapping, BundlingRule classes

**Step 1: Delete TaskMapping class**

Delete the entire `TaskMapping` class (approximately lines 452-496).

**Step 2: Delete TaskInstanceMapping class**

Delete the entire `TaskInstanceMapping` class (approximately lines 498-507).

**Step 3: Delete BundlingRule class and alias**

Delete the entire `BundlingRule` class (approximately lines 656-721).
Delete the alias: `ProductBundlingRule = BundlingRule`

**Step 4: Remove product_type and template_type from WorkOrderTemplate**

In WorkOrderTemplate class, delete:
```python
TEMPLATE_TYPE_CHOICES = [
    ('product', 'Complete Product Template'),
    ('service', 'Service Template'),
    ('process', 'Process/Workflow Template'),
]
template_type = models.CharField(max_length=20, choices=TEMPLATE_TYPE_CHOICES, default='product')
product_type = models.CharField(max_length=50, blank=True)  # e.g., "table", "chair"
```

**Step 5: Update generate_tasks_for_worksheet to not use product_type**

In WorkOrderTemplate.generate_tasks_for_worksheet(), change:
```python
bundle_identifier = f"{self.product_type}_{worksheet.est_worksheet_id}_{instance}"
```
to:
```python
bundle_identifier = f"{self.template_name}_{worksheet.est_worksheet_id}_{instance}"
```

(This is temporary - we'll rework this method later)

**Step 6: Commit**

```bash
git add apps/jobs/models.py
git commit -m "Delete TaskMapping, TaskInstanceMapping, BundlingRule models"
```

---

### Task 7: Clean Up Services

**Files:**
- Modify: `apps/jobs/services.py` - Remove all TaskMapping/BundlingRule logic

**Step 1: Gut the EstimateGenerationService**

The current service heavily depends on TaskMapping and BundlingRule. For now, replace the implementation with a simple stub that will fail tests but compile:

```python
class EstimateGenerationService:
    """Service for converting EstWorksheets to Estimates.

    TODO: Reimplement using TemplateBundle system.
    """

    def __init__(self):
        self.line_number = 1
        self._default_line_item_type = None

    def _get_default_line_item_type(self):
        """Get a default LineItemType to use when none is specified."""
        if self._default_line_item_type is None:
            from apps.core.models import LineItemType
            self._default_line_item_type = LineItemType.objects.filter(
                code__in=['SVC', 'DIR'], is_active=True
            ).first()
            if self._default_line_item_type is None:
                self._default_line_item_type = LineItemType.objects.filter(is_active=True).first()
        return self._default_line_item_type

    @transaction.atomic
    def generate_estimate_from_worksheet(self, worksheet) -> 'Estimate':
        """
        Convert EstWorksheet to Estimate.

        TODO: Reimplement with TemplateBundle system.
        """
        raise NotImplementedError("EstimateGenerationService needs reimplementation with TemplateBundle system")
```

**Step 2: Remove imports of deleted models**

Remove `TaskMapping`, `TaskInstanceMapping`, `BundlingRule` from imports in services.py.

**Step 3: Commit**

```bash
git add apps/jobs/services.py
git commit -m "Stub out EstimateGenerationService pending TemplateBundle implementation"
```

---

### Task 8: Delete/Update Fixtures

**Files:**
- Modify or delete fixture files containing TaskMapping/BundlingRule data

**Step 1: Identify and clean fixtures**

Check each fixture file and remove TaskMapping, BundlingRule, TaskInstanceMapping entries:
- `fixtures/featuredata/line_item_type_test_data.json`
- `fixtures/job_data/data-lineitemtypes.json`
- `fixtures/webserver_test_data_old.json`
- `fixtures/webserver_test_data.json`
- `fixtures/job_data/01_base.json`
- `fixtures/workorder_from_estimate.json`
- `fixtures/unit_test_data.json`
- `fixtures/mixed_lineitems.json`
- `fixtures/template_test_data.json`

For each file, search for and remove any entries with:
- `"model": "jobs.taskmapping"`
- `"model": "jobs.bundlingrule"`
- `"model": "jobs.taskinstancemapping"`

Also remove references to these in FK fields (e.g., `"task_mapping": 1`).

**Step 2: Commit**

```bash
git add fixtures/
git commit -m "Remove TaskMapping/BundlingRule/TaskInstanceMapping from fixtures"
```

---

### Task 9: Delete Remaining Test Files That Will Break

**Files:**
- Review and delete/stub tests that depend on deleted functionality

**Step 1: Delete or heavily modify these test files**

Tests that are too coupled to the old system - delete entirely:
```bash
rm tests/test_estimate_generation_simple.py
rm tests/test_estimate_generation_demo.py
rm tests/test_estimate_generation_bundling.py
rm tests/test_estimate_generation_line_item_type.py
rm tests/test_task_service_line_item_type.py
```

**Step 2: Commit**

```bash
git add -A
git commit -m "Delete estimate generation tests (will rewrite for new system)"
```

---

### Task 10: Create Migration to Drop Old Tables

**Files:**
- Create: `apps/jobs/migrations/XXXX_drop_old_templating_tables.py`

**Step 1: Create migration**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
python manage.py makemigrations jobs --name drop_old_templating_tables
```

**Step 2: Review the generated migration**

It should show:
- Removal of `task_mapping` field from TaskTemplate
- Removal of `template_type`, `product_type` fields from WorkOrderTemplate
- Deletion of TaskMapping, TaskInstanceMapping, BundlingRule models

**Step 3: Apply the migration**

```bash
python manage.py migrate
```

**Step 4: Commit**

```bash
git add apps/jobs/migrations/
git commit -m "Migration: drop TaskMapping, BundlingRule, TaskInstanceMapping tables"
```

---

### Task 11: Verify Clean Compile

**Step 1: Run Django check**

```bash
python manage.py check
```

Expected: No errors (warnings OK)

**Step 2: Verify no stray references**

```bash
grep -r "TaskMapping\|BundlingRule\|TaskInstanceMapping\|step_type\|product_type" apps/ --include="*.py" | grep -v migrations | grep -v __pycache__
```

Expected: No matches (except possibly comments)

**Step 3: Commit any fixes needed**

---

## Phase 2: Build New System

### Task 12: Add line_item_type to TaskTemplate

**Files:**
- Modify: `apps/jobs/models.py`
- Test: `tests/test_new_templating.py` (new file)

**Step 1: Write the failing test**

Create `tests/test_new_templating.py`:

```python
import pytest
from apps.jobs.models import TaskTemplate
from apps.core.models import LineItemType

@pytest.mark.django_db
class TestTaskTemplateLineItemType:
    def test_task_template_requires_line_item_type(self):
        """TaskTemplate must have a line_item_type"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        tt = TaskTemplate.objects.create(
            template_name="Sand Surface",
            line_item_type=lit
        )
        assert tt.line_item_type == lit

    def test_task_template_line_item_type_protected(self):
        """Cannot delete LineItemType if TaskTemplate references it"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        TaskTemplate.objects.create(template_name="Sand", line_item_type=lit)

        with pytest.raises(Exception):  # ProtectedError
            lit.delete()
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_new_templating.py -v
```

Expected: FAIL - line_item_type field doesn't exist

**Step 3: Add line_item_type field to TaskTemplate**

In `apps/jobs/models.py`, add to TaskTemplate class:

```python
line_item_type = models.ForeignKey(
    'core.LineItemType',
    on_delete=models.PROTECT,
    null=True,  # Temporarily nullable for migration
    blank=True,
    help_text="Type of line item this task produces when mapped directly"
)
```

**Step 4: Create and run migration**

```bash
python manage.py makemigrations jobs --name add_line_item_type_to_task_template
python manage.py migrate
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_new_templating.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ tests/test_new_templating.py
git commit -m "feat: add line_item_type to TaskTemplate"
```

---

### Task 13: Create TemplateBundle Model

**Files:**
- Modify: `apps/jobs/models.py`
- Test: `tests/test_new_templating.py`

**Step 1: Write the failing test**

Add to `tests/test_new_templating.py`:

```python
from apps.jobs.models import WorkOrderTemplate, TemplateBundle

@pytest.mark.django_db
class TestTemplateBundle:
    def test_create_template_bundle(self):
        """Can create a TemplateBundle attached to WorkOrderTemplate"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        wot = WorkOrderTemplate.objects.create(template_name="Cabinet Refinish")

        bundle = TemplateBundle.objects.create(
            work_order_template=wot,
            name="Prep Work",
            line_item_type=lit
        )

        assert bundle.work_order_template == wot
        assert bundle.name == "Prep Work"
        assert bundle.line_item_type == lit

    def test_bundle_name_unique_per_template(self):
        """Bundle names must be unique within a WorkOrderTemplate"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        wot = WorkOrderTemplate.objects.create(template_name="Cabinet Refinish")

        TemplateBundle.objects.create(work_order_template=wot, name="Prep", line_item_type=lit)

        from django.db import IntegrityError
        with pytest.raises(IntegrityError):
            TemplateBundle.objects.create(work_order_template=wot, name="Prep", line_item_type=lit)

    def test_bundle_cascades_on_template_delete(self):
        """Deleting WorkOrderTemplate deletes its bundles"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        wot = WorkOrderTemplate.objects.create(template_name="Cabinet Refinish")
        TemplateBundle.objects.create(work_order_template=wot, name="Prep", line_item_type=lit)

        wot.delete()
        assert TemplateBundle.objects.count() == 0
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_new_templating.py::TestTemplateBundle -v
```

Expected: FAIL - TemplateBundle doesn't exist

**Step 3: Create TemplateBundle model**

In `apps/jobs/models.py`, add after WorkOrderTemplate class:

```python
class TemplateBundle(models.Model):
    """
    A named grouping within a WorkOrderTemplate that becomes one line item.

    TemplateTaskAssociations point to a bundle to indicate they should be
    combined into a single line item on the estimate.
    """
    work_order_template = models.ForeignKey(
        WorkOrderTemplate,
        on_delete=models.CASCADE,
        related_name='bundles'
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    line_item_type = models.ForeignKey(
        'core.LineItemType',
        on_delete=models.PROTECT
    )
    sort_order = models.IntegerField(default=0)

    class Meta:
        unique_together = ['work_order_template', 'name']
        ordering = ['sort_order', 'name']

    def __str__(self):
        return f"{self.work_order_template.template_name} - {self.name}"
```

**Step 4: Create and run migration**

```bash
python manage.py makemigrations jobs --name create_template_bundle
python manage.py migrate
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_new_templating.py::TestTemplateBundle -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ tests/test_new_templating.py
git commit -m "feat: create TemplateBundle model"
```

---

### Task 14: Add Mapping Fields to TemplateTaskAssociation

**Files:**
- Modify: `apps/jobs/models.py`
- Test: `tests/test_new_templating.py`

**Step 1: Write the failing test**

Add to `tests/test_new_templating.py`:

```python
from apps.jobs.models import TemplateTaskAssociation

@pytest.mark.django_db
class TestTemplateTaskAssociationMapping:
    def test_association_direct_mapping(self):
        """Association can have direct mapping strategy"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        wot = WorkOrderTemplate.objects.create(template_name="Cabinet Refinish")
        tt = TaskTemplate.objects.create(template_name="Sand", line_item_type=lit)

        assoc = TemplateTaskAssociation.objects.create(
            work_order_template=wot,
            task_template=tt,
            quantity=1,
            mapping_strategy='direct'
        )

        assert assoc.mapping_strategy == 'direct'
        assert assoc.bundle is None

    def test_association_bundle_mapping(self):
        """Association can point to a bundle"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        wot = WorkOrderTemplate.objects.create(template_name="Cabinet Refinish")
        tt = TaskTemplate.objects.create(template_name="Sand", line_item_type=lit)
        bundle = TemplateBundle.objects.create(work_order_template=wot, name="Prep", line_item_type=lit)

        assoc = TemplateTaskAssociation.objects.create(
            work_order_template=wot,
            task_template=tt,
            quantity=1,
            mapping_strategy='bundle',
            bundle=bundle
        )

        assert assoc.mapping_strategy == 'bundle'
        assert assoc.bundle == bundle

    def test_bundle_must_belong_to_same_template(self):
        """Cannot assign a bundle from a different WorkOrderTemplate"""
        lit = LineItemType.objects.create(name="Labor", code="LBR")
        wot1 = WorkOrderTemplate.objects.create(template_name="Cabinet Refinish")
        wot2 = WorkOrderTemplate.objects.create(template_name="Table Refinish")
        tt = TaskTemplate.objects.create(template_name="Sand", line_item_type=lit)
        bundle = TemplateBundle.objects.create(work_order_template=wot2, name="Prep", line_item_type=lit)

        from django.core.exceptions import ValidationError
        assoc = TemplateTaskAssociation(
            work_order_template=wot1,
            task_template=tt,
            quantity=1,
            mapping_strategy='bundle',
            bundle=bundle  # Wrong template!
        )

        with pytest.raises(ValidationError):
            assoc.full_clean()
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_new_templating.py::TestTemplateTaskAssociationMapping -v
```

Expected: FAIL - fields don't exist

**Step 3: Add fields to TemplateTaskAssociation**

In `apps/jobs/models.py`, modify TemplateTaskAssociation:

```python
class TemplateTaskAssociation(models.Model):
    """Association between WorkOrderTemplate and TaskTemplate with mapping configuration."""
    work_order_template = models.ForeignKey(WorkOrderTemplate, on_delete=models.CASCADE)
    task_template = models.ForeignKey('TaskTemplate', on_delete=models.CASCADE)

    # Quantity and ordering
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    sort_order = models.IntegerField(default=0)

    # Mapping configuration
    MAPPING_CHOICES = [
        ('direct', 'Direct - becomes its own line item'),
        ('bundle', 'Bundle - part of a bundled line item'),
        ('exclude', 'Exclude - internal only, not on estimate'),
    ]
    mapping_strategy = models.CharField(max_length=20, choices=MAPPING_CHOICES, default='direct')
    bundle = models.ForeignKey(
        TemplateBundle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='associations'
    )

    class Meta:
        unique_together = ['work_order_template', 'task_template']
        ordering = ['sort_order']

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.bundle and self.bundle.work_order_template != self.work_order_template:
            raise ValidationError("Bundle must belong to the same WorkOrderTemplate")

    def __str__(self):
        return f"{self.work_order_template.template_name} -> {self.task_template.template_name}"
```

Note: Rename `est_qty` to `quantity` for clarity.

**Step 4: Create and run migration**

```bash
python manage.py makemigrations jobs --name add_mapping_to_association
python manage.py migrate
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_new_templating.py::TestTemplateTaskAssociationMapping -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ tests/test_new_templating.py
git commit -m "feat: add mapping_strategy and bundle FK to TemplateTaskAssociation"
```

---

### Task 15: Implement EstimateGenerationService

**Files:**
- Modify: `apps/jobs/services.py`
- Test: `tests/test_new_templating.py`

**Step 1: Write the failing test**

Add to `tests/test_new_templating.py`:

```python
from apps.jobs.models import Job, EstWorksheet, Task, Estimate, EstimateLineItem
from apps.jobs.services import EstimateGenerationService
from apps.contacts.models import Contact

@pytest.mark.django_db
class TestEstimateGeneration:
    @pytest.fixture
    def setup_data(self):
        """Create base test data"""
        contact = Contact.objects.create(first_name="Test", last_name="User")
        job = Job.objects.create(job_number="J001", contact=contact)
        lit_labor = LineItemType.objects.create(name="Labor", code="LBR")
        lit_material = LineItemType.objects.create(name="Material", code="MAT")
        return {
            'job': job,
            'lit_labor': lit_labor,
            'lit_material': lit_material,
        }

    def test_direct_tasks_become_line_items(self, setup_data):
        """Tasks with direct mapping become individual line items"""
        job = setup_data['job']
        lit = setup_data['lit_labor']

        # Create templates
        wot = WorkOrderTemplate.objects.create(template_name="Simple Job")
        tt1 = TaskTemplate.objects.create(template_name="Sand", rate=50, line_item_type=lit)
        tt2 = TaskTemplate.objects.create(template_name="Stain", rate=75, line_item_type=lit)

        # Create associations (both direct)
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt1, quantity=2, mapping_strategy='direct'
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt2, quantity=1, mapping_strategy='direct'
        )

        # Create worksheet and tasks
        worksheet = EstWorksheet.objects.create(job=job)
        Task.objects.create(est_worksheet=worksheet, name="Sand", rate=50, est_qty=2, template=tt1)
        Task.objects.create(est_worksheet=worksheet, name="Stain", rate=75, est_qty=1, template=tt2)

        # Generate estimate
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # Should have 2 line items
        assert estimate.estimatelineitem_set.count() == 2
        line_items = list(estimate.estimatelineitem_set.order_by('line_number'))
        assert line_items[0].description == "Sand"
        assert line_items[0].line_item_type == lit
        assert line_items[1].description == "Stain"

    def test_bundled_tasks_become_one_line_item(self, setup_data):
        """Tasks in same bundle become one line item"""
        job = setup_data['job']
        lit = setup_data['lit_labor']

        wot = WorkOrderTemplate.objects.create(template_name="Bundle Job")
        bundle = TemplateBundle.objects.create(work_order_template=wot, name="Prep Work", line_item_type=lit)

        tt1 = TaskTemplate.objects.create(template_name="Sand", rate=50, line_item_type=lit)
        tt2 = TaskTemplate.objects.create(template_name="Clean", rate=25, line_item_type=lit)

        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt1, quantity=1, mapping_strategy='bundle', bundle=bundle
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt2, quantity=1, mapping_strategy='bundle', bundle=bundle
        )

        worksheet = EstWorksheet.objects.create(job=job)
        Task.objects.create(est_worksheet=worksheet, name="Sand", rate=50, est_qty=1, template=tt1)
        Task.objects.create(est_worksheet=worksheet, name="Clean", rate=25, est_qty=1, template=tt2)

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # Should have 1 line item (bundled)
        assert estimate.estimatelineitem_set.count() == 1
        line_item = estimate.estimatelineitem_set.first()
        assert line_item.description == "Prep Work"
        assert line_item.line_item_type == lit
        assert line_item.unit_price == 75  # 50 + 25

    def test_excluded_tasks_not_on_estimate(self, setup_data):
        """Tasks with exclude mapping don't appear on estimate"""
        job = setup_data['job']
        lit = setup_data['lit_labor']

        wot = WorkOrderTemplate.objects.create(template_name="With Excluded")
        tt1 = TaskTemplate.objects.create(template_name="Sand", rate=50, line_item_type=lit)
        tt2 = TaskTemplate.objects.create(template_name="Internal Check", rate=0, line_item_type=lit)

        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt1, quantity=1, mapping_strategy='direct'
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=wot, task_template=tt2, quantity=1, mapping_strategy='exclude'
        )

        worksheet = EstWorksheet.objects.create(job=job)
        Task.objects.create(est_worksheet=worksheet, name="Sand", rate=50, est_qty=1, template=tt1)
        Task.objects.create(est_worksheet=worksheet, name="Internal Check", rate=0, est_qty=1, template=tt2)

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        assert estimate.estimatelineitem_set.count() == 1
        assert estimate.estimatelineitem_set.first().description == "Sand"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_new_templating.py::TestEstimateGeneration -v
```

Expected: FAIL - NotImplementedError

**Step 3: Implement EstimateGenerationService**

Replace the stub in `apps/jobs/services.py` with full implementation:

```python
class EstimateGenerationService:
    """Service for converting EstWorksheets to Estimates using TemplateBundle system."""

    def __init__(self):
        self.line_number = 1
        self._default_line_item_type = None

    def _get_default_line_item_type(self):
        """Get a default LineItemType to use when none is specified."""
        if self._default_line_item_type is None:
            from apps.core.models import LineItemType
            self._default_line_item_type = LineItemType.objects.filter(
                code__in=['SVC', 'DIR'], is_active=True
            ).first()
            if self._default_line_item_type is None:
                self._default_line_item_type = LineItemType.objects.filter(is_active=True).first()
        return self._default_line_item_type

    @transaction.atomic
    def generate_estimate_from_worksheet(self, worksheet: 'EstWorksheet') -> 'Estimate':
        """Convert EstWorksheet to Estimate using TemplateBundle system."""
        from apps.jobs.models import Task, Estimate, EstimateLineItem, TemplateTaskAssociation

        tasks = worksheet.task_set.select_related('template', 'template__line_item_type').all()

        if not tasks:
            raise ValueError(f"EstWorksheet {worksheet.pk} has no tasks to convert")

        estimate = self._create_estimate(worksheet)

        # Categorize tasks by their mapping strategy
        direct_tasks = []
        bundle_tasks = defaultdict(list)  # bundle_id -> [tasks]

        for task in tasks:
            strategy = self._get_mapping_strategy(task)

            if strategy == 'exclude':
                continue
            elif strategy == 'bundle':
                bundle = self._get_bundle(task)
                if bundle:
                    bundle_tasks[bundle.pk].append((task, bundle))
                else:
                    # No bundle found, treat as direct
                    direct_tasks.append(task)
            else:
                direct_tasks.append(task)

        line_items = []

        # Process direct tasks
        for task in direct_tasks:
            line_item = self._create_direct_line_item(task, estimate)
            line_items.append(line_item)

        # Process bundled tasks
        for bundle_id, task_bundle_pairs in bundle_tasks.items():
            bundle = task_bundle_pairs[0][1]
            bundle_task_list = [pair[0] for pair in task_bundle_pairs]
            line_item = self._create_bundle_line_item(bundle_task_list, bundle, estimate)
            line_items.append(line_item)

        if line_items:
            EstimateLineItem.objects.bulk_create(line_items)

        worksheet.estimate = estimate
        worksheet.save()

        return estimate

    def _get_mapping_strategy(self, task: 'Task') -> str:
        """Get mapping strategy for a task from its template's association."""
        if not task.template:
            return 'direct'

        # Find the association for this template
        from apps.jobs.models import TemplateTaskAssociation

        # Get the worksheet's work order template if available
        # For now, just look up any association for this task template
        assoc = TemplateTaskAssociation.objects.filter(
            task_template=task.template
        ).first()

        if assoc:
            return assoc.mapping_strategy
        return 'direct'

    def _get_bundle(self, task: 'Task') -> 'TemplateBundle':
        """Get the bundle for a task."""
        if not task.template:
            return None

        from apps.jobs.models import TemplateTaskAssociation

        assoc = TemplateTaskAssociation.objects.filter(
            task_template=task.template
        ).select_related('bundle').first()

        if assoc:
            return assoc.bundle
        return None

    def _create_estimate(self, worksheet: 'EstWorksheet') -> 'Estimate':
        """Create a new estimate for the worksheet's job."""
        from apps.jobs.models import Estimate
        from apps.core.services import NumberGenerationService

        version = 1
        parent_estimate = None

        if worksheet.parent and worksheet.parent.estimate:
            parent_estimate = worksheet.parent.estimate
            estimate_number = parent_estimate.estimate_number
            version = parent_estimate.version + 1
            parent_estimate.status = 'superseded'
            parent_estimate.save()
        else:
            estimate_number = NumberGenerationService.generate_next_number('estimate')

        estimate = Estimate.objects.create(
            job=worksheet.job,
            estimate_number=estimate_number,
            version=version,
            parent=parent_estimate,
            status='draft'
        )

        return estimate

    def _create_direct_line_item(self, task: 'Task', estimate: 'Estimate') -> 'EstimateLineItem':
        """Create a line item for a direct-mapped task."""
        from apps.jobs.models import EstimateLineItem

        line_item_type = None
        if task.template and task.template.line_item_type:
            line_item_type = task.template.line_item_type
        else:
            line_item_type = self._get_default_line_item_type()

        line_item = EstimateLineItem(
            estimate=estimate,
            line_number=self.line_number,
            description=task.name,
            quantity=task.est_qty or 1,
            unit_price=task.rate or 0,
            line_item_type=line_item_type,
        )
        self.line_number += 1
        return line_item

    def _create_bundle_line_item(self, tasks: list, bundle: 'TemplateBundle', estimate: 'Estimate') -> 'EstimateLineItem':
        """Create a single line item for bundled tasks."""
        from apps.jobs.models import EstimateLineItem

        # Sum up the prices
        total_price = sum((t.rate or 0) * (t.est_qty or 1) for t in tasks)

        line_item = EstimateLineItem(
            estimate=estimate,
            line_number=self.line_number,
            description=bundle.name,
            quantity=1,
            unit_price=total_price,
            line_item_type=bundle.line_item_type,
        )
        self.line_number += 1
        return line_item
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_new_templating.py::TestEstimateGeneration -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add apps/jobs/services.py tests/test_new_templating.py
git commit -m "feat: implement EstimateGenerationService with TemplateBundle system"
```

---

### Task 16: Update Remaining Tests

**Files:**
- Modify: Various test files that import old models

**Step 1: Find and fix remaining test imports**

```bash
grep -r "TaskMapping\|BundlingRule\|TaskInstanceMapping" tests/ --include="*.py" | grep -v __pycache__
```

For each file found, either:
1. Remove the import if the test no longer needs it
2. Delete the test if it's obsolete
3. Rewrite the test to use the new system

**Step 2: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Fix any failures.

**Step 3: Commit**

```bash
git add tests/
git commit -m "fix: update remaining tests for new templating system"
```

---

### Task 17: Final Cleanup - Grep for Stragglers

**Step 1: Search for any remaining references**

```bash
grep -rn "TaskMapping\|BundlingRule\|TaskInstanceMapping\|step_type\|product_type\|template_type" \
  --include="*.py" --include="*.html" \
  apps/ templates/ tests/ \
  | grep -v migrations \
  | grep -v __pycache__ \
  | grep -v ".pyc"
```

**Step 2: Fix any remaining references found**

**Step 3: Run Django check and full test suite**

```bash
python manage.py check
pytest tests/ -v
```

**Step 4: Commit any final fixes**

```bash
git add -A
git commit -m "chore: final cleanup of old templating system references"
```

---

## Summary

**Models Deleted:**
- TaskMapping
- TaskInstanceMapping
- BundlingRule (and ProductBundlingRule alias)

**Fields Deleted:**
- WorkOrderTemplate.template_type
- WorkOrderTemplate.product_type
- TaskTemplate.task_mapping (FK)

**Models Created:**
- TemplateBundle

**Fields Added:**
- TaskTemplate.line_item_type (FK to LineItemType)
- TemplateTaskAssociation.mapping_strategy
- TemplateTaskAssociation.bundle (FK to TemplateBundle)
- TemplateTaskAssociation.quantity (renamed from est_qty)

**Files Deleted:**
- 8 HTML templates (task_mapping_*, bundling_rule_*)
- ~12 test files
- View functions and URL routes for old CRUD

**Services Rewritten:**
- EstimateGenerationService - completely rewritten for TemplateBundle system
