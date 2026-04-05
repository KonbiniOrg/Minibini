# Plan 2: WO Creation Actions + Workflow Routing + PlanTask API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the three WorkOrder creation paths as API actions with hard prerequisite gates and soft workflow warnings, and add a standalone `/api/plan-tasks/` read-only resource.

**Architecture:** Three new `@action` endpoints on `WorkOrderViewSet` (`create-from-estimate`, `create-from-template`, `copy-from-worksheet`). Each calls the existing `WorkOrderService` method and wraps it with validation: hard gates (400 if prerequisite missing) and soft warnings (200 with `warnings` array if workflow mismatch, unless `?confirm=true` is passed). A standalone `PlanTaskViewSet` provides read-only retrieve for plan tasks (CRUD already lives on the worksheet nested endpoints). TDD throughout.

**Tech Stack:** Django 5.2, DRF, Python 3.12, MySQL.

**Spec:** `docs/designs/2026-04-05-task-split-and-worksheet-to-workorder.md` — sections "Workflow Routing: Restrictions and Warnings" and "API Shape".

**Depends on:** Plan 1 (commit `e74cbe8`+) on branch `feature/worksheet-to-workorder`.

---

## File Structure

**Files to create:**

- `apps/api/plan_tasks/__init__.py` — empty
- `apps/api/plan_tasks/views.py` — `PlanTaskViewSet` (read-only retrieve)
- `apps/api/plan_tasks/serializers.py` — `PlanTaskDetailSerializer` (full detail for standalone endpoint)
- `tests/test_api_plan_tasks.py` — tests for standalone PlanTask API
- `tests/test_api_wo_creation.py` — tests for all three WO creation actions + routing

**Files to modify:**

- `apps/api/work_orders/views.py` — add three `@action` methods for WO creation
- `apps/api/urls.py` — register `plan-tasks` router and add to `api_root`
- `apps/api/worksheets/serializers.py` — add `PlanMaterialSerializer` to `PlanTaskSerializer` (materials not yet exposed)

---

## Phase 1: Standalone PlanTask API

### Task 1.1: PlanTask detail serializer + viewset

**Files:**
- Create: `apps/api/plan_tasks/__init__.py`
- Create: `apps/api/plan_tasks/serializers.py`
- Create: `apps/api/plan_tasks/views.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_plan_tasks.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_plan_tasks.py`:

```python
from rest_framework.test import APIClient
from django.test import TestCase
from apps.core.models import User
from apps.jobs.models import Job, PlanTask, PlanBundle
from apps.estimates.models import EstWorksheet


class PlanTaskAPITest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser', password='testpass',
        )
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.create(
            job_number='TEST-001', name='Test Job',
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Install shelves',
            description='Wall-mount 3 shelves',
            units='each',
            rate=50,
            est_qty=3,
        )

    def test_retrieve_plan_task(self):
        response = self.client.get(f'/api/plan-tasks/{self.plan_task.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Install shelves')
        self.assertIn('plan_task_id', response.data)
        self.assertIn('est_worksheet', response.data)

    def test_retrieve_includes_materials(self):
        from apps.inventory.models import PlanMaterial
        PlanMaterial.objects.create(
            plan_task=self.plan_task,
            description='Shelf bracket',
            quantity=6,
            unit_cost=5,
            sell_price=10,
        )
        response = self.client.get(f'/api/plan-tasks/{self.plan_task.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['plan_materials']), 1)
        self.assertEqual(response.data['plan_materials'][0]['description'], 'Shelf bracket')

    def test_retrieve_includes_worksheet_and_job_context(self):
        response = self.client.get(f'/api/plan-tasks/{self.plan_task.pk}/')
        self.assertEqual(response.status_code, 200)
        ws = response.data['est_worksheet']
        self.assertEqual(ws['est_worksheet_id'], self.worksheet.pk)
        self.assertEqual(ws['job']['job_number'], 'TEST-001')

    def test_list_not_allowed(self):
        """PlanTasks are accessed via worksheet nested endpoint, not flat list."""
        response = self.client.get('/api/plan-tasks/')
        self.assertEqual(response.status_code, 405)

    def test_create_not_allowed(self):
        response = self.client.post('/api/plan-tasks/', {
            'name': 'New task',
        }, format='json')
        self.assertEqual(response.status_code, 405)

    def test_unauthenticated_returns_403(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(f'/api/plan-tasks/{self.plan_task.pk}/')
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test tests.test_api_plan_tasks -v 2 2>&1 | tail -20
```

