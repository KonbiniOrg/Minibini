# API Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the full REST API for Minibini using Django Rest Framework, as specified in `docs/plans/2026-03-07-api-implementation-design.md`.

**Architecture:** Single `apps/api/` Django app with per-domain submodules. All writes delegate to existing service classes. Session auth only initially, `IsAuthenticated` permissions. Full URL tree from day one with 501 stubs for unimplemented features.

**Tech Stack:** Django 5.2, Django REST Framework, existing service layer

**Reference docs:**
- `docs/2026-03-01-api-design.md` — full API spec
- `docs/plans/2026-03-07-api-implementation-design.md` — approved implementation design
- `docs/plans/2026-03-07-permissions-design.md` — permissions design (deferred to later task)

---

## Phase 1: Foundation

### Task 1: Install DRF and Create API App Skeleton

**Files:**
- Modify: `requirements.txt`
- Modify: `minibini/settings.py`
- Modify: `minibini/urls.py`
- Create: `apps/api/__init__.py`
- Create: `apps/api/urls.py`
- Create: `apps/api/permissions.py`
- Create: `apps/api/pagination.py`
- Create: `apps/api/mixins.py`
- Create: all submodule `__init__.py` files
- Test: `tests/test_api_foundation.py`

**Step 1: Install DRF**

```bash
pip install djangorestframework
```

Add to `requirements.txt`:
```
djangorestframework==3.16.0
```

**Step 2: Write the failing test**

```python
# tests/test_api_foundation.py
from django.test import TestCase
from rest_framework.test import APIClient
from tests.base import BaseTestCase


class APIFoundationTest(BaseTestCase):
    """Test that the API root is accessible and DRF is configured."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        from apps.core.models import User
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_api_root_returns_200(self):
        """The API root URL should return 200."""
        response = self.client.get('/api/')
        self.assertEqual(response.status_code, 200)

    def test_api_requires_authentication(self):
        """Unauthenticated requests should return 403."""
        client = APIClient()
        response = client.get('/api/')
        self.assertEqual(response.status_code, 403)
```

**Step 3: Run test to verify it fails**

Run: `python manage.py test tests.test_api_foundation -v2`
Expected: FAIL (no module / URL not found)

**Step 4: Create API app skeleton**

Create all directories:
```
apps/api/
apps/api/auth/
apps/api/jobs/
apps/api/contacts/
apps/api/estimates/
apps/api/worksheets/
apps/api/work_orders/
apps/api/invoicing/
apps/api/purchasing/
apps/api/templates_config/
apps/api/inventory/
apps/api/search/
apps/api/email/
apps/api/time_tracking/
apps/api/expenses/
```

Each directory gets an empty `__init__.py`.

```python
# apps/api/permissions.py
from rest_framework.permissions import IsAuthenticated

# For now, all API views require authentication only.
# Permission atoms (CanManageJobs, etc.) will be added in a later task.
APIDefaultPermission = IsAuthenticated
```

```python
# apps/api/pagination.py
from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100
```

```python
# apps/api/mixins.py
# Shared mixins — populated in Tasks 2-3
```

```python
# apps/api/urls.py
from django.urls import path, include
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_root(request):
    """API root — lists available endpoints."""
    return Response({
        'auth': '/api/auth/',
        'jobs': '/api/jobs/',
        'contacts': '/api/contacts/',
        'businesses': '/api/businesses/',
        'payment-terms': '/api/payment-terms/',
        'est-worksheets': '/api/est-worksheets/',
        'estimates': '/api/estimates/',
        'work-orders': '/api/work-orders/',
        'invoices': '/api/invoices/',
        'purchase-orders': '/api/purchase-orders/',
        'bills': '/api/bills/',
        'price-list-items': '/api/price-list-items/',
        'inventory-items': '/api/inventory-items/',
        'search': '/api/search/',
        'emails': '/api/emails/',
        'work-order-templates': '/api/work-order-templates/',
        'task-templates': '/api/task-templates/',
        'settings': '/api/settings/',
        'line-item-types': '/api/line-item-types/',
    })


app_name = 'api'

urlpatterns = [
    path('', api_root, name='api-root'),
    # Submodule URLs added in subsequent tasks
]
```

Add to `minibini/settings.py` INSTALLED_APPS:
```python
'rest_framework',
'apps.api',
```

Add DRF settings to `minibini/settings.py`:
```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'apps.api.pagination.StandardPagination',
    'PAGE_SIZE': 25,
}
```

Add to `minibini/urls.py`:
```python
path('api/', include('apps.api.urls')),
```

**Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_api_foundation -v2`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/api/ requirements.txt minibini/settings.py minibini/urls.py tests/test_api_foundation.py
git commit -m "feat: create API app skeleton with DRF configuration"
```

---

### Task 2: Shared Mixins — StatusTransitionMixin

**Files:**
- Modify: `apps/api/mixins.py`
- Test: `tests/test_api_mixins.py`

**Step 1: Write the failing test**

```python
# tests/test_api_mixins.py
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework import serializers, viewsets, status
from apps.core.models import User
from apps.core.services import ServiceError
from apps.api.mixins import StatusTransitionMixin
from tests.base import BaseTestCase


class StatusTransitionMixinTest(BaseTestCase):
    """Test StatusTransitionMixin auto-registers action endpoints."""

    def setUp(self):
        super().setUp()
        self.user = User.objects.get(username='dev_user')
        self.factory = APIRequestFactory()

    def test_routine_action_calls_service(self):
        """A routine status action should call the service method and return the updated object."""
        from apps.jobs.models import Job

        # Create a simple viewset that uses the mixin
        class JobSerializer(serializers.ModelSerializer):
            class Meta:
                model = Job
                fields = ['job_id', 'status']

        class TestViewSet(StatusTransitionMixin, viewsets.ModelViewSet):
            queryset = Job.objects.all()
            serializer_class = JobSerializer
            lookup_field = 'pk'
            status_actions = {
                'complete': {'service': lambda pk: Job.objects.filter(pk=pk).update(status=Job.STATUS_COMPLETED)},
            }

        view = TestViewSet.as_view({'post': 'complete'}, detail=True)
        job = Job.objects.first()
        request = self.factory.post(f'/api/jobs/{job.pk}/complete/')
        force_authenticate(request, user=self.user)
        response = view(request, pk=job.pk)
        self.assertEqual(response.status_code, 200)

    def test_exceptional_action_requires_reason(self):
        """An exceptional action (requires_reason=True) should reject requests without a reason."""
        from apps.jobs.models import Job

        class JobSerializer(serializers.ModelSerializer):
            class Meta:
                model = Job
                fields = ['job_id', 'status']

        class TestViewSet(StatusTransitionMixin, viewsets.ModelViewSet):
            queryset = Job.objects.all()
            serializer_class = JobSerializer
            lookup_field = 'pk'
            status_actions = {
                'cancel': {
                    'service': lambda pk, reason=None: Job.objects.filter(pk=pk).update(status=Job.STATUS_CANCELLED),
                    'requires_reason': True,
                },
            }

        view = TestViewSet.as_view({'post': 'cancel'}, detail=True)
        job = Job.objects.first()

        # Without reason — should fail
        request = self.factory.post(f'/api/jobs/{job.pk}/cancel/', {}, format='json')
        force_authenticate(request, user=self.user)
        response = view(request, pk=job.pk)
        self.assertEqual(response.status_code, 400)

        # With reason — should succeed
        request = self.factory.post(f'/api/jobs/{job.pk}/cancel/', {'reason': 'Test cancellation'}, format='json')
        force_authenticate(request, user=self.user)
        response = view(request, pk=job.pk)
        self.assertEqual(response.status_code, 200)

    def test_service_error_returns_400(self):
        """ServiceError from the service method should return 400."""
        from apps.jobs.models import Job

        def failing_service(pk):
            raise ServiceError("Cannot complete this job")

        class JobSerializer(serializers.ModelSerializer):
            class Meta:
                model = Job
                fields = ['job_id', 'status']

        class TestViewSet(StatusTransitionMixin, viewsets.ModelViewSet):
            queryset = Job.objects.all()
            serializer_class = JobSerializer
            lookup_field = 'pk'
            status_actions = {
                'complete': {'service': failing_service},
            }

        view = TestViewSet.as_view({'post': 'complete'}, detail=True)
        job = Job.objects.first()
        request = self.factory.post(f'/api/jobs/{job.pk}/complete/')
        force_authenticate(request, user=self.user)
        response = view(request, pk=job.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Cannot complete this job', str(response.data))
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_mixins -v2`
Expected: FAIL (cannot import StatusTransitionMixin)

**Step 3: Implement StatusTransitionMixin**

```python
# apps/api/mixins.py
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.core.services import ServiceError, NotFoundError


class StatusTransitionMixin:
    """
    Mixin that auto-registers action endpoints from a status_actions dict.

    Subclasses declare:
        status_actions = {
            'complete': {'service': SomeService.complete},
            'cancel': {'service': SomeService.cancel, 'requires_reason': True},
        }

    Each entry becomes a POST action on the viewset.
    If requires_reason is True, validates that 'reason' is in the request body.
    The service callable receives (pk) or (pk, reason=reason).
    """
    status_actions = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for action_name, config in cls.status_actions.items():
            cls._register_status_action(action_name, config)

    @classmethod
    def _register_status_action(cls, action_name, config):
        service_fn = config['service']
        requires_reason = config.get('requires_reason', False)

        @action(detail=True, methods=['post'], url_path=action_name, url_name=action_name)
        def action_view(self, request, pk=None):
            if requires_reason:
                reason = request.data.get('reason', '').strip()
                if not reason:
                    return Response(
                        {'reason': ['This field is required.']},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            try:
                kwargs = {}
                if requires_reason:
                    kwargs['reason'] = request.data['reason']
                service_fn(pk, **kwargs)
            except NotFoundError:
                return Response(
                    {'detail': 'Not found.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
            except ServiceError as e:
                return Response(
                    {'detail': str(e)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            instance = self.get_object()
            serializer = self.get_serializer(instance)
            return Response(serializer.data)

        action_view.__name__ = action_name
        action_view.__qualname__ = f'{cls.__name__}.{action_name}'
        setattr(cls, action_name, action_view)
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_mixins -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/mixins.py tests/test_api_mixins.py
git commit -m "feat: add StatusTransitionMixin for API action endpoints"
```

