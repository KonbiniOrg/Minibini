# Expenses + Job P&L Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the expense submission/approval system, push approved expenses to QBO, and add a job profit & loss view aggregating all revenue and costs.

**Architecture:** New `Expense` model in a new `apps/expenses/` Django app. Approval workflow uses `can_approve_expenses` permission atom with configurable auto-approval threshold. Approved expenses push to QBO as either Purchases (company-paid) or Bills to employee (reimbursements). Job P&L is a read-only aggregation service + API endpoint, with no QBO dependency except for knowing invoice payment status.

**Tech Stack:** Django 5.2+, DRF, python-quickbooks, Svelte 5

**Design spec:** `docs/designs/2026-03-28-quickbooks-integration.md` (see "Expense Flow" and "Job Profit & Loss")

**Prerequisites:**
- QBO Foundation plan
- AccountingCategory rename plan
- Invoice push plan (for payment status on the P&L revenue side)
- Bill push plan (for bill costs on the P&L)

---

## File Structure

```
apps/expenses/                         # NEW Django app
├── __init__.py
├── apps.py
├── models.py                          # Expense model
├── services.py                        # ExpenseService (submit, approve, reject)
├── admin.py
└── migrations/
    └── 0001_initial.py

apps/qbo/
└── services.py                        # Add QBOExpenseSyncService

apps/api/expenses/                     # NEW (stub exists, needs implementation)
├── __init__.py
├── serializers.py
├── views.py                           # ExpenseViewSet with approve/reject actions
└── urls.py

apps/jobs/
└── services.py                        # Add JobProfitLossService

apps/api/jobs/
└── views.py                           # Add profit-loss action on JobViewSet

frontend/src/
├── routes/expenses/
│   ├── ExpenseListPage.svelte         # List with status filters
│   └── ExpenseFormPage.svelte         # Submit new expense
├── components/expenses/
│   ├── ExpenseList.svelte
│   └── ExpenseForm.svelte
└── components/jobs/
    └── JobProfitLoss.svelte           # P&L display on job detail

tests/
├── test_expense_model.py
├── test_expense_service.py
├── test_expense_api.py
├── test_qbo_expense_push.py
└── test_job_profit_loss.py
```

---

### Task 1: Create the Expense App and Model

**Files:**
- Create: `apps/expenses/` (full app)
- Modify: `minibini/settings.py` (INSTALLED_APPS)
- Test: `tests/test_expense_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_expense_model.py
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.expenses.models import Expense
from apps.core.models import AccountingCategory, Configuration
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business

User = get_user_model()


class ExpenseModelTest(TestCase):
    """Test the Expense model."""

    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        self.user = User.objects.create_user(username='worker', password='testpass')
        self.category = AccountingCategory.objects.create(
            code='SUP', name='Shop Supplies', taxable=True,
        )
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(contact=self.contact)

    def test_create_expense(self):
        exp = Expense.objects.create(
            submitted_by=self.user,
            amount=Decimal('47.50'),
            description='Bolts from hardware store',
            accounting_category=self.category,
            payment_method='company_card',
        )
        self.assertEqual(exp.status, Expense.STATUS_SUBMITTED)
        self.assertIsNotNone(exp.submitted_at)

    def test_expense_linked_to_job(self):
        exp = Expense.objects.create(
            submitted_by=self.user,
            amount=Decimal('47.50'),
            description='Bolts for job',
            accounting_category=self.category,
            payment_method='company_card',
            job=self.job,
        )
        self.assertEqual(exp.job, self.job)

    def test_expense_without_job(self):
        exp = Expense.objects.create(
            submitted_by=self.user,
            amount=Decimal('15.00'),
            description='Office supplies',
            accounting_category=self.category,
            payment_method='petty_cash',
        )
        self.assertIsNone(exp.job)

    def test_payment_method_choices(self):
        """All payment methods are valid."""
        for method, _ in Expense.PAYMENT_METHOD_CHOICES:
            exp = Expense.objects.create(
                submitted_by=self.user,
                amount=Decimal('10.00'),
                description=f'Test {method}',
                accounting_category=self.category,
                payment_method=method,
            )
            self.assertEqual(exp.payment_method, method)

    def test_status_choices(self):
        exp = Expense.objects.create(
            submitted_by=self.user,
            amount=Decimal('10.00'),
            description='Test',
            accounting_category=self.category,
            payment_method='company_card',
        )
        self.assertEqual(exp.status, 'submitted')
        # Verify all status values are valid
        for status, _ in Expense.STATUS_CHOICES:
            exp.status = status
            exp.save()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_expense_model -v2
```

Expected: ImportError — module doesn't exist.

- [ ] **Step 3: Create the app and model**

Create app structure:

```python
# apps/expenses/__init__.py
# (empty)

# apps/expenses/apps.py
from django.apps import AppConfig

class ExpensesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.expenses'
    verbose_name = 'Expenses'
```