Expected: errors because `/api/plan-tasks/` route doesn't exist yet.

- [ ] **Step 3: Create the serializer**

Create `apps/api/plan_tasks/__init__.py` (empty file).

Create `apps/api/plan_tasks/serializers.py`:

```python
from rest_framework import serializers
from apps.jobs.models import PlanTask
from apps.inventory.models import PlanMaterial
from apps.core.units import UnitsField


class PlanMaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanMaterial
        fields = [
            'plan_material_id', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category',
        ]
        read_only_fields = fields


class PlanTaskDetailSerializer(serializers.ModelSerializer):
    units = UnitsField()
    plan_materials = PlanMaterialSerializer(many=True, read_only=True)
    est_worksheet = serializers.SerializerMethodField()

    class Meta:
        model = PlanTask
        fields = [
            'plan_task_id', 'name', 'description', 'sort_order',
            'units', 'rate', 'est_qty', 'accounting_category',
            'mapping_strategy', 'bundle',
            'plan_materials', 'est_worksheet',
        ]
        read_only_fields = fields

    def get_est_worksheet(self, obj):
        ws = obj.est_worksheet
        job = ws.job
        return {
            'est_worksheet_id': ws.pk,
            'status': ws.status,
            'job': {
                'id': job.pk,
                'job_number': job.job_number,
                'name': job.name,
            },
        }
```

- [ ] **Step 4: Create the viewset**

Create `apps/api/plan_tasks/views.py`:

```python
from rest_framework.mixins import RetrieveModelMixin
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from apps.jobs.models import PlanTask
from .serializers import PlanTaskDetailSerializer


class PlanTaskViewSet(RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only detail for PlanTasks.

    CRUD operations live on the worksheet nested endpoints:
    /api/est-worksheets/{id}/tasks/

    This standalone endpoint provides a detail view with full context
    (materials, worksheet, job) for use by the SPA when navigating
    directly to a plan task.
    """
    queryset = PlanTask.objects.select_related(
        'est_worksheet__job',
    ).prefetch_related('plan_materials')
    serializer_class = PlanTaskDetailSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'pk'
```

- [ ] **Step 5: Register the route**

In `apps/api/urls.py`, add the import and router registration:

Add import near the top (after the existing `TaskViewSet` import):

```python
from apps.api.plan_tasks.views import PlanTaskViewSet
```

Add router registration (after line 70, `router.register(r'tasks', ...)`):

```python
router.register(r'plan-tasks', PlanTaskViewSet, basename='plan-task')
```

Add to the `api_root` response dict (after the `'search'` line):

```python
'plan-tasks': '/api/plan-tasks/',
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
python manage.py test tests.test_api_plan_tasks -v 2 2>&1 | tail -20
```

Expected: all 6 tests pass.

- [ ] **Step 7: Commit**

```bash
git add apps/api/plan_tasks/ apps/api/urls.py tests/test_api_plan_tasks.py
git commit -m "$(cat <<'EOF'
feat: add standalone /api/plan-tasks/ read-only resource

PlanTaskViewSet exposes retrieve-only endpoint with full context:
materials, worksheet, and job info. CRUD remains on the worksheet
nested endpoints. List and create return 405.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.2: Add PlanMaterial to nested worksheet PlanTask serializer

**Files:**
- Modify: `apps/api/worksheets/serializers.py`
- Test: `tests/test_api_plan_tasks.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api_plan_tasks.py`:

```python
class WorksheetNestedPlanTaskTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser2', password='testpass',
        )
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.create(
            job_number='TEST-002', name='Test Job 2',
        )
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Sand floor',
            units='sqft',
            rate=2,
            est_qty=100,
        )

    def test_nested_task_list_includes_materials(self):
        from apps.inventory.models import PlanMaterial
        PlanMaterial.objects.create(
            plan_task=self.plan_task,
            description='Sandpaper 120 grit',
            quantity=10,
            unit_cost=3,
            sell_price=5,
        )
        response = self.client.get(
            f'/api/est-worksheets/{self.worksheet.pk}/tasks/'
        )
        self.assertEqual(response.status_code, 200)
        task_data = response.data[0]
        self.assertIn('plan_materials', task_data)
        self.assertEqual(len(task_data['plan_materials']), 1)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test tests.test_api_plan_tasks.WorksheetNestedPlanTaskTest -v 2 2>&1 | tail -10