---

### Task 3: Shared Mixins — LineItemMixin and TaskBundleMixin

**Files:**
- Modify: `apps/api/mixins.py`
- Test: `tests/test_api_line_item_mixin.py`

**Step 1: Write the failing test**

```python
# tests/test_api_line_item_mixin.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User


class LineItemMixinTest(BaseTestCase):
    """Test LineItemMixin provides line-item CRUD actions.
    Full integration tests — tested via Estimate endpoints in Task 9."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_mixin_importable(self):
        """LineItemMixin and TaskBundleMixin should be importable."""
        from apps.api.mixins import LineItemMixin, TaskBundleMixin
        self.assertTrue(hasattr(LineItemMixin, 'add_line_item'))
        self.assertTrue(hasattr(TaskBundleMixin, 'add_task'))
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_line_item_mixin -v2`
Expected: FAIL (cannot import LineItemMixin)

**Step 3: Implement LineItemMixin and TaskBundleMixin**

Add to `apps/api/mixins.py`:

```python
class LineItemMixin:
    """
    Adds line-item CRUD actions to a document viewset.

    Subclasses declare:
        line_item_serializer_class = SomeLineItemSerializer
        line_item_parent_field = 'estimate'  # FK name on line item model

    Uses LineItemService for delete (renumber) and reorder.
    """
    line_item_serializer_class = None
    line_item_parent_field = None

    @action(detail=True, methods=['get', 'post'], url_path='line-items', url_name='line-items')
    def line_items(self, request, pk=None):
        parent = self.get_object()
        if request.method == 'GET':
            items = self._get_line_items_qs(parent)
            serializer = self.line_item_serializer_class(items, many=True)
            return Response(serializer.data)

        serializer = self.line_item_serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(**{self.line_item_parent_field: parent})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='line-items/(?P<item_id>[0-9]+)', url_name='line-item-detail')
    def line_item_detail(self, request, pk=None, item_id=None):
        parent = self.get_object()
        item = self._get_line_item_or_404(parent, item_id)

        if request.method == 'DELETE':
            from apps.core.services import LineItemService
            LineItemService.delete_line_item_with_renumber(item)
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = self.line_item_serializer_class(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=['post'],
            url_path='line-items/reorder', url_name='line-items-reorder')
    def reorder_line_items(self, request, pk=None):
        parent = self.get_object()
        item_ids = request.data.get('item_ids', [])
        if not item_ids:
            return Response(
                {'item_ids': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        items_qs = self._get_line_items_qs(parent)
        # Reorder by setting line_number to match position in item_ids
        for position, item_id in enumerate(item_ids, start=1):
            items_qs.filter(pk=item_id).update(line_number=position)
        items = items_qs.order_by('line_number')
        serializer = self.line_item_serializer_class(items, many=True)
        return Response(serializer.data)

    def _get_line_items_qs(self, parent):
        return parent.__class__._meta.get_field(
            self._get_reverse_name()
        ).related_model.objects.filter(
            **{self.line_item_parent_field: parent}
        ).order_by('line_number')

    def _get_reverse_name(self):
        """Get the related manager name for line items on the parent."""
        model = self.line_item_serializer_class.Meta.model
        for field in model._meta.fields:
            if field.name == self.line_item_parent_field:
                return field.related_query_name()
        return self.line_item_parent_field

    def _get_line_item_or_404(self, parent, item_id):
        model = self.line_item_serializer_class.Meta.model
        try:
            return model.objects.get(
                pk=item_id,
                **{self.line_item_parent_field: parent}
            )
        except model.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()


class TaskBundleMixin:
    """
    Adds task and bundle CRUD actions to a container viewset (EstWorksheet, WorkOrder).

    Subclasses declare:
        task_serializer_class = SomeTaskSerializer
        bundle_serializer_class = SomeBundleSerializer
        container_field = 'est_worksheet'  # FK name on Task/TaskBundle
    """
    task_serializer_class = None
    bundle_serializer_class = None
    container_field = None

    @action(detail=True, methods=['get', 'post'], url_path='tasks', url_name='tasks')
    def tasks(self, request, pk=None):
        container = self.get_object()
        if request.method == 'GET':
            from apps.jobs.models import Task
            tasks = Task.objects.filter(**{self.container_field: container}).order_by('sort_order')
            serializer = self.task_serializer_class(tasks, many=True)
            return Response(serializer.data)

        serializer = self.task_serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(**{self.container_field: container})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='tasks/(?P<task_id>[0-9]+)', url_name='task-detail')
    def task_detail(self, request, pk=None, task_id=None):
        container = self.get_object()
        task = self._get_task_or_404(container, task_id)

        if request.method == 'DELETE':
            task.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = self.task_serializer_class(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=['get', 'post'], url_path='bundles', url_name='bundles')
    def bundles(self, request, pk=None):
        container = self.get_object()
        if request.method == 'GET':
            from apps.jobs.models import TaskBundle
            bundles = TaskBundle.objects.filter(**{self.container_field: container}).order_by('sort_order')
            serializer = self.bundle_serializer_class(bundles, many=True)
            return Response(serializer.data)

        serializer = self.bundle_serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(**{self.container_field: container})
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch', 'delete'],
            url_path='bundles/(?P<bundle_id>[0-9]+)', url_name='bundle-detail')
    def bundle_detail(self, request, pk=None, bundle_id=None):
        container = self.get_object()
        bundle = self._get_bundle_or_404(container, bundle_id)

        if request.method == 'DELETE':
            # Unbundle tasks first (revert to direct), then delete bundle
            from apps.jobs.models import Task
            Task.objects.filter(bundle=bundle).update(
                bundle=None, mapping_strategy='direct'
            )
            bundle.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = self.bundle_serializer_class(bundle, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=['post'],
            url_path='bundles/(?P<bundle_id>[0-9]+)/add-tasks', url_name='bundle-add-tasks')
    def add_tasks_to_bundle(self, request, pk=None, bundle_id=None):
        container = self.get_object()
        bundle = self._get_bundle_or_404(container, bundle_id)
        task_ids = request.data.get('task_ids', [])
        if not task_ids:
            return Response({'task_ids': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
        from apps.jobs.models import Task
        Task.objects.filter(pk__in=task_ids, **{self.container_field: container}).update(
            bundle=bundle, mapping_strategy='bundle'
        )
        serializer = self.bundle_serializer_class(bundle)
        return Response(serializer.data)

    @action(detail=True, methods=['post'],
            url_path='bundles/(?P<bundle_id>[0-9]+)/remove-tasks', url_name='bundle-remove-tasks')
    def remove_tasks_from_bundle(self, request, pk=None, bundle_id=None):
        container = self.get_object()
        bundle = self._get_bundle_or_404(container, bundle_id)
        task_ids = request.data.get('task_ids', [])
        if not task_ids:
            return Response({'task_ids': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
        from apps.jobs.models import Task
        Task.objects.filter(pk__in=task_ids, bundle=bundle).update(
            bundle=None, mapping_strategy='direct'
        )
        serializer = self.bundle_serializer_class(bundle)
        return Response(serializer.data)

    def _get_task_or_404(self, container, task_id):
        from apps.jobs.models import Task
        try:
            return Task.objects.get(pk=task_id, **{self.container_field: container})
        except Task.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()

    def _get_bundle_or_404(self, container, bundle_id):
        from apps.jobs.models import TaskBundle
        try:
            return TaskBundle.objects.get(pk=bundle_id, **{self.container_field: container})
        except TaskBundle.DoesNotExist:
            from rest_framework.exceptions import NotFound
            raise NotFound()
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_line_item_mixin -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/mixins.py tests/test_api_line_item_mixin.py
git commit -m "feat: add LineItemMixin and TaskBundleMixin for API"
```

---

### Task 4: Auth Module

**Files:**
- Create: `apps/api/auth/serializers.py`
- Create: `apps/api/auth/views.py`
- Create: `apps/api/auth/urls.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_auth.py`

**Step 1: Write the failing test**

```python
# tests/test_api_auth.py
from rest_framework.test import APIClient
from rest_framework import status
from tests.base import BaseTestCase
from apps.core.models import User


class AuthAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')

    def test_login_success(self):
        response = self.client.post('/api/auth/login/', {
            'username': 'dev_user',
            'password': 'dev_password',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'dev_user')

    def test_login_bad_credentials(self):
        response = self.client.post('/api/auth/login/', {
            'username': 'dev_user',
            'password': 'wrong',
        }, format='json')
        self.assertEqual(response.status_code, 400)

    def test_logout(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post('/api/auth/logout/')
        self.assertEqual(response.status_code, 200)

    def test_me_authenticated(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'dev_user')

    def test_me_unauthenticated(self):
        response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, 403)

    def test_jwt_refresh_returns_501(self):
        response = self.client.post('/api/auth/refresh/')
        self.assertEqual(response.status_code, 501)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_auth -v2`
Expected: FAIL