```python
# apps/expenses/models.py
from django.db import models
from django.utils import timezone


class Expense(models.Model):
    """Employee-submitted expense, optionally linked to a job."""

    PAYMENT_METHOD_CHOICES = [
        ('company_card', 'Company Credit Card'),
        ('personal', 'Personal (Reimbursement)'),
        ('petty_cash', 'Petty Cash'),
        ('check', 'Check'),
    ]

    STATUS_SUBMITTED = 'submitted'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_SYNCED = 'synced'
    STATUS_REIMBURSED = 'reimbursed'

    STATUS_CHOICES = [
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_SYNCED, 'Synced to QBO'),
        (STATUS_REIMBURSED, 'Reimbursed'),
    ]

    submitted_by = models.ForeignKey('core.User', on_delete=models.PROTECT, related_name='submitted_expenses')
    job = models.ForeignKey('jobs.Job', null=True, blank=True, on_delete=models.SET_NULL)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField()
    accounting_category = models.ForeignKey('core.AccountingCategory', on_delete=models.PROTECT)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    receipt = models.FileField(upload_to='receipts/', null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SUBMITTED)
    approved_by = models.ForeignKey(
        'core.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='approved_expenses',
    )
    submitted_at = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(null=True, blank=True)
    qbo_id = models.CharField(max_length=50, blank=True, default='')

    class Meta:
        db_table = 'expenses'
        ordering = ['-submitted_at']

    def __str__(self):
        return f"Expense {self.pk}: ${self.amount} ({self.status})"

    @property
    def needs_reimbursement(self):
        return self.payment_method == 'personal'
```

```python
# apps/expenses/admin.py
from django.contrib import admin
from .models import Expense

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ['pk', 'submitted_by', 'amount', 'accounting_category', 'payment_method', 'status', 'submitted_at']
    list_filter = ['status', 'payment_method']
    ordering = ['-submitted_at']
```

- [ ] **Step 4: Add to INSTALLED_APPS**

In `minibini/settings.py`, add `'apps.expenses'` to INSTALLED_APPS.

- [ ] **Step 5: Generate migration**

```bash
python manage.py makemigrations expenses
```

- [ ] **Step 6: Run tests**

```bash
python manage.py test tests.test_expense_model -v2
```

- [ ] **Step 7: Commit**

```bash
git add apps/expenses/ minibini/settings.py tests/test_expense_model.py
git commit -m "feat: create expenses app with Expense model"
```

---

### Task 2: Expense Service — Submit, Approve, Reject

**Files:**
- Create: `apps/expenses/services.py`
- Test: `tests/test_expense_service.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_expense_service.py
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.expenses.models import Expense
from apps.expenses.services import ExpenseService
from apps.core.models import AccountingCategory, Configuration

User = get_user_model()


class ExpenseSubmissionTest(TestCase):
    """Test expense submission with auto-approval."""

    def setUp(self):
        Configuration.objects.create(key='expense_auto_approval_threshold', value='50.00')
        self.user = User.objects.create_user(username='worker', password='testpass')
        self.category = AccountingCategory.objects.create(code='SUP', name='Supplies')

    def test_submit_under_threshold_auto_approves(self):
        exp = ExpenseService.submit_expense(
            submitted_by=self.user,
            amount=Decimal('25.00'),
            description='Small purchase',
            accounting_category=self.category,
            payment_method='company_card',
        )
        self.assertEqual(exp.status, Expense.STATUS_APPROVED)
        self.assertIsNotNone(exp.approved_at)

    def test_submit_over_threshold_stays_submitted(self):
        exp = ExpenseService.submit_expense(
            submitted_by=self.user,
            amount=Decimal('100.00'),
            description='Large purchase',
            accounting_category=self.category,
            payment_method='company_card',
        )
        self.assertEqual(exp.status, Expense.STATUS_SUBMITTED)
        self.assertIsNone(exp.approved_at)

    def test_submit_without_threshold_config_stays_submitted(self):
        """If no threshold configured, all expenses require approval."""
        Configuration.objects.filter(key='expense_auto_approval_threshold').delete()
        exp = ExpenseService.submit_expense(
            submitted_by=self.user,
            amount=Decimal('5.00'),
            description='Tiny purchase',
            accounting_category=self.category,
            payment_method='petty_cash',
        )
        self.assertEqual(exp.status, Expense.STATUS_SUBMITTED)


class ExpenseApprovalTest(TestCase):
    """Test expense approval and rejection."""

    def setUp(self):
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.manager = User.objects.create_user(username='manager', password='testpass')
        self.category = AccountingCategory.objects.create(code='SUP', name='Supplies')

    def _create_submitted_expense(self, amount='100.00'):
        return Expense.objects.create(
            submitted_by=self.worker,
            amount=Decimal(amount),
            description='Test expense',
            accounting_category=self.category,
            payment_method='company_card',
        )

    def test_approve_expense(self):
        exp = self._create_submitted_expense()
        result = ExpenseService.approve_expense(exp.pk, approved_by=self.manager)
        self.assertEqual(result.status, Expense.STATUS_APPROVED)
        self.assertEqual(result.approved_by, self.manager)
        self.assertIsNotNone(result.approved_at)

    def test_reject_expense(self):
        exp = self._create_submitted_expense()
        result = ExpenseService.reject_expense(exp.pk)
        self.assertEqual(result.status, Expense.STATUS_REJECTED)

    def test_cannot_approve_non_submitted(self):
        exp = self._create_submitted_expense()
        exp.status = Expense.STATUS_APPROVED
        exp.save()
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            ExpenseService.approve_expense(exp.pk, approved_by=self.manager)

    def test_cannot_reject_non_submitted(self):
        exp = self._create_submitted_expense()
        exp.status = Expense.STATUS_APPROVED
        exp.save()
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            ExpenseService.reject_expense(exp.pk)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_expense_service -v2
```