```

Expected: FAIL — `plan_materials` key missing from nested task serializer.

- [ ] **Step 3: Update the worksheet PlanTaskSerializer**

In `apps/api/worksheets/serializers.py`, add `PlanMaterialSerializer` and nest it:

```python
from rest_framework import serializers
from apps.estimates.models import EstWorksheet
from apps.jobs.models import PlanTask, PlanBundle
from apps.inventory.models import PlanMaterial
from apps.core.units import UnitsField


class PlanMaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanMaterial
        fields = [
            'plan_material_id', 'description', 'quantity',
            'unit_cost', 'sell_price', 'price_list_item',
            'accounting_category',
        ]
        read_only_fields = fields


class PlanTaskSerializer(serializers.ModelSerializer):
    units = UnitsField()
    plan_materials = PlanMaterialSerializer(many=True, read_only=True)

    class Meta:
        model = PlanTask
        fields = [
            'plan_task_id', 'name', 'description', 'sort_order',
            'units', 'rate', 'est_qty', 'accounting_category',
            'mapping_strategy', 'bundle', 'plan_materials',
        ]
        read_only_fields = ['plan_task_id', 'sort_order']


class PlanBundleSerializer(serializers.ModelSerializer):
    plan_tasks = PlanTaskSerializer(many=True, read_only=True)

    class Meta:
        model = PlanBundle
        fields = [
            'plan_bundle_id', 'name', 'description', 'accounting_category',
            'sort_order', 'plan_tasks',
        ]
        read_only_fields = ['plan_bundle_id', 'sort_order']


class EstWorksheetSerializer(serializers.ModelSerializer):
    tasks = PlanTaskSerializer(source='plan_tasks', many=True, read_only=True)
    bundles = PlanBundleSerializer(source='plan_bundles', many=True, read_only=True)

    class Meta:
        model = EstWorksheet
        fields = [
            'est_worksheet_id', 'job', 'template', 'estimate',
            'status', 'version', 'parent', 'created_date', 'tasks', 'bundles',
        ]
        read_only_fields = ['est_worksheet_id', 'created_date', 'status']
```

- [ ] **Step 4: Run tests**

```bash
python manage.py test tests.test_api_plan_tasks -v 2 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/worksheets/serializers.py tests/test_api_plan_tasks.py
git commit -m "$(cat <<'EOF'
feat: expose plan_materials on worksheet PlanTask serializer

Both the nested /api/est-worksheets/{id}/tasks/ and standalone
/api/plan-tasks/{id}/ endpoints now include plan_materials.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2: WO Creation Actions

### Task 2.1: `create-from-template` action

**Files:**
- Modify: `apps/api/work_orders/views.py`
- Test: `tests/test_api_wo_creation.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_wo_creation.py`:

```python
from django.test import TestCase
from rest_framework.test import APIClient
from apps.core.models import User
from apps.jobs.models import Job, WorkOrder, Task, PlanTask, PlanBundle
from apps.estimates.models import (
    Estimate, EstWorksheet, WorkOrderTemplate, TaskTemplate,
    TemplateTaskAssociation,
)
from apps.inventory.models import PlanMaterial


def make_admin():
    user = User.objects.create_user(username='admin_wo', password='pass')
    from django.contrib.auth.models import Permission
    perm = Permission.objects.get(codename='can_manage_jobs')
    user.user_permissions.add(perm)
    return user


class CreateFromTemplateTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = make_admin()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.create(job_number='WO-T-001', name='Template Job')
        self.template = WorkOrderTemplate.objects.create(
            template_name='Kitchen Install', is_active=True,
        )
        from apps.core.models import AccountingCategory
        cat = AccountingCategory.objects.create(name='Labor')
        self.task_template = TaskTemplate.objects.create(
            template_name='Countertop', is_active=True,
            units='each', rate=100,
            accounting_category=cat,
        )
        TemplateTaskAssociation.objects.create(
            work_order_template=self.template,
            task_template=self.task_template,
            est_qty=2,
            sort_order=1,
        )

    def test_create_from_template_success(self):
        response = self.client.post(
            '/api/work-orders/create-from-template/',
            {'job': self.job.pk, 'template': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn('work_order_id', response.data)
        wo = WorkOrder.objects.get(pk=response.data['work_order_id'])
        self.assertEqual(wo.job, self.job)
        self.assertEqual(wo.tasks.count(), 1)
        self.assertEqual(wo.tasks.first().name, 'Countertop')

    def test_create_from_template_missing_template(self):
        response = self.client.post(
            '/api/work-orders/create-from-template/',
            {'job': self.job.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_create_from_template_inactive_template(self):
        self.template.is_active = False
        self.template.save()
        response = self.client.post(
            '/api/work-orders/create-from-template/',
            {'job': self.job.pk, 'template': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_can_manage_jobs(self):
        worker = User.objects.create_user(username='worker_wo', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            '/api/work-orders/create-from-template/',
            {'job': self.job.pk, 'template': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test tests.test_api_wo_creation.CreateFromTemplateTest -v 2 2>&1 | tail -10
```