**Step 3: Implement auth module**

```python
# apps/api/auth/serializers.py
from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField(source='pk', read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
```

```python
# apps/api/auth/views.py
from django.contrib.auth import authenticate, login, logout
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from .serializers import LoginSerializer, UserSerializer


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = authenticate(
        request,
        username=serializer.validated_data['username'],
        password=serializer.validated_data['password'],
    )
    if user is None:
        return Response(
            {'detail': 'Invalid credentials.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    login(request, user)
    return Response(UserSerializer(user).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    logout(request)
    return Response({'detail': 'Logged out.'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me_view(request):
    return Response(UserSerializer(request.user).data)


@api_view(['POST'])
@permission_classes([AllowAny])
def refresh_stub(request):
    return Response(
        {'detail': 'Not yet implemented.', 'endpoint': 'POST /api/auth/refresh/'},
        status=status.HTTP_501_NOT_IMPLEMENTED,
    )
```

```python
# apps/api/auth/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='auth-login'),
    path('logout/', views.logout_view, name='auth-logout'),
    path('me/', views.me_view, name='auth-me'),
    path('refresh/', views.refresh_stub, name='auth-refresh'),
]
```

Update `apps/api/urls.py` to include auth:
```python
urlpatterns = [
    path('', api_root, name='api-root'),
    path('auth/', include('apps.api.auth.urls')),
]
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_auth -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/auth/ apps/api/urls.py tests/test_api_auth.py
git commit -m "feat: add auth API endpoints (login, logout, me, JWT stub)"
```

---

## Phase 2: Core Domain APIs

### Task 5: Jobs API

**Files:**
- Create: `apps/api/jobs/serializers.py`
- Create: `apps/api/jobs/views.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_jobs.py`

**Step 1: Write the failing test**

```python
# tests/test_api_jobs.py
from rest_framework.test import APIClient
from rest_framework import status
from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import Job


class JobAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_jobs(self):
        response = self.client.get('/api/jobs/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_create_job(self):
        from apps.contacts.models import Contact
        contact = Contact.objects.first()
        response = self.client.post('/api/jobs/', {
            'name': 'Test API Job',
            'contact': contact.pk,
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['name'], 'Test API Job')
        self.assertIn('job_number', response.data)

    def test_retrieve_job(self):
        job = Job.objects.first()
        response = self.client.get(f'/api/jobs/{job.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['job_id'], job.pk)

    def test_update_job(self):
        job = Job.objects.first()
        response = self.client.patch(f'/api/jobs/{job.pk}/', {
            'name': 'Updated Name',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Updated Name')

    def test_delete_job(self):
        job = Job.objects.first()
        response = self.client.delete(f'/api/jobs/{job.pk}/')
        self.assertEqual(response.status_code, 204)

    def test_complete_job(self):
        job = Job.objects.filter(status=Job.STATUS_APPROVED).first()
        if not job:
            job = Job.objects.first()
            job.status = Job.STATUS_APPROVED
            job.save()
        response = self.client.post(f'/api/jobs/{job.pk}/complete/')
        self.assertEqual(response.status_code, 200)

    def test_cancel_job_requires_reason(self):
        job = Job.objects.first()
        response = self.client.post(f'/api/jobs/{job.pk}/cancel/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_cancel_job_with_reason(self):
        job = Job.objects.first()
        response = self.client.post(f'/api/jobs/{job.pk}/cancel/', {
            'reason': 'Customer withdrew',
        }, format='json')
        self.assertEqual(response.status_code, 200)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_jobs -v2`
Expected: FAIL

**Step 3: Implement jobs API**

```python
# apps/api/jobs/serializers.py
from rest_framework import serializers
from apps.jobs.models import Job


class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = [
            'job_id', 'job_number', 'name', 'status',
            'contact', 'customer_po_number', 'description',
            'created_date', 'start_date', 'due_date', 'completed_date',
        ]
        read_only_fields = ['job_id', 'job_number', 'created_date', 'completed_date']
```

```python
# apps/api/jobs/views.py
from rest_framework import viewsets
from apps.jobs.models import Job
from apps.jobs.services import JobService
from apps.core.services import ServiceError
from apps.api.mixins import StatusTransitionMixin
from .serializers import JobSerializer


class JobViewSet(StatusTransitionMixin, viewsets.ModelViewSet):
    queryset = Job.objects.all().order_by('-created_date')
    serializer_class = JobSerializer
    lookup_field = 'pk'

    status_actions = {
        'complete': {'service': lambda pk: JobService.update_job(pk, status=Job.STATUS_COMPLETED)},
        'cancel': {
            'service': lambda pk, reason=None: JobService.update_job(pk, status=Job.STATUS_CANCELLED),
            'requires_reason': True,
        },
        'reopen': {
            'service': lambda pk, reason=None: JobService.update_job(pk, status=Job.STATUS_DRAFT),
            'requires_reason': True,
        },
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        job = JobService.create_job(**data)
        serializer.instance = job

    def perform_update(self, serializer):
        JobService.update_job(self.get_object().pk, **serializer.validated_data)
```

Add to `apps/api/urls.py`:
```python
from rest_framework.routers import DefaultRouter
from apps.api.jobs.views import JobViewSet

router = DefaultRouter()
router.register(r'jobs', JobViewSet, basename='job')

urlpatterns = [
    path('', api_root, name='api-root'),
    path('auth/', include('apps.api.auth.urls')),
] + router.urls
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_jobs -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/jobs/ apps/api/urls.py tests/test_api_jobs.py
git commit -m "feat: add jobs API with CRUD and status actions"
```

---

### Task 6: Contacts API (Contacts, Businesses, Payment Terms)

**Files:**
- Create: `apps/api/contacts/serializers.py`
- Create: `apps/api/contacts/views.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_contacts.py`

**Step 1: Write the failing test**

```python
# tests/test_api_contacts.py
from rest_framework.test import APIClient
from rest_framework import status
from tests.base import BaseTestCase
from apps.core.models import User
from apps.contacts.models import Contact, Business, PaymentTerms


class ContactAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_contacts(self):
        response = self.client.get('/api/contacts/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_create_contact(self):
        response = self.client.post('/api/contacts/', {
            'first_name': 'New',
            'last_name': 'Contact',
            'email': 'new@example.com',
            'mobile_number': '555-000-0000',
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_retrieve_contact(self):
        contact = Contact.objects.first()
        response = self.client.get(f'/api/contacts/{contact.pk}/')
        self.assertEqual(response.status_code, 200)

    def test_update_contact(self):
        contact = Contact.objects.first()
        response = self.client.patch(f'/api/contacts/{contact.pk}/', {
            'first_name': 'Updated',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['first_name'], 'Updated')

    def test_delete_contact_without_confirm_returns_impact(self):
        contact = Contact.objects.first()
        response = self.client.delete(f'/api/contacts/{contact.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('confirm_required', response.data)

    def test_delete_contact_with_confirm(self):
        # Create a standalone contact for safe deletion
        contact = Contact.objects.create(
            first_name='Delete', last_name='Me',
            email='delete@example.com', mobile_number='555-999-9999',
        )
        response = self.client.delete(f'/api/contacts/{contact.pk}/?confirm=true')
        self.assertEqual(response.status_code, 204)


class BusinessAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_businesses(self):
        response = self.client.get('/api/businesses/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_business(self):
        business = Business.objects.first()
        response = self.client.get(f'/api/businesses/{business.pk}/')
        self.assertEqual(response.status_code, 200)

    def test_set_default_contact(self):
        business = Business.objects.first()
        contact = Contact.objects.filter(business=business).first()
        if contact:
            response = self.client.post(
                f'/api/businesses/{business.pk}/set-default-contact/',
                {'contact_id': contact.pk}, format='json'
            )
            self.assertEqual(response.status_code, 200)


class PaymentTermsAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_payment_terms(self):
        response = self.client.get('/api/payment-terms/')
        self.assertEqual(response.status_code, 200)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_contacts -v2`
Expected: FAIL

**Step 3: Implement contacts API**

```python
# apps/api/contacts/serializers.py
from rest_framework import serializers
from apps.contacts.models import Contact, Business, PaymentTerms


class ContactSerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)

    class Meta:
        model = Contact
        fields = [
            'contact_id', 'first_name', 'middle_initial', 'last_name', 'name',
            'email', 'mobile_number', 'work_number', 'home_number',
            'addr1', 'addr2', 'addr3', 'city', 'municipality',
            'postal_code', 'country_code', 'business',
        ]
        read_only_fields = ['contact_id']


class BusinessSerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = [
            'business_id', 'our_reference_code', 'business_name',
            'business_address', 'business_phone', 'tax_exemption_number',
            'website', 'terms', 'default_contact', 'tax_multiplier',
        ]
        read_only_fields = ['business_id', 'our_reference_code']


class PaymentTermsSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTerms
        fields = '__all__'
```