- [ ] **Step 3: Implement ExpenseService**

```python
# apps/expenses/services.py
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.expenses.models import Expense
from apps.core.models import Configuration
from apps.core.services import NotFoundError


class ExpenseService:
    """Service for expense submission and approval workflow."""

    @staticmethod
    def submit_expense(submitted_by, amount, description, accounting_category,
                       payment_method, job=None, receipt=None):
        """
        Submit a new expense. Auto-approves if under threshold.
        """
        expense = Expense.objects.create(
            submitted_by=submitted_by,
            amount=amount,
            description=description,
            accounting_category=accounting_category,
            payment_method=payment_method,
            job=job,
            receipt=receipt,
        )

        # Auto-approve if under threshold
        try:
            config = Configuration.objects.get(key='expense_auto_approval_threshold')
            threshold = Decimal(config.value)
            if amount <= threshold:
                expense.status = Expense.STATUS_APPROVED
                expense.approved_at = timezone.now()
                expense.save(update_fields=['status', 'approved_at'])
        except Configuration.DoesNotExist:
            pass  # No threshold = all require manual approval

        return expense

    @staticmethod
    def approve_expense(expense_id, approved_by):
        """Approve a submitted expense."""
        try:
            expense = Expense.objects.get(pk=expense_id)
        except Expense.DoesNotExist:
            raise NotFoundError(f'Expense {expense_id} not found')

        if expense.status != Expense.STATUS_SUBMITTED:
            raise ValidationError('Only submitted expenses can be approved.')

        expense.status = Expense.STATUS_APPROVED
        expense.approved_by = approved_by
        expense.approved_at = timezone.now()
        expense.save(update_fields=['status', 'approved_by', 'approved_at'])
        return expense

    @staticmethod
    def reject_expense(expense_id):
        """Reject a submitted expense."""
        try:
            expense = Expense.objects.get(pk=expense_id)
        except Expense.DoesNotExist:
            raise NotFoundError(f'Expense {expense_id} not found')

        if expense.status != Expense.STATUS_SUBMITTED:
            raise ValidationError('Only submitted expenses can be rejected.')

        expense.status = Expense.STATUS_REJECTED
        expense.save(update_fields=['status'])
        return expense
```

- [ ] **Step 4: Run tests**

```bash
python manage.py test tests.test_expense_service -v2
```

- [ ] **Step 5: Commit**

```bash
git add apps/expenses/services.py tests/test_expense_service.py
git commit -m "feat: add ExpenseService with submit, approve, reject workflow"
```

---

### Task 3: Expense API — ViewSet with Approve/Reject Actions

**Files:**
- Create: `apps/api/expenses/serializers.py`
- Modify: `apps/api/expenses/views.py` (stub exists)
- Modify: `apps/api/expenses/urls.py` (stub exists)
- Modify: `apps/api/urls.py`
- Test: `tests/test_expense_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_expense_api.py
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from apps.expenses.models import Expense
from apps.core.models import AccountingCategory, Configuration
from apps.jobs.models import Job
from apps.contacts.models import Contact, Business

User = get_user_model()


class ExpenseAPITest(TestCase):
    """Test expense API endpoints."""

    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')

        self.client = Client()
        self.worker = User.objects.create_user(username='worker', password='testpass')
        self.manager = User.objects.create_user(username='manager', password='testpass')
        perm = Permission.objects.get(codename='can_approve_expenses', content_type__app_label='core')
        self.manager.user_permissions.add(perm)
        self.manager = User.objects.get(pk=self.manager.pk)

        self.category = AccountingCategory.objects.create(code='SUP', name='Supplies')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='User',
            email='test@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

    def test_worker_can_create_expense(self):
        """Any authenticated user can submit an expense."""
        self.client.login(username='worker', password='testpass')
        response = self.client.post('/api/expenses/', data={
            'amount': '47.50',
            'description': 'Hardware store purchase',
            'accounting_category': self.category.pk,
            'payment_method': 'company_card',
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Expense.objects.count(), 1)

    def test_worker_can_list_own_expenses(self):
        """Worker sees their own expenses."""
        Expense.objects.create(
            submitted_by=self.worker, amount=Decimal('10.00'),
            description='Test', accounting_category=self.category,
            payment_method='petty_cash',
        )
        self.client.login(username='worker', password='testpass')
        response = self.client.get('/api/expenses/')
        self.assertEqual(response.status_code, 200)

    def test_approve_requires_permission(self):
        """Approving requires can_approve_expenses."""
        exp = Expense.objects.create(
            submitted_by=self.worker, amount=Decimal('100.00'),
            description='Test', accounting_category=self.category,
            payment_method='company_card',
        )
        self.client.login(username='worker', password='testpass')
        response = self.client.post(f'/api/expenses/{exp.pk}/approve/')
        self.assertEqual(response.status_code, 403)

    def test_manager_can_approve(self):
        """Manager with can_approve_expenses can approve."""
        exp = Expense.objects.create(
            submitted_by=self.worker, amount=Decimal('100.00'),
            description='Test', accounting_category=self.category,
            payment_method='company_card',
        )
        self.client.login(username='manager', password='testpass')
        response = self.client.post(f'/api/expenses/{exp.pk}/approve/')
        self.assertEqual(response.status_code, 200)
        exp.refresh_from_db()
        self.assertEqual(exp.status, Expense.STATUS_APPROVED)

    def test_manager_can_reject(self):
        exp = Expense.objects.create(
            submitted_by=self.worker, amount=Decimal('100.00'),
            description='Test', accounting_category=self.category,
            payment_method='company_card',
        )
        self.client.login(username='manager', password='testpass')
        response = self.client.post(f'/api/expenses/{exp.pk}/reject/')
        self.assertEqual(response.status_code, 200)
        exp.refresh_from_db()
        self.assertEqual(exp.status, Expense.STATUS_REJECTED)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_expense_api -v2
```