Expected: 404 because the action doesn't exist yet.

- [ ] **Step 3: Implement the action**

In `apps/api/work_orders/views.py`, add the import and action:

Add imports at the top:

```python
from rest_framework.decorators import action
from django.core.exceptions import ValidationError
from apps.estimates.models import WorkOrderTemplate
```

Add method to `WorkOrderViewSet`:

```python
    @action(detail=False, methods=['post'], url_path='create-from-template')
    def create_from_template(self, request):
        job_pk = request.data.get('job')
        template_pk = request.data.get('template')
        if not job_pk:
            return Response(
                {'job': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not template_pk:
            return Response(
                {'template': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_pk)
        except Job.DoesNotExist:
            return Response({'job': ['Job not found.']}, status=status.HTTP_400_BAD_REQUEST)
        try:
            template = WorkOrderTemplate.objects.get(pk=template_pk)
        except WorkOrderTemplate.DoesNotExist:
            return Response(
                {'template': ['Template not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            wo = WorkOrderService.create_from_template(template, job)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(wo)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
```

Also add the `status` import at the top if not already present:

```python
from rest_framework import viewsets, status
```

- [ ] **Step 4: Run tests**

```bash
python manage.py test tests.test_api_wo_creation.CreateFromTemplateTest -v 2 2>&1 | tail -10
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/work_orders/views.py tests/test_api_wo_creation.py
git commit -m "$(cat <<'EOF'
feat: add POST /api/work-orders/create-from-template/ action

Creates a WorkOrder from a WorkOrderTemplate for a given job.
Validates template existence and active status.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.2: `create-from-estimate` action

**Files:**
- Modify: `apps/api/work_orders/views.py`
- Modify: `tests/test_api_wo_creation.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_wo_creation.py`:

```python
class CreateFromEstimateTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = make_admin()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.create(job_number='WO-E-001', name='Estimate Job')
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-001',
            status=Estimate.STATUS_ACCEPTED,
        )

    def test_create_from_accepted_estimate(self):
        response = self.client.post(
            '/api/work-orders/create-from-estimate/',
            {'estimate': self.estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn('work_order_id', response.data)
        wo = WorkOrder.objects.get(pk=response.data['work_order_id'])
        self.assertEqual(wo.job, self.job)

    def test_create_from_open_estimate(self):
        self.estimate.status = Estimate.STATUS_OPEN
        self.estimate.save()
        response = self.client.post(
            '/api/work-orders/create-from-estimate/',
            {'estimate': self.estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)

    def test_rejects_draft_estimate(self):
        self.estimate.status = Estimate.STATUS_DRAFT
        self.estimate.save()
        response = self.client.post(
            '/api/work-orders/create-from-estimate/',
            {'estimate': self.estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_estimate(self):
        response = self.client.post(
            '/api/work-orders/create-from-estimate/',
            {},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_can_manage_jobs(self):
        worker = User.objects.create_user(username='worker_est', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            '/api/work-orders/create-from-estimate/',
            {'estimate': self.estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test tests.test_api_wo_creation.CreateFromEstimateTest -v 2 2>&1 | tail -10
```

- [ ] **Step 3: Implement the action**

Add import at top of `apps/api/work_orders/views.py`:

```python
from apps.estimates.models import WorkOrderTemplate, Estimate
```

Add method to `WorkOrderViewSet`:

```python
    @action(detail=False, methods=['post'], url_path='create-from-estimate')
    def create_from_estimate(self, request):
        estimate_pk = request.data.get('estimate')
        if not estimate_pk:
            return Response(
                {'estimate': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            estimate = Estimate.objects.get(pk=estimate_pk)
        except Estimate.DoesNotExist:
            return Response(
                {'estimate': ['Estimate not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            wo = WorkOrderService.create_from_estimate(estimate)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(wo)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
```

- [ ] **Step 4: Run tests**

```bash
python manage.py test tests.test_api_wo_creation.CreateFromEstimateTest -v 2 2>&1 | tail -10
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/work_orders/views.py tests/test_api_wo_creation.py
git commit -m "$(cat <<'EOF'
feat: add POST /api/work-orders/create-from-estimate/ action

Creates a WorkOrder from an Estimate. Validates estimate exists
and is in open or accepted status.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2.3: `copy-from-worksheet` action

**Files:**
- Modify: `apps/api/work_orders/views.py`
- Modify: `tests/test_api_wo_creation.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_wo_creation.py`:

```python
class CopyFromWorksheetTest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = make_admin()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.create(job_number='WO-W-001', name='Worksheet Job')
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Build cabinet',
            units='each',
            rate=200,
            est_qty=1,
        )
        PlanMaterial.objects.create(
            plan_task=self.plan_task,
            description='Plywood sheet',
            quantity=2,
            unit_cost=40,
            sell_price=60,
        )

    def test_copy_from_worksheet_success(self):
        response = self.client.post(
            '/api/work-orders/copy-from-worksheet/',
            {'job': self.job.pk, 'worksheet': self.worksheet.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn('work_order_id', response.data)
        wo = WorkOrder.objects.get(pk=response.data['work_order_id'])
        self.assertEqual(wo.job, self.job)
        self.assertEqual(wo.tasks.count(), 1)
        task = wo.tasks.first()
        self.assertEqual(task.name, 'Build cabinet')
        self.assertEqual(task.materials.count(), 1)
        self.assertEqual(task.materials.first().description, 'Plywood sheet')

    def test_missing_worksheet(self):
        response = self.client.post(
            '/api/work-orders/copy-from-worksheet/',
            {'job': self.job.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_job(self):
        response = self.client.post(
            '/api/work-orders/copy-from-worksheet/',
            {'worksheet': self.worksheet.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_worksheet_not_found(self):
        response = self.client.post(
            '/api/work-orders/copy-from-worksheet/',
            {'job': self.job.pk, 'worksheet': 99999},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_requires_can_manage_jobs(self):
        worker = User.objects.create_user(username='worker_ws', password='pass')
        self.client.force_authenticate(user=worker)
        response = self.client.post(
            '/api/work-orders/copy-from-worksheet/',
            {'job': self.job.pk, 'worksheet': self.worksheet.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test tests.test_api_wo_creation.CopyFromWorksheetTest -v 2 2>&1 | tail -10
```

- [ ] **Step 3: Implement the action**

Add import at top of `apps/api/work_orders/views.py` if not already present:

```python
from apps.estimates.models import WorkOrderTemplate, Estimate, EstWorksheet
```

Add method to `WorkOrderViewSet`:

```python
    @action(detail=False, methods=['post'], url_path='copy-from-worksheet')
    def copy_from_worksheet(self, request):
        job_pk = request.data.get('job')
        worksheet_pk = request.data.get('worksheet')
        if not job_pk:
            return Response(
                {'job': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not worksheet_pk:
            return Response(
                {'worksheet': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_pk)
        except Job.DoesNotExist:
            return Response({'job': ['Job not found.']}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ws = EstWorksheet.objects.get(pk=worksheet_pk)
        except EstWorksheet.DoesNotExist:
            return Response(
                {'worksheet': ['Worksheet not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.db import transaction
        with transaction.atomic():
            wo = WorkOrderService.create_direct(job, template=ws.template)
            WorkOrderService.copy_from_worksheet(wo.pk, ws.pk)

        wo.refresh_from_db()
        serializer = self.get_serializer(wo)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
```

- [ ] **Step 4: Run tests**

```bash
python manage.py test tests.test_api_wo_creation.CopyFromWorksheetTest -v 2 2>&1 | tail -10
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/work_orders/views.py tests/test_api_wo_creation.py
git commit -m "$(cat <<'EOF'
feat: add POST /api/work-orders/copy-from-worksheet/ action

Creates a WorkOrder and populates it from a worksheet's PlanTasks
and PlanMaterials. Preserves PLI linkage on materials.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3: Workflow Routing (Soft Warnings)

### Task 3.1: Soft warnings on `create-from-estimate`

**Files:**
- Modify: `apps/api/work_orders/views.py`
- Modify: `tests/test_api_wo_creation.py`

The spec says: if the job has a Worksheet, warn: "This job has a Worksheet. Usually the Worksheet is the source for the WorkOrder, not the Estimate. Proceed anyway?"

The API pattern: return 200 with a `warnings` array and no WorkOrder created. If the client re-sends with `?confirm=true`, proceed normally.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_wo_creation.py`:

```python
class WorkflowWarningEstimateTest(TestCase):
    """Soft warning: create-from-estimate when job has a worksheet."""

    def setUp(self):
        self.client = APIClient()
        self.user = make_admin()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.create(job_number='WRN-E-001', name='Warning Job')
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-W-001',
            status=Estimate.STATUS_ACCEPTED,
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, estimate=self.estimate,
        )

    def test_warns_when_job_has_worksheet(self):
        response = self.client.post(
            '/api/work-orders/create-from-estimate/',
            {'estimate': self.estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('warnings', response.data)
        self.assertTrue(len(response.data['warnings']) > 0)
        self.assertNotIn('work_order_id', response.data)

    def test_confirm_bypasses_warning(self):
        response = self.client.post(
            '/api/work-orders/create-from-estimate/?confirm=true',
            {'estimate': self.estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn('work_order_id', response.data)

    def test_no_warning_when_no_worksheet(self):
        """Job with estimate but no worksheet — no warning."""
        self.worksheet.delete()
        response = self.client.post(
            '/api/work-orders/create-from-estimate/',
            {'estimate': self.estimate.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test tests.test_api_wo_creation.WorkflowWarningEstimateTest -v 2 2>&1 | tail -10
```

Expected: `test_warns_when_job_has_worksheet` returns 201 (no warning logic yet).

- [ ] **Step 3: Add warning logic to `create_from_estimate`**

Update the `create_from_estimate` method in `apps/api/work_orders/views.py`. Insert the warning check between the estimate lookup and the service call:

```python
    @action(detail=False, methods=['post'], url_path='create-from-estimate')
    def create_from_estimate(self, request):
        estimate_pk = request.data.get('estimate')
        if not estimate_pk:
            return Response(
                {'estimate': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            estimate = Estimate.objects.get(pk=estimate_pk)
        except Estimate.DoesNotExist:
            return Response(
                {'estimate': ['Estimate not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Soft warning: job has a worksheet
        confirm = request.query_params.get('confirm') == 'true'
        if not confirm:
            warnings = self._check_estimate_workflow_warnings(estimate)
            if warnings:
                return Response({'warnings': warnings})

        try:
            wo = WorkOrderService.create_from_estimate(estimate)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(wo)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _check_estimate_workflow_warnings(estimate):
        warnings = []
        has_worksheet = EstWorksheet.objects.filter(job=estimate.job).exists()
        if has_worksheet:
            warnings.append(
                'This job has a Worksheet. Usually the Worksheet is the '
                'source for the WorkOrder, not the Estimate. Proceed anyway?'
            )
        return warnings
```

- [ ] **Step 4: Run tests**

```bash
python manage.py test tests.test_api_wo_creation.WorkflowWarningEstimateTest tests.test_api_wo_creation.CreateFromEstimateTest -v 2 2>&1 | tail -15
```

Expected: all pass. The existing `CreateFromEstimateTest` tests still pass because they don't have worksheets on the job.

- [ ] **Step 5: Commit**

```bash
git add apps/api/work_orders/views.py tests/test_api_wo_creation.py
git commit -m "$(cat <<'EOF'
feat: soft workflow warning on create-from-estimate

Returns 200 with warnings array when the job has a worksheet,
advising that the worksheet is usually the WO source. Bypassed
with ?confirm=true.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.2: Soft warnings on `create-from-template`

**Files:**
- Modify: `apps/api/work_orders/views.py`
- Modify: `tests/test_api_wo_creation.py`

Spec says: if the job has a Worksheet or an Estimate, warn: "This job already has [Worksheet/Estimate]. Template → WO is usually for jobs that go straight to work. Proceed anyway?"

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_wo_creation.py`:

```python
class WorkflowWarningTemplateTest(TestCase):
    """Soft warning: create-from-template when job has worksheet or estimate."""

    def setUp(self):
        self.client = APIClient()
        self.user = make_admin()
        self.client.force_authenticate(user=self.user)
        self.job = Job.objects.create(job_number='WRN-T-001', name='Warning Template Job')
        self.template = WorkOrderTemplate.objects.create(
            template_name='Quick Template', is_active=True,
        )

    def test_warns_when_job_has_worksheet(self):
        EstWorksheet.objects.create(job=self.job)
        response = self.client.post(
            '/api/work-orders/create-from-template/',
            {'job': self.job.pk, 'template': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('warnings', response.data)
        self.assertIn('Worksheet', response.data['warnings'][0])

    def test_warns_when_job_has_estimate(self):
        Estimate.objects.create(
            job=self.job, estimate_number='EST-WT-001',
            status=Estimate.STATUS_OPEN,
        )
        response = self.client.post(
            '/api/work-orders/create-from-template/',
            {'job': self.job.pk, 'template': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('warnings', response.data)
        self.assertIn('Estimate', response.data['warnings'][0])

    def test_warns_when_job_has_both(self):
        EstWorksheet.objects.create(job=self.job)
        Estimate.objects.create(
            job=self.job, estimate_number='EST-WT-002',
            status=Estimate.STATUS_OPEN,
        )
        response = self.client.post(
            '/api/work-orders/create-from-template/',
            {'job': self.job.pk, 'template': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('warnings', response.data)

    def test_confirm_bypasses_warning(self):
        EstWorksheet.objects.create(job=self.job)
        response = self.client.post(
            '/api/work-orders/create-from-template/?confirm=true',
            {'job': self.job.pk, 'template': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)

    def test_no_warning_for_clean_job(self):
        response = self.client.post(
            '/api/work-orders/create-from-template/',
            {'job': self.job.pk, 'template': self.template.pk},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python manage.py test tests.test_api_wo_creation.WorkflowWarningTemplateTest -v 2 2>&1 | tail -15
```

Expected: warning tests fail (currently returns 201 unconditionally).

- [ ] **Step 3: Add warning logic to `create_from_template`**

Update `create_from_template` in `apps/api/work_orders/views.py`:

```python
    @action(detail=False, methods=['post'], url_path='create-from-template')
    def create_from_template(self, request):
        job_pk = request.data.get('job')
        template_pk = request.data.get('template')
        if not job_pk:
            return Response(
                {'job': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not template_pk:
            return Response(
                {'template': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from apps.jobs.models import Job
        try:
            job = Job.objects.get(pk=job_pk)
        except Job.DoesNotExist:
            return Response({'job': ['Job not found.']}, status=status.HTTP_400_BAD_REQUEST)
        try:
            template = WorkOrderTemplate.objects.get(pk=template_pk)
        except WorkOrderTemplate.DoesNotExist:
            return Response(
                {'template': ['Template not found.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Soft warning: job already has planning artifacts
        confirm = request.query_params.get('confirm') == 'true'
        if not confirm:
            warnings = self._check_template_workflow_warnings(job)
            if warnings:
                return Response({'warnings': warnings})

        try:
            wo = WorkOrderService.create_from_template(template, job)
        except ValidationError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(wo)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _check_template_workflow_warnings(job):
        warnings = []
        has_worksheet = EstWorksheet.objects.filter(job=job).exists()
        has_estimate = Estimate.objects.filter(job=job).exists()
        if has_worksheet and has_estimate:
            warnings.append(
                'This job already has a Worksheet and an Estimate. '
                'Template \u2192 WO is usually for jobs that go straight to work. '
                'Proceed anyway?'
            )
        elif has_worksheet:
            warnings.append(
                'This job already has a Worksheet. '
                'Template \u2192 WO is usually for jobs that go straight to work. '
                'Proceed anyway?'
            )
        elif has_estimate:
            warnings.append(
                'This job already has an Estimate. '
                'Template \u2192 WO is usually for jobs that go straight to work. '
                'Proceed anyway?'
            )
        return warnings
```

- [ ] **Step 4: Run tests**

```bash
python manage.py test tests.test_api_wo_creation.WorkflowWarningTemplateTest tests.test_api_wo_creation.CreateFromTemplateTest -v 2 2>&1 | tail -15
```

Expected: all pass (including the original `CreateFromTemplateTest` which has no worksheet/estimate on the job).

- [ ] **Step 5: Commit**

```bash
git add apps/api/work_orders/views.py tests/test_api_wo_creation.py
git commit -m "$(cat <<'EOF'
feat: soft workflow warning on create-from-template

Returns 200 with warnings when the job already has a worksheet
and/or estimate, advising that template->WO is usually for jobs
that go straight to work. Bypassed with ?confirm=true.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.3: Update permissions for the new actions

**Files:**
- Modify: `apps/api/work_orders/views.py`
- Modify: `tests/test_api_wo_creation.py`

The three new actions need `CanManageJobs` permission. Check that the existing `get_permissions()` catches them — they are non-read, non-task actions, so they fall through to the default `return [IsAuthenticated(), CanManageJobs()]`. The permission tests in 2.1-2.3 already verify this. This task is a verification step.

- [ ] **Step 1: Re-run all creation tests as a worker (no `can_manage_jobs`)**

```bash
python manage.py test tests.test_api_wo_creation -v 2 2>&1 | tail -15
```

Expected: all tests pass, including `test_requires_can_manage_jobs` tests in each class.

- [ ] **Step 2: No code change needed — the default `get_permissions()` already covers custom actions.**

The existing `get_permissions` method (lines 15-25 in views.py) returns `[IsAuthenticated(), CanManageJobs()]` for all actions not in `read_actions` or the `tasks` action. The three new `@action` methods (`create_from_template`, `create_from_estimate`, `copy_from_worksheet`) fall through to this default.

---

## Phase 4: Final checkpoint

### Task 4.1: Full test suite run

**Files:** none

- [ ] **Step 1: Run the full test suite**

```bash
python manage.py test 2>&1 | tail -10
```

Expected: all 2045+ tests pass (baseline from Plan 1 was 2045). The new tests from this plan add ~20+ tests on top.

- [ ] **Step 2: Verify no migration changes**

```bash
python manage.py makemigrations --check --dry-run --skip-checks
```

Expected: "No changes detected" (this plan adds no model changes).

- [ ] **Step 3: Review commit log**

```bash
git log --oneline main..HEAD
```

Plan 2 commits should include:
1. `feat: add standalone /api/plan-tasks/ read-only resource`
2. `feat: expose plan_materials on worksheet PlanTask serializer`
3. `feat: add POST /api/work-orders/create-from-template/ action`
4. `feat: add POST /api/work-orders/create-from-estimate/ action`
5. `feat: add POST /api/work-orders/copy-from-worksheet/ action`
6. `feat: soft workflow warning on create-from-estimate`
7. `feat: soft workflow warning on create-from-template`

---

## Completion Criteria

Plan 2 is complete when:

1. `GET /api/plan-tasks/{id}/` returns PlanTask detail with materials, worksheet, and job context.
2. `POST /api/work-orders/create-from-template/` creates a WO from a template+job.
3. `POST /api/work-orders/create-from-estimate/` creates a WO from an estimate.
4. `POST /api/work-orders/copy-from-worksheet/` creates a WO and copies PlanTasks/PlanMaterials.
5. `create-from-estimate` returns soft warning when job has a worksheet.
6. `create-from-template` returns soft warning when job has a worksheet or estimate.
7. All warnings are bypassed with `?confirm=true`.
8. All new endpoints require `can_manage_jobs` permission (except PlanTask read which is `IsAuthenticated`).
9. All existing tests still pass.
10. New test count is >= 2045 + 20.

## What's Explicitly NOT in Plan 2

- SPA routes for `#/worksheets/[ws_id]/plan-tasks/[pt_id]` — deferred to materials-in-Svelte project which will build out the Svelte worksheet UI.
- SPA WO creation form with warning dialogs — SPA work follows the API.
- Earmark lifecycle relocation (Plan 3).
- PlanTask CRUD on the standalone endpoint (CRUD stays on worksheet nested endpoints).