```python
# apps/api/contacts/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.contacts.models import Contact, Business, PaymentTerms
from apps.contacts.services import ContactService
from apps.core.services import ServiceError, NotFoundError
from .serializers import ContactSerializer, BusinessSerializer, PaymentTermsSerializer


class ContactViewSet(viewsets.ModelViewSet):
    queryset = Contact.objects.all().order_by('last_name', 'first_name')
    serializer_class = ContactSerializer
    lookup_field = 'pk'

    def perform_create(self, serializer):
        data = serializer.validated_data
        business_pk = data.pop('business', None)
        if business_pk:
            business_pk = business_pk.pk if hasattr(business_pk, 'pk') else business_pk
        contact = ContactService.create_contact(business_pk=business_pk, **data)
        serializer.instance = contact

    def perform_update(self, serializer):
        data = serializer.validated_data
        business = data.pop('business', None)
        kwargs = dict(data)
        if business is not None:
            kwargs['business_pk'] = business.pk if hasattr(business, 'pk') else business
        ContactService.update_contact(self.get_object().pk, **kwargs)

    def destroy(self, request, *args, **kwargs):
        contact = self.get_object()
        confirm = request.query_params.get('confirm', '').lower() == 'true'

        if not confirm:
            from apps.jobs.models import Job
            impact = {
                'jobs': Job.objects.filter(contact=contact).count(),
            }
            return Response({
                'confirm_required': True,
                'impact': impact,
            })

        try:
            ContactService.delete_contact(contact.pk)
        except ServiceError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BusinessViewSet(viewsets.ModelViewSet):
    queryset = Business.objects.all().order_by('business_name')
    serializer_class = BusinessSerializer
    lookup_field = 'pk'

    def perform_create(self, serializer):
        data = serializer.validated_data
        default_contact = data.pop('default_contact', None)
        if default_contact and hasattr(default_contact, 'pk'):
            default_contact = default_contact.pk
        contacts_data = []
        if default_contact:
            contacts_data = [{'contact_pk': default_contact}]
        business = ContactService.create_business(contacts_data=contacts_data, **data)
        serializer.instance = business

    def perform_update(self, serializer):
        ContactService.update_business(self.get_object().pk, **serializer.validated_data)

    def destroy(self, request, *args, **kwargs):
        business = self.get_object()
        confirm = request.query_params.get('confirm', '').lower() == 'true'

        if not confirm:
            from apps.jobs.models import Job
            from apps.purchasing.models import PurchaseOrder, Bill
            impact = {
                'jobs': Job.objects.filter(contact__business=business).count(),
                'purchase_orders': PurchaseOrder.objects.filter(business=business).count(),
                'bills': Bill.objects.filter(business=business).count(),
                'contacts': Contact.objects.filter(business=business).count(),
            }
            return Response({
                'confirm_required': True,
                'impact': impact,
            })

        try:
            ContactService.delete_business(business.pk)
        except ServiceError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='set-default-contact')
    def set_default_contact(self, request, pk=None):
        contact_id = request.data.get('contact_id')
        if not contact_id:
            return Response(
                {'contact_id': ['This field is required.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            ContactService.set_default_contact(pk, contact_id)
        except (ServiceError, NotFoundError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        business = self.get_object()
        return Response(BusinessSerializer(business).data)


class PaymentTermsViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PaymentTerms.objects.all()
    serializer_class = PaymentTermsSerializer
    pagination_class = None
```

Update `apps/api/urls.py` — register the new viewsets on the router:
```python
from apps.api.contacts.views import ContactViewSet, BusinessViewSet, PaymentTermsViewSet

router.register(r'contacts', ContactViewSet, basename='contact')
router.register(r'businesses', BusinessViewSet, basename='business')
router.register(r'payment-terms', PaymentTermsViewSet, basename='payment-terms')
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_contacts -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/contacts/ apps/api/urls.py tests/test_api_contacts.py
git commit -m "feat: add contacts, businesses, and payment terms API"
```

---

### Task 7: Estimates API (with Line Items)

**Files:**
- Create: `apps/api/estimates/serializers.py`
- Create: `apps/api/estimates/views.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_estimates.py`

**Step 1: Write the failing test**

```python
# tests/test_api_estimates.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.estimates.models import Estimate, EstimateLineItem


class EstimateAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_estimates(self):
        response = self.client.get('/api/estimates/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_estimate(self):
        estimate = Estimate.objects.first()
        response = self.client.get(f'/api/estimates/{estimate.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('line_items', response.data)

    def test_update_estimate(self):
        estimate = Estimate.objects.filter(status=Estimate.STATUS_DRAFT).first()
        if estimate:
            response = self.client.patch(f'/api/estimates/{estimate.pk}/', {
                'status': Estimate.STATUS_DRAFT,
            }, format='json')
            self.assertEqual(response.status_code, 200)

    def test_add_line_item(self):
        estimate = Estimate.objects.first()
        response = self.client.post(f'/api/estimates/{estimate.pk}/line-items/', {
            'qty': '2.00',
            'units': 'ea',
            'description': 'API test item',
            'price': '100.00',
        }, format='json')
        self.assertIn(response.status_code, [200, 201])

    def test_list_line_items(self):
        estimate = Estimate.objects.first()
        response = self.client.get(f'/api/estimates/{estimate.pk}/line-items/')
        self.assertEqual(response.status_code, 200)

    def test_delete_line_item(self):
        line_item = EstimateLineItem.objects.first()
        if line_item:
            estimate = line_item.estimate
            response = self.client.delete(
                f'/api/estimates/{estimate.pk}/line-items/{line_item.pk}/'
            )
            self.assertEqual(response.status_code, 204)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_estimates -v2`
Expected: FAIL

**Step 3: Implement estimates API**

```python
# apps/api/estimates/serializers.py
from rest_framework import serializers
from apps.estimates.models import Estimate, EstimateLineItem


class EstimateLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = EstimateLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'price_list_item',
            'qty', 'units', 'description', 'price',
            'line_item_type', 'taxable_override', 'tax_rate_override',
        ]
        read_only_fields = ['line_item_id']


class EstimateSerializer(serializers.ModelSerializer):
    line_items = EstimateLineItemSerializer(
        source='estimatelineitem_set', many=True, read_only=True
    )

    class Meta:
        model = Estimate
        fields = [
            'estimate_id', 'job', 'estimate_number', 'version', 'status',
            'parent', 'created_date', 'sent_date', 'closed_date',
            'expiration_date', 'line_items',
        ]
        read_only_fields = [
            'estimate_id', 'estimate_number', 'version',
            'created_date', 'sent_date', 'closed_date',
        ]
```

```python
# apps/api/estimates/views.py
from rest_framework import viewsets
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from apps.api.mixins import StatusTransitionMixin, LineItemMixin
from .serializers import EstimateSerializer, EstimateLineItemSerializer


class EstimateViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = Estimate.objects.all().order_by('-created_date')
    serializer_class = EstimateSerializer
    lookup_field = 'pk'

    # Line item mixin config
    line_item_serializer_class = EstimateLineItemSerializer
    line_item_parent_field = 'estimate'

    # Status actions
    status_actions = {
        'mark-open': {'service': EstimateService.mark_open},
        'revise': {'service': EstimateService.revise_estimate},
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        job = data.get('job')
        job_pk = job.pk if hasattr(job, 'pk') else job
        estimate = EstimateService.create_for_job(job_pk)
        serializer.instance = estimate

    def perform_update(self, serializer):
        # Direct field updates via serializer save
        serializer.save()
```

Update `apps/api/urls.py`:
```python
from apps.api.estimates.views import EstimateViewSet
router.register(r'estimates', EstimateViewSet, basename='estimate')
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_estimates -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/estimates/ apps/api/urls.py tests/test_api_estimates.py
git commit -m "feat: add estimates API with line items and status actions"
```

---

### Task 8: EstWorksheets API (with Tasks and Bundles)

**Files:**
- Create: `apps/api/worksheets/serializers.py`
- Create: `apps/api/worksheets/views.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_worksheets.py`

**Step 1: Write the failing test**

```python
# tests/test_api_worksheets.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.estimates.models import EstWorksheet
from apps.jobs.models import Job


class WorksheetAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_worksheets(self):
        response = self.client.get('/api/est-worksheets/')
        self.assertEqual(response.status_code, 200)

    def test_create_worksheet(self):
        job = Job.objects.first()
        response = self.client.post('/api/est-worksheets/', {
            'job': job.pk,
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_retrieve_worksheet(self):
        ws = EstWorksheet.objects.first()
        if ws:
            response = self.client.get(f'/api/est-worksheets/{ws.pk}/')
            self.assertEqual(response.status_code, 200)

    def test_list_tasks(self):
        ws = EstWorksheet.objects.first()
        if ws:
            response = self.client.get(f'/api/est-worksheets/{ws.pk}/tasks/')
            self.assertEqual(response.status_code, 200)

    def test_generate_estimate(self):
        ws = EstWorksheet.objects.filter(status='draft').first()
        if ws:
            response = self.client.post(f'/api/est-worksheets/{ws.pk}/generate-estimate/')
            self.assertIn(response.status_code, [200, 400])

    def test_revise_worksheet(self):
        ws = EstWorksheet.objects.filter(status='final').first()
        if ws:
            response = self.client.post(f'/api/est-worksheets/{ws.pk}/revise/')
            self.assertEqual(response.status_code, 200)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_worksheets -v2`
Expected: FAIL

**Step 3: Implement worksheets API**

```python
# apps/api/worksheets/serializers.py
from rest_framework import serializers
from apps.estimates.models import EstWorksheet
from apps.jobs.models import Task, TaskBundle


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = [
            'task_id', 'name', 'description', 'sort_order',
            'units', 'rate', 'est_qty', 'line_item_type',
            'mapping_strategy', 'bundle', 'parent_task', 'assignee',
        ]
        read_only_fields = ['task_id', 'sort_order']


class TaskBundleSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(source='task_set', many=True, read_only=True)

    class Meta:
        model = TaskBundle
        fields = [
            'id', 'name', 'description', 'line_item_type',
            'sort_order', 'tasks',
        ]
        read_only_fields = ['id', 'sort_order']


class EstWorksheetSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(source='task_set', many=True, read_only=True)
    bundles = TaskBundleSerializer(source='taskbundle_set', many=True, read_only=True)

    class Meta:
        model = EstWorksheet
        fields = [
            'est_worksheet_id', 'job', 'template', 'estimate',
            'status', 'parent', 'created_date', 'tasks', 'bundles',
        ]
        read_only_fields = ['est_worksheet_id', 'created_date', 'status']
```