- [ ] **Step 3: Implement serializers, viewset, and URLs**

```python
# apps/api/expenses/serializers.py
from rest_framework import serializers
from apps.expenses.models import Expense


class ExpenseSerializer(serializers.ModelSerializer):
    submitted_by_name = serializers.CharField(source='submitted_by.username', read_only=True)

    class Meta:
        model = Expense
        fields = [
            'id', 'submitted_by', 'submitted_by_name', 'job', 'amount',
            'description', 'accounting_category', 'payment_method',
            'receipt', 'status', 'approved_by', 'submitted_at',
            'approved_at', 'qbo_id',
        ]
        read_only_fields = [
            'id', 'submitted_by', 'status', 'approved_by',
            'submitted_at', 'approved_at', 'qbo_id',
        ]
```

```python
# apps/api/expenses/views.py
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.api.permissions import CanApproveExpenses
from apps.expenses.models import Expense
from apps.expenses.services import ExpenseService
from apps.api.expenses.serializers import ExpenseSerializer


class ExpenseViewSet(viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer

    def get_queryset(self):
        qs = Expense.objects.all().order_by('-submitted_at')
        # Workers see all expenses (managers need full view for approval)
        return qs

    def get_permissions(self):
        if self.action in ('approve', 'reject'):
            return [IsAuthenticated(), CanApproveExpenses()]
        return [IsAuthenticated()]

    def perform_create(self, serializer):
        data = serializer.validated_data
        expense = ExpenseService.submit_expense(
            submitted_by=self.request.user,
            **data,
        )
        serializer.instance = expense

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a submitted expense. Attempts QBO push if connected."""
        try:
            expense = ExpenseService.approve_expense(pk, approved_by=request.user)
            # Attempt QBO push (non-blocking — log failures, don't reject the approval)
            try:
                from apps.qbo.services import QBOExpenseSyncService, QBOService
                if QBOService.get_active_connection():
                    QBOExpenseSyncService.push_expense(expense)
            except Exception:
                pass  # QBO push failure doesn't block approval; logged in QBOSyncLog
            return Response(ExpenseSerializer(expense).data)
        except Exception as e:
            return Response({'error': str(e)}, status=400)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject a submitted expense."""
        try:
            expense = ExpenseService.reject_expense(pk)
            return Response(ExpenseSerializer(expense).data)
        except Exception as e:
            return Response({'error': str(e)}, status=400)
```

```python
# apps/api/expenses/urls.py
from rest_framework.routers import DefaultRouter
from .views import ExpenseViewSet

router = DefaultRouter()
router.register(r'', ExpenseViewSet, basename='expense')
urlpatterns = router.urls
```

In `apps/api/urls.py`, update the expenses include (stub already exists):
```python
path('expenses/', include('apps.api.expenses.urls')),
```

- [ ] **Step 4: Run tests**

```bash
python manage.py test tests.test_expense_api -v2
```

- [ ] **Step 5: Commit**

```bash
git add apps/api/expenses/ tests/test_expense_api.py apps/api/urls.py
git commit -m "feat: add Expense API with approve/reject actions"
```

---

### Task 4: QBO Expense Push Service

**Files:**
- Modify: `apps/qbo/services.py`
- Test: `tests/test_qbo_expense_push.py`

Approved expenses push to QBO as either a Purchase (company-paid) or a Bill to the employee (reimbursement).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_qbo_expense_push.py
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.expenses.models import Expense
from apps.core.models import AccountingCategory
from apps.qbo.services import QBOExpenseSyncService
from apps.qbo.models import QBOSyncLog

User = get_user_model()