```python
# apps/api/worksheets/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.estimates.models import EstWorksheet
from apps.estimates.services import WorksheetService, EstimateGenerationService
from apps.core.services import ServiceError
from apps.api.mixins import StatusTransitionMixin, TaskBundleMixin
from .serializers import EstWorksheetSerializer, TaskSerializer, TaskBundleSerializer


class EstWorksheetViewSet(StatusTransitionMixin, TaskBundleMixin, viewsets.ModelViewSet):
    queryset = EstWorksheet.objects.all().order_by('-created_date')
    serializer_class = EstWorksheetSerializer
    lookup_field = 'pk'

    # TaskBundleMixin config
    task_serializer_class = TaskSerializer
    bundle_serializer_class = TaskBundleSerializer
    container_field = 'est_worksheet'

    status_actions = {
        'revise': {'service': WorksheetService.revise_worksheet},
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        job = data.get('job')
        job_pk = job.pk if hasattr(job, 'pk') else job
        template = data.get('template')
        template_pk = template.pk if template and hasattr(template, 'pk') else template
        ws = WorksheetService.create_worksheet(job_pk, template_pk=template_pk)
        serializer.instance = ws

    @action(detail=True, methods=['post'], url_path='generate-estimate')
    def generate_estimate(self, request, pk=None):
        worksheet = self.get_object()
        try:
            estimate = EstimateGenerationService.generate_estimate_from_worksheet(worksheet)
        except ServiceError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'detail': 'Estimate generated.',
            'estimate_id': estimate.pk,
            'estimate_number': estimate.estimate_number,
        })
```

Update `apps/api/urls.py`:
```python
from apps.api.worksheets.views import EstWorksheetViewSet
router.register(r'est-worksheets', EstWorksheetViewSet, basename='est-worksheet')
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_worksheets -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/worksheets/ apps/api/urls.py tests/test_api_worksheets.py
git commit -m "feat: add est-worksheets API with tasks, bundles, and estimate generation"
```

---

### Task 9: Work Orders API

**Files:**
- Create: `apps/api/work_orders/serializers.py`
- Create: `apps/api/work_orders/views.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_work_orders.py`

**Step 1: Write the failing test**

```python
# tests/test_api_work_orders.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.jobs.models import WorkOrder, Job


class WorkOrderAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_work_orders(self):
        response = self.client.get('/api/work-orders/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_work_order(self):
        wo = WorkOrder.objects.first()
        if wo:
            response = self.client.get(f'/api/work-orders/{wo.pk}/')
            self.assertEqual(response.status_code, 200)

    def test_create_work_order(self):
        job = Job.objects.first()
        response = self.client.post('/api/work-orders/', {
            'job': job.pk,
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_complete_work_order(self):
        wo = WorkOrder.objects.filter(status=WorkOrder.STATUS_INCOMPLETE).first()
        if wo:
            response = self.client.post(f'/api/work-orders/{wo.pk}/complete/')
            self.assertEqual(response.status_code, 200)

    def test_block_requires_reason(self):
        wo = WorkOrder.objects.first()
        if wo:
            response = self.client.post(f'/api/work-orders/{wo.pk}/block/', {}, format='json')
            self.assertEqual(response.status_code, 400)

    def test_list_tasks(self):
        wo = WorkOrder.objects.first()
        if wo:
            response = self.client.get(f'/api/work-orders/{wo.pk}/tasks/')
            self.assertEqual(response.status_code, 200)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_work_orders -v2`
Expected: FAIL

**Step 3: Implement work orders API**

```python
# apps/api/work_orders/serializers.py
from rest_framework import serializers
from apps.jobs.models import WorkOrder, Blep
from apps.api.worksheets.serializers import TaskSerializer, TaskBundleSerializer


class BlepSerializer(serializers.ModelSerializer):
    class Meta:
        model = Blep
        fields = ['blep_id', 'user', 'task', 'start_time', 'end_time']
        read_only_fields = ['blep_id']


class WorkOrderSerializer(serializers.ModelSerializer):
    tasks = TaskSerializer(source='task_set', many=True, read_only=True)
    bundles = TaskBundleSerializer(source='taskbundle_set', many=True, read_only=True)

    class Meta:
        model = WorkOrder
        fields = [
            'work_order_id', 'job', 'template', 'status',
            'tasks', 'bundles',
        ]
        read_only_fields = ['work_order_id']
```

```python
# apps/api/work_orders/views.py
from rest_framework import viewsets
from apps.jobs.models import WorkOrder
from apps.jobs.services import WorkOrderService
from apps.api.mixins import StatusTransitionMixin, TaskBundleMixin
from apps.api.worksheets.serializers import TaskSerializer, TaskBundleSerializer
from .serializers import WorkOrderSerializer


class WorkOrderViewSet(StatusTransitionMixin, TaskBundleMixin, viewsets.ModelViewSet):
    queryset = WorkOrder.objects.all()
    serializer_class = WorkOrderSerializer
    lookup_field = 'pk'

    # TaskBundleMixin config
    task_serializer_class = TaskSerializer
    bundle_serializer_class = TaskBundleSerializer
    container_field = 'work_order'

    status_actions = {
        'complete': {
            'service': lambda pk: WorkOrderService.update_status(pk, WorkOrder.STATUS_COMPLETE),
        },
        'block': {
            'service': lambda pk, reason=None: WorkOrderService.update_status(pk, WorkOrder.STATUS_BLOCKED),
            'requires_reason': True,
        },
        'cancel': {
            'service': lambda pk, reason=None: WorkOrderService.update_status(pk, WorkOrder.STATUS_DRAFT),
            'requires_reason': True,
        },
        'reopen': {
            'service': lambda pk, reason=None: WorkOrderService.update_status(pk, WorkOrder.STATUS_INCOMPLETE),
            'requires_reason': True,
        },
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        job = data.get('job')
        wo = WorkOrderService.create_direct(job)
        serializer.instance = wo
```

Update `apps/api/urls.py`:
```python
from apps.api.work_orders.views import WorkOrderViewSet
router.register(r'work-orders', WorkOrderViewSet, basename='work-order')
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_work_orders -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/work_orders/ apps/api/urls.py tests/test_api_work_orders.py
git commit -m "feat: add work orders API with tasks, bundles, and status actions"
```

---

## Phase 3: Financial APIs

### Task 10: Invoicing API

**Files:**
- Create: `apps/api/invoicing/serializers.py`
- Create: `apps/api/invoicing/views.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_invoicing.py`

**Step 1: Write the failing test**

```python
# tests/test_api_invoicing.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.invoicing.models import Invoice, InvoiceLineItem


class InvoiceAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_invoices(self):
        response = self.client.get('/api/invoices/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_invoice(self):
        invoice = Invoice.objects.first()
        if invoice:
            response = self.client.get(f'/api/invoices/{invoice.pk}/')
            self.assertEqual(response.status_code, 200)
            self.assertIn('line_items', response.data)

    def test_add_line_item(self):
        invoice = Invoice.objects.first()
        if invoice:
            response = self.client.post(f'/api/invoices/{invoice.pk}/line-items/', {
                'qty': '1.00',
                'units': 'hr',
                'description': 'Consulting',
                'price': '150.00',
            }, format='json')
            self.assertIn(response.status_code, [200, 201])

    def test_cancel_invoice_requires_reason(self):
        invoice = Invoice.objects.first()
        if invoice:
            response = self.client.post(f'/api/invoices/{invoice.pk}/cancel/', {}, format='json')
            self.assertEqual(response.status_code, 400)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_invoicing -v2`
Expected: FAIL

**Step 3: Implement invoicing API**

```python
# apps/api/invoicing/serializers.py
from rest_framework import serializers
from apps.invoicing.models import Invoice, InvoiceLineItem


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'price_list_item',
            'qty', 'units', 'description', 'price',
            'line_item_type', 'taxable_override', 'tax_rate_override',
        ]
        read_only_fields = ['line_item_id']


class InvoiceSerializer(serializers.ModelSerializer):
    line_items = InvoiceLineItemSerializer(
        source='invoicelineitem_set', many=True, read_only=True
    )

    class Meta:
        model = Invoice
        fields = [
            'invoice_id', 'job', 'invoice_number', 'status',
            'created_date', 'sent_date', 'closed_date', 'line_items',
        ]
        read_only_fields = [
            'invoice_id', 'invoice_number', 'created_date',
            'sent_date', 'closed_date',
        ]
```

```python
# apps/api/invoicing/views.py
from rest_framework import viewsets
from apps.invoicing.models import Invoice
from apps.api.mixins import StatusTransitionMixin, LineItemMixin
from .serializers import InvoiceSerializer, InvoiceLineItemSerializer


class InvoiceViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = Invoice.objects.all().order_by('-created_date')
    serializer_class = InvoiceSerializer
    lookup_field = 'pk'

    # Line item mixin config
    line_item_serializer_class = InvoiceLineItemSerializer
    line_item_parent_field = 'invoice'

    status_actions = {
        'cancel': {
            'service': lambda pk, reason=None: Invoice.objects.filter(pk=pk).update(status='cancelled'),
            'requires_reason': True,
        },
    }

    def perform_create(self, serializer):
        serializer.save()
```

Update `apps/api/urls.py`:
```python
from apps.api.invoicing.views import InvoiceViewSet
router.register(r'invoices', InvoiceViewSet, basename='invoice')
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_invoicing -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/invoicing/ apps/api/urls.py tests/test_api_invoicing.py
git commit -m "feat: add invoicing API with line items and status actions"
```

---

### Task 11: Purchasing API (POs and Bills)

**Files:**
- Create: `apps/api/purchasing/serializers.py`
- Create: `apps/api/purchasing/views.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_purchasing.py`

**Step 1: Write the failing test**

```python
# tests/test_api_purchasing.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.purchasing.models import PurchaseOrder, Bill


class PurchaseOrderAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_purchase_orders(self):
        response = self.client.get('/api/purchase-orders/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_po(self):
        po = PurchaseOrder.objects.first()
        if po:
            response = self.client.get(f'/api/purchase-orders/{po.pk}/')
            self.assertEqual(response.status_code, 200)
            self.assertIn('line_items', response.data)

    def test_create_po(self):
        from apps.contacts.models import Business
        business = Business.objects.first()
        response = self.client.post('/api/purchase-orders/', {
            'business': business.pk,
        }, format='json')
        self.assertIn(response.status_code, [201, 400])

    def test_add_line_item(self):
        po = PurchaseOrder.objects.first()
        if po:
            response = self.client.post(f'/api/purchase-orders/{po.pk}/line-items/', {
                'qty': '5.00',
                'units': 'ea',
                'description': 'Widgets',
                'price': '25.00',
            }, format='json')
            self.assertIn(response.status_code, [200, 201])


class BillAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_bills(self):
        response = self.client.get('/api/bills/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_bill(self):
        bill = Bill.objects.first()
        if bill:
            response = self.client.get(f'/api/bills/{bill.pk}/')
            self.assertEqual(response.status_code, 200)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_purchasing -v2`
Expected: FAIL

**Step 3: Implement purchasing API**

```python
# apps/api/purchasing/serializers.py
from rest_framework import serializers
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem, Bill, BillLineItem


class POLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchaseOrderLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'price_list_item',
            'qty', 'units', 'description', 'price', 'job',
            'line_item_type', 'taxable_override', 'tax_rate_override',
        ]
        read_only_fields = ['line_item_id']


class PurchaseOrderSerializer(serializers.ModelSerializer):
    line_items = POLineItemSerializer(
        source='purchaseorderlineitem_set', many=True, read_only=True
    )

    class Meta:
        model = PurchaseOrder
        fields = [
            'po_id', 'business', 'contact', 'po_number', 'status',
            'created_date', 'requested_date', 'issued_date',
            'received_date', 'cancel_date', 'line_items',
        ]
        read_only_fields = ['po_id', 'po_number', 'created_date']


class BillLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillLineItem
        fields = [
            'line_item_id', 'line_number', 'task', 'price_list_item',
            'qty', 'units', 'description', 'price', 'job',
            'line_item_type', 'taxable_override', 'tax_rate_override',
        ]
        read_only_fields = ['line_item_id']


class BillSerializer(serializers.ModelSerializer):
    line_items = BillLineItemSerializer(
        source='billlineitem_set', many=True, read_only=True
    )

    class Meta:
        model = Bill
        fields = [
            'bill_id', 'purchase_order', 'vendor_invoice_number',
            'business', 'contact', 'bill_number', 'status',
            'created_date', 'received_date', 'cancel_date', 'line_items',
        ]
        read_only_fields = ['bill_id', 'bill_number', 'created_date']
```

```python
# apps/api/purchasing/views.py
from rest_framework import viewsets
from apps.purchasing.models import PurchaseOrder, Bill
from apps.purchasing.services import PurchaseOrderService, BillService
from apps.core.services import ServiceError
from apps.api.mixins import StatusTransitionMixin, LineItemMixin
from .serializers import (
    PurchaseOrderSerializer, POLineItemSerializer,
    BillSerializer, BillLineItemSerializer,
)


class PurchaseOrderViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.all().order_by('-created_date')
    serializer_class = PurchaseOrderSerializer
    lookup_field = 'pk'

    line_item_serializer_class = POLineItemSerializer
    line_item_parent_field = 'purchase_order'

    status_actions = {
        'issue': {
            'service': lambda pk: PurchaseOrderService.update_status(pk, PurchaseOrder.STATUS_ISSUED),
        },
        'cancel': {
            'service': lambda pk, reason=None: PurchaseOrderService.cancel_po(pk),
            'requires_reason': True,
        },
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        business = data.get('business')
        contact = data.get('contact')
        kwargs = {}
        if business:
            kwargs['business'] = business
        if contact:
            kwargs['contact'] = contact
        po = PurchaseOrderService.create_po(**kwargs)
        serializer.instance = po

    def perform_update(self, serializer):
        PurchaseOrderService.update_po(self.get_object().pk, **serializer.validated_data)


class BillViewSet(StatusTransitionMixin, LineItemMixin, viewsets.ModelViewSet):
    queryset = Bill.objects.all().order_by('-created_date')
    serializer_class = BillSerializer
    lookup_field = 'pk'

    line_item_serializer_class = BillLineItemSerializer
    line_item_parent_field = 'bill'

    status_actions = {
        'cancel': {
            'service': lambda pk, reason=None: BillService.update_status(pk, 'cancelled'),
            'requires_reason': True,
        },
    }

    def perform_create(self, serializer):
        data = serializer.validated_data
        po = data.get('purchase_order')
        if po:
            bill = BillService.create_bill_from_po(po.pk if hasattr(po, 'pk') else po)
        else:
            bill = BillService.create_bill(**data)
        serializer.instance = bill
```

Update `apps/api/urls.py`:
```python
from apps.api.purchasing.views import PurchaseOrderViewSet, BillViewSet
router.register(r'purchase-orders', PurchaseOrderViewSet, basename='purchase-order')
router.register(r'bills', BillViewSet, basename='bill')
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_purchasing -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/purchasing/ apps/api/urls.py tests/test_api_purchasing.py
git commit -m "feat: add purchasing API (POs and bills) with line items"
```

---

## Phase 4: Supporting APIs

### Task 12: Inventory API

**Files:**
- Create: `apps/api/inventory/serializers.py`
- Create: `apps/api/inventory/views.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_inventory.py`

**Step 1: Write the failing test**

```python
# tests/test_api_inventory.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.inventory.models import PriceListItem


class PriceListItemAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_price_list_items(self):
        response = self.client.get('/api/price-list-items/')
        self.assertEqual(response.status_code, 200)

    def test_create_price_list_item(self):
        response = self.client.post('/api/price-list-items/', {
            'code': 'API-TEST-001',
            'description': 'API test item',
            'units': 'ea',
            'purchase_price': '10.00',
            'selling_price': '20.00',
        }, format='json')
        self.assertEqual(response.status_code, 201)

    def test_retrieve_price_list_item(self):
        pli = PriceListItem.objects.first()
        if pli:
            response = self.client.get(f'/api/price-list-items/{pli.pk}/')
            self.assertEqual(response.status_code, 200)

    def test_update_price_list_item(self):
        pli = PriceListItem.objects.first()
        if pli:
            response = self.client.patch(f'/api/price-list-items/{pli.pk}/', {
                'selling_price': '25.00',
            }, format='json')
            self.assertEqual(response.status_code, 200)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_inventory -v2`
Expected: FAIL

**Step 3: Implement inventory API**

```python
# apps/api/inventory/serializers.py
from rest_framework import serializers
from apps.inventory.models import PriceListItem


class PriceListItemSerializer(serializers.ModelSerializer):
    qty_earmarked = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    qty_available = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = PriceListItem
        fields = [
            'price_list_item_id', 'code', 'units', 'description',
            'purchase_price', 'selling_price',
            'qty_on_hand', 'qty_sold', 'qty_wasted',
            'qty_earmarked', 'qty_available',
            'is_active', 'is_inventoried', 'line_item_type',
        ]
        read_only_fields = [
            'price_list_item_id', 'qty_on_hand', 'qty_sold', 'qty_wasted',
        ]
```

```python
# apps/api/inventory/views.py
from rest_framework import viewsets
from apps.inventory.models import PriceListItem
from apps.inventory.services import InventoryService
from .serializers import PriceListItemSerializer


class PriceListItemViewSet(viewsets.ModelViewSet):
    queryset = PriceListItem.objects.all().order_by('code')
    serializer_class = PriceListItemSerializer
    lookup_field = 'pk'

    def perform_create(self, serializer):
        item = InventoryService.create_item(**serializer.validated_data)
        serializer.instance = item

    def perform_update(self, serializer):
        InventoryService.update_item(self.get_object().pk, **serializer.validated_data)
```

Update `apps/api/urls.py`:
```python
from apps.api.inventory.views import PriceListItemViewSet
router.register(r'price-list-items', PriceListItemViewSet, basename='price-list-item')
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_inventory -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/inventory/ apps/api/urls.py tests/test_api_inventory.py
git commit -m "feat: add inventory/price list items API"
```

---

### Task 13: Search API

**Files:**
- Create: `apps/api/search/views.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_search.py`

**Step 1: Write the failing test**

```python
# tests/test_api_search.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User


class SearchAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_search_returns_results(self):
        response = self.client.get('/api/search/', {'q': 'test'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('results', response.data)

    def test_search_empty_query(self):
        response = self.client.get('/api/search/')
        self.assertEqual(response.status_code, 400)

    def test_search_with_category_filter(self):
        response = self.client.get('/api/search/', {'q': 'test', 'category': 'jobs'})
        self.assertEqual(response.status_code, 200)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_search -v2`
Expected: FAIL

**Step 3: Implement search API**