class QBOExpensePushTest(TestCase):
    """Test pushing approved expenses to QBO."""

    def setUp(self):
        self.user = User.objects.create_user(username='worker', password='testpass')
        self.category = AccountingCategory.objects.create(
            code='SUP', name='Supplies', qbo_expense_account_id='500',
        )

    def _create_approved_expense(self, payment_method='company_card'):
        return Expense.objects.create(
            submitted_by=self.user,
            amount=Decimal('47.50'),
            description='Hardware store bolts',
            accounting_category=self.category,
            payment_method=payment_method,
            status=Expense.STATUS_APPROVED,
        )

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_company_expense(self, mock_get_client):
        """Company-paid expense pushes as QBO Purchase."""
        exp = self._create_approved_expense(payment_method='company_card')

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_purchase = MagicMock()
        mock_purchase.Id = '333'
        mock_purchase.save = MagicMock(return_value=mock_purchase)

        with patch('apps.qbo.services.QBOExpenseSyncService._build_purchase',
                   return_value=mock_purchase):
            QBOExpenseSyncService.push_expense(exp)

        exp.refresh_from_db()
        self.assertEqual(exp.qbo_id, '333')
        self.assertEqual(exp.status, Expense.STATUS_SYNCED)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_reimbursement_expense(self, mock_get_client):
        """Personal expense pushes as QBO Bill (reimbursement)."""
        exp = self._create_approved_expense(payment_method='personal')

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_bill = MagicMock()
        mock_bill.Id = '444'
        mock_bill.save = MagicMock(return_value=mock_bill)

        with patch('apps.qbo.services.QBOExpenseSyncService._build_reimbursement_bill',
                   return_value=mock_bill):
            QBOExpenseSyncService.push_expense(exp)

        exp.refresh_from_db()
        self.assertEqual(exp.qbo_id, '444')

    def test_push_requires_approved_status(self):
        """Cannot push a non-approved expense."""
        exp = Expense.objects.create(
            submitted_by=self.user, amount=Decimal('10.00'),
            description='Test', accounting_category=self.category,
            payment_method='company_card',
            status=Expense.STATUS_SUBMITTED,
        )
        with self.assertRaises(ValueError):
            QBOExpenseSyncService.push_expense(exp)

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_logs_success(self, mock_get_client):
        """push_expense logs success."""
        exp = self._create_approved_expense()

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_purchase = MagicMock()
        mock_purchase.Id = '333'
        mock_purchase.save = MagicMock(return_value=mock_purchase)

        with patch('apps.qbo.services.QBOExpenseSyncService._build_purchase',
                   return_value=mock_purchase):
            QBOExpenseSyncService.push_expense(exp)

        log = QBOSyncLog.objects.get(entity_type='expense')
        self.assertEqual(log.status, 'success')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_expense_push -v2
```

- [ ] **Step 3: Implement QBOExpenseSyncService**

Add to `apps/qbo/services.py`:

```python
class QBOExpenseSyncService:
    """Pushes approved expenses to QBO.

    NOTE: _build_purchase needs AccountRef for the payment source account
    (CC account, bank account, petty cash). This requires a mapping from
    payment_method to QBO account IDs — likely a Configuration key per method.
    Deferred to sandbox testing to determine exact QBO API requirements.

    NOTE: _build_reimbursement_bill needs VendorRef for the employee.
    This requires either mapping employees to QBO Vendors or using a generic
    "Employee Reimbursements" vendor. Deferred to sandbox testing.
    """

    @staticmethod
    def push_expense(expense):
        """
        Push an approved expense to QBO.
        Company-paid → QBO Purchase (Expense entity)
        Personal → QBO Bill to employee (reimbursement)
        """
        if expense.status != Expense.STATUS_APPROVED:
            raise ValueError('Only approved expenses can be pushed to QBO')

        if expense.qbo_id:
            return expense.qbo_id

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        try:
            if expense.needs_reimbursement:
                qbo_entity = QBOExpenseSyncService._build_reimbursement_bill(expense)
                qbo_entity_type = 'Bill'
            else:
                qbo_entity = QBOExpenseSyncService._build_purchase(expense)
                qbo_entity_type = 'Purchase'

            qbo_entity.save(qb=client)
            qbo_id = str(qbo_entity.Id)

            expense.qbo_id = qbo_id
            expense.status = Expense.STATUS_SYNCED
            expense.save(update_fields=['qbo_id', 'status'])

            QBOService.log_sync(
                entity_type='expense',
                entity_id=expense.pk,
                qbo_entity_type=qbo_entity_type,
                qbo_entity_id=qbo_id,
                action='create',
                status='success',
            )
            return qbo_id

        except Exception as e:
            QBOService.log_sync(
                entity_type='expense',
                entity_id=expense.pk,
                qbo_entity_type='',
                qbo_entity_id='',
                action='create',
                status='failed',
                error_message=str(e),
            )
            raise

    @staticmethod
    def _build_purchase(expense):
        """Build a QBO Purchase (Expense) for company-paid expenses."""
        from quickbooks.objects.purchase import Purchase
        from quickbooks.objects.detailline import AccountBasedExpenseLine, AccountBasedExpenseLineDetail
        from quickbooks.objects.base import Ref

        purchase = Purchase()
        purchase.PaymentType = 'Cash'  # Generic; actual payment method is tracking info

        line = AccountBasedExpenseLine()
        line.Amount = float(expense.amount)
        line.Description = expense.description

        detail = AccountBasedExpenseLineDetail()
        if expense.accounting_category and expense.accounting_category.qbo_expense_account_id:
            detail.AccountRef = Ref()
            detail.AccountRef.value = expense.accounting_category.qbo_expense_account_id

        line.AccountBasedExpenseLineDetail = detail
        purchase.Line = [line]

        return purchase

    @staticmethod
    def _build_reimbursement_bill(expense):
        """Build a QBO Bill for employee reimbursement expenses."""
        from quickbooks.objects.bill import Bill as QBOBill
        from quickbooks.objects.detailline import AccountBasedExpenseLine, AccountBasedExpenseLineDetail
        from quickbooks.objects.base import Ref

        bill = QBOBill()
        # Employee as vendor — this requires the employee to exist as a QBO Vendor.
        # For now, use a generic "Employee Reimbursements" vendor.
        # TODO: Map employees to QBO vendors for proper reimbursement tracking.

        line = AccountBasedExpenseLine()
        line.Amount = float(expense.amount)
        line.Description = f"Reimbursement: {expense.description} (submitted by {expense.submitted_by.username})"

        detail = AccountBasedExpenseLineDetail()
        if expense.accounting_category and expense.accounting_category.qbo_expense_account_id:
            detail.AccountRef = Ref()
            detail.AccountRef.value = expense.accounting_category.qbo_expense_account_id

        line.AccountBasedExpenseLineDetail = detail
        bill.Line = [line]

        return bill