```python
# apps/api/search/views.py
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.search.services import SearchService


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def search_view(request):
    query = request.query_params.get('q', '').strip()
    if not query:
        return Response(
            {'detail': 'Query parameter "q" is required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    category = request.query_params.get('category', '').strip()

    categories = SearchService.search_all_entities(query)

    if category:
        filter_id = SearchService.get_category_id_from_string(category)
        if filter_id is not None:
            categories = SearchService.apply_category_filter(categories, filter_id)

    total = SearchService.calculate_total_count(categories)

    results = []
    for cat_id, items in categories.items():
        cat_key = SearchService.get_category_key_from_id(cat_id)
        cat_name = SearchService.get_category_display_name(cat_id)
        for item in items:
            results.append({
                'category': cat_key,
                'category_display': cat_name,
                **item,
            })

    return Response({
        'query': query,
        'total': total,
        'results': results,
    })
```

Update `apps/api/urls.py`:
```python
from apps.api.search.views import search_view

urlpatterns = [
    path('', api_root, name='api-root'),
    path('auth/', include('apps.api.auth.urls')),
    path('search/', search_view, name='api-search'),
] + router.urls
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_search -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/search/ apps/api/urls.py tests/test_api_search.py
git commit -m "feat: add search API endpoint"
```

---

### Task 14: Email API

**Files:**
- Create: `apps/api/email/serializers.py`
- Create: `apps/api/email/views.py`
- Create: `apps/api/email/urls.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_email.py`

**Step 1: Write the failing test**

```python
# tests/test_api_email.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, EmailRecord


class EmailAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_emails(self):
        response = self.client.get('/api/emails/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_email(self):
        email = EmailRecord.objects.first()
        if email:
            response = self.client.get(f'/api/emails/{email.pk}/')
            self.assertIn(response.status_code, [200, 404])

    def test_link_to_job(self):
        email = EmailRecord.objects.first()
        from apps.jobs.models import Job
        job = Job.objects.first()
        if email and job:
            response = self.client.post(f'/api/emails/{email.pk}/link-to-job/', {
                'job_id': job.pk,
            }, format='json')
            self.assertIn(response.status_code, [200, 400])

    def test_unlink_from_job(self):
        email = EmailRecord.objects.filter(job__isnull=False).first()
        if email:
            response = self.client.post(f'/api/emails/{email.pk}/unlink-from-job/')
            self.assertEqual(response.status_code, 200)

    def test_send_stub_returns_501(self):
        response = self.client.post('/api/emails/send/', {}, format='json')
        self.assertEqual(response.status_code, 501)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_email -v2`
Expected: FAIL

**Step 3: Implement email API**

```python
# apps/api/email/serializers.py
from rest_framework import serializers
from apps.core.models import EmailRecord, TempEmail


class TempEmailSerializer(serializers.ModelSerializer):
    class Meta:
        model = TempEmail
        fields = [
            'subject', 'from_email', 'to_email', 'cc_email',
            'date_sent', 'is_read', 'is_starred', 'has_attachments',
        ]


class EmailRecordSerializer(serializers.ModelSerializer):
    temp_email = TempEmailSerializer(source='tempemail', read_only=True)

    class Meta:
        model = EmailRecord
        fields = ['email_record_id', 'message_id', 'job', 'created_at', 'temp_email']
```

```python
# apps/api/email/views.py
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.models import EmailRecord
from apps.core.services import EmailService, ServiceError
from .serializers import EmailRecordSerializer


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def email_list(request):
    emails = EmailRecord.objects.select_related('tempemail').order_by('-created_at')
    # Simple pagination
    from apps.api.pagination import StandardPagination
    paginator = StandardPagination()
    page = paginator.paginate_queryset(emails, request)
    serializer = EmailRecordSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def email_detail(request, pk):
    try:
        email = EmailRecord.objects.select_related('tempemail').get(pk=pk)
    except EmailRecord.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    data = EmailRecordSerializer(email).data
    # Try to get full content
    try:
        content = EmailService.get_email_content(pk)
        data['content'] = content
    except Exception:
        data['content'] = None

    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def link_to_job(request, pk):
    job_id = request.data.get('job_id')
    if not job_id:
        return Response({'job_id': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
    try:
        EmailService.associate_with_job(pk, job_id)
    except (ServiceError, Exception) as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    email = EmailRecord.objects.get(pk=pk)
    return Response(EmailRecordSerializer(email).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def unlink_from_job(request, pk):
    try:
        EmailService.disassociate_from_job(pk)
    except (ServiceError, Exception) as e:
        return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    email = EmailRecord.objects.get(pk=pk)
    return Response(EmailRecordSerializer(email).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_job_from_email(request, pk):
    """Create a job from an email — delegates to JobService."""
    from apps.jobs.services import JobService
    try:
        email = EmailRecord.objects.select_related('tempemail').get(pk=pk)
    except EmailRecord.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    contact_id = request.data.get('contact')
    name = request.data.get('name', '')
    if not contact_id:
        return Response({'contact': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)

    job = JobService.create_job(name=name, contact_id=contact_id)
    EmailService.associate_with_job(pk, job.pk)
    return Response({
        'job_id': job.pk,
        'job_number': job.job_number,
    }, status=status.HTTP_201_CREATED)


def _stub_501(endpoint):
    @api_view(['POST'])
    @permission_classes([IsAuthenticated])
    def view(request, *args, **kwargs):
        return Response(
            {'detail': 'Not yet implemented.', 'endpoint': endpoint},
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )
    return view
```

```python
# apps/api/email/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.email_list, name='email-list'),
    path('<int:pk>/', views.email_detail, name='email-detail'),
    path('<int:pk>/link-to-job/', views.link_to_job, name='email-link-to-job'),
    path('<int:pk>/unlink-from-job/', views.unlink_from_job, name='email-unlink-from-job'),
    path('<int:pk>/create-job/', views.create_job_from_email, name='email-create-job'),
    path('send/', views._stub_501('POST /api/emails/send/'), name='email-send'),
]
```

Update `apps/api/urls.py`:
```python
urlpatterns = [
    path('', api_root, name='api-root'),
    path('auth/', include('apps.api.auth.urls')),
    path('emails/', include('apps.api.email.urls')),
    path('search/', search_view, name='api-search'),
] + router.urls
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_email -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/email/ apps/api/urls.py tests/test_api_email.py
git commit -m "feat: add email API (inbox, detail, link/unlink, create-job, send stub)"
```

---

### Task 15: Templates and Configuration API

**Files:**
- Create: `apps/api/templates_config/serializers.py`
- Create: `apps/api/templates_config/views.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_templates_config.py`

**Step 1: Write the failing test**

```python
# tests/test_api_templates_config.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, Configuration, LineItemType
from apps.estimates.models import WorkOrderTemplate, TaskTemplate


class WorkOrderTemplateAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_wo_templates(self):
        response = self.client.get('/api/work-order-templates/')
        self.assertEqual(response.status_code, 200)

    def test_retrieve_wo_template(self):
        template = WorkOrderTemplate.objects.first()
        if template:
            response = self.client.get(f'/api/work-order-templates/{template.pk}/')
            self.assertEqual(response.status_code, 200)


class TaskTemplateAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_list_task_templates(self):
        response = self.client.get('/api/task-templates/')
        self.assertEqual(response.status_code, 200)

    def test_create_task_template(self):
        response = self.client.post('/api/task-templates/', {
            'template_name': 'API Test Template',
            'description': 'Created via API',
            'units': 'hr',
        }, format='json')
        self.assertEqual(response.status_code, 201)


class ConfigurationAPITest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_get_settings(self):
        response = self.client.get('/api/settings/')
        self.assertEqual(response.status_code, 200)

    def test_list_line_item_types(self):
        response = self.client.get('/api/line-item-types/')
        self.assertEqual(response.status_code, 200)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_templates_config -v2`
Expected: FAIL

**Step 3: Implement templates and configuration API**

```python
# apps/api/templates_config/serializers.py
from rest_framework import serializers
from apps.estimates.models import (
    WorkOrderTemplate, TaskTemplate, TemplateTaskAssociation, TemplateBundle,
)
from apps.core.models import Configuration, LineItemType


class TaskTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskTemplate
        fields = [
            'template_id', 'template_name', 'description',
            'units', 'rate', 'line_item_type', 'is_active',
        ]
        read_only_fields = ['template_id']


class TemplateBundleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TemplateBundle
        fields = [
            'bundle_id', 'name', 'description',
            'line_item_type', 'sort_order',
        ]
        read_only_fields = ['bundle_id']


class TemplateAssociationSerializer(serializers.ModelSerializer):
    task_template = TaskTemplateSerializer(read_only=True)

    class Meta:
        model = TemplateTaskAssociation
        fields = [
            'association_id', 'task_template', 'est_qty',
            'sort_order', 'mapping_strategy', 'bundle',
        ]
        read_only_fields = ['association_id']


class WorkOrderTemplateSerializer(serializers.ModelSerializer):
    associations = TemplateAssociationSerializer(
        source='templatetaskassociation_set', many=True, read_only=True
    )
    bundles = TemplateBundleSerializer(
        source='templatebundle_set', many=True, read_only=True
    )

    class Meta:
        model = WorkOrderTemplate
        fields = [
            'template_id', 'template_name', 'description',
            'is_active', 'associations', 'bundles',
        ]
        read_only_fields = ['template_id']


class ConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Configuration
        fields = ['key', 'value']


class LineItemTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LineItemType
        fields = ['id', 'code', 'name', 'taxable', 'default_description', 'is_active']
        read_only_fields = ['id']
```

```python
# apps/api/templates_config/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.estimates.models import WorkOrderTemplate, TaskTemplate
from apps.estimates.services import WorkOrderTemplateService
from apps.core.models import Configuration, LineItemType
from apps.core.services import ConfigurationService
from .serializers import (
    WorkOrderTemplateSerializer, TaskTemplateSerializer,
    ConfigurationSerializer, LineItemTypeSerializer,
)


class WorkOrderTemplateViewSet(viewsets.ModelViewSet):
    queryset = WorkOrderTemplate.objects.all()
    serializer_class = WorkOrderTemplateSerializer
    lookup_field = 'pk'

    def perform_create(self, serializer):
        template = WorkOrderTemplateService.create_template(**serializer.validated_data)
        serializer.instance = template

    def perform_update(self, serializer):
        WorkOrderTemplateService.update_template(self.get_object().pk, **serializer.validated_data)

    def perform_destroy(self, instance):
        WorkOrderTemplateService.delete_template(instance.pk)


class TaskTemplateViewSet(viewsets.ModelViewSet):
    queryset = TaskTemplate.objects.all()
    serializer_class = TaskTemplateSerializer
    lookup_field = 'pk'

    def perform_create(self, serializer):
        template = WorkOrderTemplateService.create_task_template(**serializer.validated_data)
        serializer.instance = template

    def perform_update(self, serializer):
        WorkOrderTemplateService.update_task_template(
            self.get_object().pk, **serializer.validated_data
        )

    def perform_destroy(self, instance):
        WorkOrderTemplateService.delete_task_template(instance.pk)


class LineItemTypeViewSet(viewsets.ModelViewSet):
    queryset = LineItemType.objects.all()
    serializer_class = LineItemTypeSerializer
    lookup_field = 'pk'

    def perform_create(self, serializer):
        lit = ConfigurationService.create_line_item_type(**serializer.validated_data)
        serializer.instance = lit

    def perform_update(self, serializer):
        ConfigurationService.update_line_item_type(
            self.get_object().pk, **serializer.validated_data
        )


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def settings_view(request):
    if request.method == 'GET':
        configs = Configuration.objects.all()
        data = {c.key: c.value for c in configs}
        return Response(data)

    # PATCH — update settings
    for key, value in request.data.items():
        Configuration.objects.update_or_create(
            key=key, defaults={'value': str(value)}
        )
    configs = Configuration.objects.all()
    data = {c.key: c.value for c in configs}
    return Response(data)
```

Update `apps/api/urls.py`:
```python
from apps.api.templates_config.views import (
    WorkOrderTemplateViewSet, TaskTemplateViewSet,
    LineItemTypeViewSet, settings_view,
)

router.register(r'work-order-templates', WorkOrderTemplateViewSet, basename='work-order-template')
router.register(r'task-templates', TaskTemplateViewSet, basename='task-template')
router.register(r'line-item-types', LineItemTypeViewSet, basename='line-item-type')

urlpatterns = [
    path('', api_root, name='api-root'),
    path('auth/', include('apps.api.auth.urls')),
    path('emails/', include('apps.api.email.urls')),
    path('search/', search_view, name='api-search'),
    path('settings/', settings_view, name='api-settings'),
] + router.urls
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_templates_config -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/templates_config/ apps/api/urls.py tests/test_api_templates_config.py
git commit -m "feat: add templates, configuration, and line item types API"
```

---

## Phase 5: Stubs and Finalization

### Task 16: 501 Stubs (Time Tracking, Expenses)

**Files:**
- Create: `apps/api/time_tracking/urls.py`
- Create: `apps/api/expenses/urls.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_api_stubs.py`

**Step 1: Write the failing test**

```python
# tests/test_api_stubs.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User


class StubEndpointTest(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_time_tracking_stubs(self):
        endpoints = [
            '/api/shifts/clock-in/',
            '/api/shifts/clock-out/',
            '/api/time-tracking/status/',
            '/api/time-tracking/active/',
        ]
        for url in endpoints:
            response = self.client.post(url, {}, format='json')
            self.assertEqual(response.status_code, 501, f'{url} should return 501')

    def test_expense_stubs(self):
        endpoints = [
            '/api/expenses/',
        ]
        for url in endpoints:
            response = self.client.post(url, {}, format='json')
            self.assertEqual(response.status_code, 501, f'{url} should return 501')
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_stubs -v2`
Expected: FAIL

**Step 3: Implement stubs**

Create a helper in `apps/api/urls.py`:

```python
def stub_501(endpoint_name):
    """Create a view that returns 501 for unimplemented endpoints."""
    @api_view(['GET', 'POST', 'PATCH', 'DELETE'])
    @permission_classes([IsAuthenticated])
    def view(request, *args, **kwargs):
        return Response(
            {'detail': 'Not yet implemented.', 'endpoint': endpoint_name},
            status=501,
        )
    return view
```

```python
# apps/api/time_tracking/urls.py
from django.urls import path
from apps.api.urls import stub_501

urlpatterns = [
    path('clock-in/', stub_501('POST /api/shifts/clock-in/'), name='shift-clock-in'),
    path('clock-out/', stub_501('POST /api/shifts/clock-out/'), name='shift-clock-out'),
]
```

```python
# apps/api/expenses/urls.py
from django.urls import path
from apps.api.urls import stub_501

urlpatterns = [
    path('', stub_501('POST /api/expenses/'), name='expense-list'),
]
```

Update `apps/api/urls.py` to include:
```python
path('shifts/', include('apps.api.time_tracking.urls')),
path('expenses/', include('apps.api.expenses.urls')),
path('time-tracking/status/', stub_501('GET /api/time-tracking/status/'), name='time-tracking-status'),
path('time-tracking/active/', stub_501('GET /api/time-tracking/active/'), name='time-tracking-active'),
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_api_stubs -v2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/api/time_tracking/ apps/api/expenses/ apps/api/urls.py tests/test_api_stubs.py
git commit -m "feat: add 501 stubs for time tracking and expenses API"
```

---

### Task 17: Final URL Wiring and Full Test Suite

**Files:**
- Modify: `apps/api/urls.py` (final cleanup)
- Test: `tests/test_api_full_url_tree.py`

**Step 1: Write the failing test**

```python
# tests/test_api_full_url_tree.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User


class FullURLTreeTest(BaseTestCase):
    """Verify every documented endpoint returns a non-404 response."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='dev_user')
        self.client.force_authenticate(user=self.user)

    def test_all_list_endpoints_resolve(self):
        """All list endpoints should return 200 or 501 (not 404)."""
        endpoints = [
            '/api/',
            '/api/auth/me/',
            '/api/jobs/',
            '/api/contacts/',
            '/api/businesses/',
            '/api/payment-terms/',
            '/api/est-worksheets/',
            '/api/estimates/',
            '/api/work-orders/',
            '/api/invoices/',
            '/api/purchase-orders/',
            '/api/bills/',
            '/api/price-list-items/',
            '/api/emails/',
            '/api/work-order-templates/',
            '/api/task-templates/',
            '/api/line-item-types/',
            '/api/settings/',
        ]
        for url in endpoints:
            response = self.client.get(url)
            self.assertNotEqual(
                response.status_code, 404,
                f'{url} returned 404 — endpoint not wired'
            )

    def test_all_stub_endpoints_return_501(self):
        """Stub endpoints should return 501."""
        stubs = [
            ('POST', '/api/auth/refresh/'),
            ('POST', '/api/shifts/clock-in/'),
            ('POST', '/api/shifts/clock-out/'),
            ('GET', '/api/time-tracking/status/'),
            ('GET', '/api/time-tracking/active/'),
            ('POST', '/api/expenses/'),
            ('POST', '/api/emails/send/'),
        ]
        for method, url in stubs:
            if method == 'GET':
                response = self.client.get(url)
            else:
                response = self.client.post(url, {}, format='json')
            self.assertEqual(
                response.status_code, 501,
                f'{method} {url} should return 501, got {response.status_code}'
            )
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_api_full_url_tree -v2`
Expected: FAIL (some endpoints may not be wired yet)

**Step 3: Fix any remaining URL wiring issues**

Review and finalize `apps/api/urls.py` to ensure all endpoints are properly wired. The complete file should have all router registrations and include() calls from Tasks 1-16.

**Step 4: Run full API test suite**

Run: `python manage.py test tests.test_api_foundation tests.test_api_auth tests.test_api_jobs tests.test_api_contacts tests.test_api_estimates tests.test_api_worksheets tests.test_api_work_orders tests.test_api_invoicing tests.test_api_purchasing tests.test_api_inventory tests.test_api_search tests.test_api_email tests.test_api_templates_config tests.test_api_stubs tests.test_api_full_url_tree -v2`
Expected: ALL PASS

**Step 5: Run existing tests to verify no regressions**

Run: `python manage.py test -v2`
Expected: ALL PASS (existing tests unaffected)

**Step 6: Commit**

```bash
git add apps/api/ tests/test_api_full_url_tree.py
git commit -m "feat: finalize API URL tree and add full endpoint verification tests"
```

---

## Summary

| Phase | Tasks | What's Built |
|---|---|---|
| 1: Foundation | 1-4 | DRF install, app skeleton, 3 mixins, auth |
| 2: Core Domain | 5-9 | Jobs, contacts, estimates, worksheets, work orders |
| 3: Financial | 10-11 | Invoices, POs, bills |
| 4: Supporting | 12-15 | Inventory, search, email, templates, config |
| 5: Finalization | 16-17 | 501 stubs, full URL tree verification |

**Total:** 17 tasks, each independently committable and testable.

**Not in scope (future tasks):**
- Permission atoms (CanManageJobs, etc.) — separate task per permissions design
- Rich job detail response with nested serializers — progressive enrichment
- JWT and OAuth auth backends
- Audit trail / history feed