```

- [ ] **Step 4: Run tests**

```bash
python manage.py test tests.test_qbo_expense_push -v2
```

- [ ] **Step 5: Commit**

```bash
git add apps/qbo/services.py tests/test_qbo_expense_push.py
git commit -m "feat: add QBOExpenseSyncService for pushing expenses to QBO"
```

---

### Task 5: Job Profit & Loss Service

**Files:**
- Modify: `apps/jobs/services.py`
- Modify: `apps/api/jobs/views.py`
- Test: `tests/test_job_profit_loss.py`

Aggregates all revenue and costs for a job. Calculated entirely from Minibini data except invoice payment status (from QBO polling).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_job_profit_loss.py
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from apps.jobs.models import Job, WorkOrder, Task, Blep
from apps.jobs.services import JobProfitLossService
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.expenses.models import Expense
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory, Configuration

User = get_user_model()


class JobProfitLossTest(TestCase):
    """Test job P&L aggregation."""

    def setUp(self):
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        Configuration.objects.create(key='job_counter', value='0')
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        Configuration.objects.create(key='invoice_counter', value='0')
        Configuration.objects.create(key='po_number_sequence', value='PO-{year}-{counter:04d}')
        Configuration.objects.create(key='po_counter', value='0')

        self.user = User.objects.create_user(username='worker', password='testpass')
        self.category = AccountingCategory.objects.create(code='SVC', name='Service')
        self.contact = Contact.objects.create(
            first_name='John', last_name='Doe',
            email='john@example.com', mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Acme', default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(contact=self.contact)

    def test_empty_job_has_zero_pl(self):
        pl = JobProfitLossService.calculate(self.job)
        self.assertEqual(pl['revenue']['invoiced'], Decimal('0'))
        self.assertEqual(pl['costs']['materials'], Decimal('0'))
        self.assertEqual(pl['costs']['expenses'], Decimal('0'))
        self.assertEqual(pl['profit'], Decimal('0'))

    def test_revenue_from_invoice_line_items(self):
        inv = Invoice.objects.create(job=self.job)
        InvoiceLineItem.objects.create(
            invoice=inv, qty=2, price=Decimal('500.00'),
            description='Work', accounting_category=self.category,
        )
        pl = JobProfitLossService.calculate(self.job)
        self.assertEqual(pl['revenue']['invoiced'], Decimal('1000.00'))

    def test_revenue_shows_payment_status(self):
        inv = Invoice.objects.create(job=self.job)
        inv.qbo_amount_paid = Decimal('600.00')
        inv.save()
        InvoiceLineItem.objects.create(
            invoice=inv, qty=1, price=Decimal('1000.00'),
            description='Work', accounting_category=self.category,
        )
        pl = JobProfitLossService.calculate(self.job)
        self.assertEqual(pl['revenue']['invoiced'], Decimal('1000.00'))
        self.assertEqual(pl['revenue']['paid'], Decimal('600.00'))

    def test_material_costs_from_po_line_items(self):
        po = PurchaseOrder.objects.create(business=self.business)
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, job=self.job,
            qty=10, price=Decimal('25.00'),
            description='Steel bolts',
        )
        pl = JobProfitLossService.calculate(self.job)
        self.assertEqual(pl['costs']['materials'], Decimal('250.00'))

    def test_expense_costs(self):
        Expense.objects.create(
            submitted_by=self.user, job=self.job,
            amount=Decimal('47.50'), description='Hardware store',
            accounting_category=self.category,
            payment_method='company_card',
            status=Expense.STATUS_APPROVED,
        )
        pl = JobProfitLossService.calculate(self.job)
        self.assertEqual(pl['costs']['expenses'], Decimal('47.50'))

    def test_labor_costs_from_bleps(self):
        """Bleps contribute to labor costs. Rate comes from Configuration or default."""
        Configuration.objects.create(key='default_hourly_rate', value='75.00')
        wo = WorkOrder.objects.create(job=self.job)
        task = Task.objects.create(work_order=wo, name='CNC work')
        from django.utils import timezone
        import datetime
        start = timezone.now() - datetime.timedelta(hours=2)
        end = timezone.now()
        Blep.objects.create(user=self.user, task=task, start_time=start, end_time=end)

        pl = JobProfitLossService.calculate(self.job)
        # 2 hours × $75/hr = $150
        self.assertAlmostEqual(float(pl['costs']['labor']), 150.00, places=0)

    def test_profit_calculation(self):
        """Profit = revenue - total costs."""
        inv = Invoice.objects.create(job=self.job)
        InvoiceLineItem.objects.create(
            invoice=inv, qty=1, price=Decimal('1000.00'),
            accounting_category=self.category,
        )
        Expense.objects.create(
            submitted_by=self.user, job=self.job,
            amount=Decimal('200.00'), description='Materials',
            accounting_category=self.category,
            payment_method='company_card',
            status=Expense.STATUS_APPROVED,
        )
        pl = JobProfitLossService.calculate(self.job)
        self.assertEqual(pl['profit'], Decimal('800.00'))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_job_profit_loss -v2
```

- [ ] **Step 3: Implement JobProfitLossService**

Add to `apps/jobs/services.py`:

```python
class JobProfitLossService:
    """Aggregates revenue and costs for a job's profit & loss view."""

    @staticmethod
    def calculate(job):
        """
        Calculate P&L for a job.
        Returns dict with revenue, costs (by category), and profit.
        """
        from decimal import Decimal
        from apps.invoicing.models import Invoice, InvoiceLineItem
        from apps.purchasing.models import PurchaseOrderLineItem
        from apps.expenses.models import Expense
        from apps.jobs.models import Blep, WorkOrder

        # Revenue: sum of invoice line items (exclude cancelled/superseded)
        invoices = Invoice.objects.filter(job=job).exclude(
            status__in=['cancelled', 'superseded']
        )
        invoiced = InvoiceLineItem.objects.filter(
            invoice__in=invoices
        ).aggregate(
            total=models.Sum(models.F('qty') * models.F('price'))
        )['total'] or Decimal('0')

        # Payment status from QBO polling
        paid = invoices.aggregate(
            total=models.Sum('qbo_amount_paid')
        )['total'] or Decimal('0')

        # Material costs: PO line items linked to this job
        materials = PurchaseOrderLineItem.objects.filter(
            job=job
        ).aggregate(
            total=models.Sum(models.F('qty') * models.F('price'))
        )['total'] or Decimal('0')

        # Subcontractor costs: bill line items where the bill's PO is linked to this job
        from apps.purchasing.models import BillLineItem
        subcontractor = BillLineItem.objects.filter(
            bill__purchase_order__purchaseorderlineitem__job=job
        ).distinct().aggregate(
            total=models.Sum(models.F('qty') * models.F('price'))
        )['total'] or Decimal('0')

        # Expense costs: approved expenses linked to this job
        expenses = Expense.objects.filter(
            job=job,
            status__in=[
                Expense.STATUS_APPROVED, Expense.STATUS_SYNCED, Expense.STATUS_REIMBURSED,
            ],
        ).aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0')

        # Labor costs: bleps on tasks in work orders for this job
        labor = Decimal('0')
        try:
            from apps.core.models import Configuration
            rate_config = Configuration.objects.get(key='default_hourly_rate')
            hourly_rate = Decimal(rate_config.value)
        except Configuration.DoesNotExist:
            hourly_rate = Decimal('0')

        if hourly_rate > 0:
            work_orders = WorkOrder.objects.filter(job=job)
            bleps = Blep.objects.filter(
                task__work_order__in=work_orders,
                start_time__isnull=False,
                end_time__isnull=False,
            )
            for blep in bleps:
                hours = Decimal(str(blep.elapsed.total_seconds())) / Decimal('3600')
                labor += hours * hourly_rate
            labor = labor.quantize(Decimal('0.01'))

        total_costs = materials + subcontractor + expenses + labor
        profit = invoiced - total_costs

        return {
            'revenue': {
                'invoiced': invoiced,
                'paid': paid,
            },
            'costs': {
                'materials': materials,
                'subcontractor': subcontractor,
                'expenses': expenses,
                'labor': labor,
                'total': total_costs,
            },
            'profit': profit,
        }
```

- [ ] **Step 4: Add API endpoint**

In `apps/api/jobs/views.py`, add to `JobViewSet`:

```python
    @action(detail=True, methods=['get'], url_path='profit-loss')
    def profit_loss(self, request, pk=None):
        """Return profit & loss breakdown for this job."""
        job = self.get_object()
        from decimal import Decimal
        from apps.jobs.services import JobProfitLossService
        pl = JobProfitLossService.calculate(job)
        # Convert Decimals to strings for JSON serialization
        def serialize(d):
            if isinstance(d, dict):
                return {k: serialize(v) for k, v in d.items()}
            if isinstance(d, Decimal):
                return str(d)
            return d
        return Response(serialize(pl))
```

The `profit-loss` action inherits `list`/`retrieve` permissions (`IsAuthenticated`), which is correct — any authenticated user can see job costs.

- [ ] **Step 5: Run tests**

```bash
python manage.py test tests.test_job_profit_loss -v2
```

- [ ] **Step 6: Commit**

```bash
git add apps/jobs/services.py apps/api/jobs/views.py tests/test_job_profit_loss.py
git commit -m "feat: add JobProfitLossService with API endpoint"
```

---

### Task 6: SPA Components — Expense Form, List, and Job P&L

**Files:**
- Create: `frontend/src/routes/expenses/ExpenseListPage.svelte`
- Create: `frontend/src/routes/expenses/ExpenseFormPage.svelte`
- Create: `frontend/src/components/expenses/ExpenseList.svelte`
- Create: `frontend/src/components/expenses/ExpenseForm.svelte`
- Create: `frontend/src/components/jobs/JobProfitLoss.svelte`
- Modify: `frontend/src/App.svelte` (add routes)
- Modify: `frontend/src/components/Nav.svelte` (add Expenses link)
- Modify: `frontend/src/components/jobs/JobDetail.svelte` (add P&L section)

This task creates the SPA UI for expenses and integrates the P&L view into the existing job detail page. Components follow existing patterns: Svelte 5 runes, `onMount`, semantic HTML, no CSS frameworks.

The expense and P&L components are standard CRUD UI following the same patterns as the existing Contact/Business/Job pages. Implementation details for each component are left to the implementer following patterns in:
- `frontend/src/routes/contacts/ContactListPage.svelte` (list pattern)
- `frontend/src/routes/contacts/ContactFormPage.svelte` (form pattern)
- `frontend/src/components/jobs/JobDetail.svelte` (detail with sub-sections)

Key points:
- **ExpenseListPage**: fetch `/api/expenses/`, display table with status, amount, category. Managers see approve/reject buttons on submitted expenses.
- **ExpenseFormPage**: form fields for amount, description, category dropdown, payment method dropdown, optional job link. POSTs to `/api/expenses/`.
- **JobProfitLoss**: fetch `/api/jobs/{id}/profit-loss/`, display revenue vs costs table. Embed in JobDetail.svelte as a collapsible section.
- Add routes: `'/expenses': ExpenseListPage`, `'/expenses/new': ExpenseFormPage`
- Add nav link: `<a href="#/expenses">Expenses</a>`

- [ ] **Step 1: Create expense list and form components**

Follow patterns from existing list/form pages. The implementer should reference `ContactListPage.svelte` and `ContactFormPage.svelte` for the standard patterns.

- [ ] **Step 2: Create JobProfitLoss component**

```svelte
<!-- frontend/src/components/jobs/JobProfitLoss.svelte -->
<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';

  const { jobId } = $props();

  let pl = $state(null);
  let loading = $state(true);
  let error = $state(null);

  async function loadPL() {
    loading = true;
    try {
      pl = await api.get(`/api/jobs/${jobId}/profit-loss/`);
    } catch (e) {
      error = e.message || 'Failed to load P&L';
    } finally {
      loading = false;
    }
  }

  onMount(() => { loadPL(); });
</script>

{#if loading}
  <p>Loading P&L...</p>
{:else if error}
  <p><strong>Error:</strong> {error}</p>
{:else if pl}
  <fieldset>
    <legend><strong>Profit & Loss</strong></legend>
    <table border="1">
      <tr><td><strong>Revenue (Invoiced)</strong></td><td style="text-align:right">${pl.revenue.invoiced}</td></tr>
      <tr><td>Paid</td><td style="text-align:right">${pl.revenue.paid}</td></tr>
      <tr><td colspan="2"><strong>Costs</strong></td></tr>
      <tr><td>Materials</td><td style="text-align:right">${pl.costs.materials}</td></tr>
      <tr><td>Subcontractor</td><td style="text-align:right">${pl.costs.subcontractor}</td></tr>
      <tr><td>Labor</td><td style="text-align:right">${pl.costs.labor}</td></tr>
      <tr><td>Expenses</td><td style="text-align:right">${pl.costs.expenses}</td></tr>
      <tr><td><strong>Total Costs</strong></td><td style="text-align:right">${pl.costs.total}</td></tr>
      <tr><td><strong>Profit</strong></td><td style="text-align:right"><strong>${pl.profit}</strong></td></tr>
    </table>
  </fieldset>
{/if}
```

- [ ] **Step 3: Add routes and navigation**

In `App.svelte`, add imports and routes for expense pages. In `Nav.svelte`, add Expenses link. In `JobDetail.svelte`, add `<JobProfitLoss jobId={job.job_id} />` section.

- [ ] **Step 4: Verify manually**

```bash
./dev.sh
```

Test: create an expense, verify it appears in the list. If manager, approve it. Navigate to a job detail — verify P&L section shows.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat: add SPA expense pages and job P&L component"
```

---

### Task 7: Run Full Test Suite and Verify

- [ ] **Step 1: Run full test suite**

```bash
python manage.py test -v2
```

- [ ] **Step 2: Review what was built**

| Component | Location | Purpose |
|---|---|---|
| Expense model | `apps/expenses/models.py` | Employee-submitted expenses with approval workflow |
| ExpenseService | `apps/expenses/services.py` | Submit, approve, reject with auto-approval threshold |
| ExpenseViewSet | `apps/api/expenses/views.py` | CRUD + approve/reject actions |
| QBOExpenseSyncService | `apps/qbo/services.py` | Push to QBO as Purchase or Bill |
| JobProfitLossService | `apps/jobs/services.py` | Aggregate revenue and costs per job |
| profit-loss endpoint | `/api/jobs/{id}/profit-loss/` | P&L data for SPA |
| Expense SPA pages | `frontend/src/routes/expenses/` | List, create |
| Job P&L component | `frontend/src/components/jobs/` | Embedded in job detail |

- [ ] **Step 3: Commit if any cleanup needed**

```bash
git status
git add apps/ tests/ frontend/ && git commit -m "chore: expenses and job P&L cleanup"
```
