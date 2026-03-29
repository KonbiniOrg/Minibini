# QBO Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish QBO integration infrastructure — OAuth connection, service layer with testable mock boundary, customer/vendor sync.

**Architecture:** New `apps/qbo/` Django app isolates all QBO concerns. A `QBOService` class wraps `python-quickbooks` calls and serves as the mock boundary for tests. OAuth tokens stored in a dedicated model. Customer/vendor sync is lazy (triggered when needed by future invoice/bill push).

**Tech Stack:** Django 5.2+, python-quickbooks, Intuit OAuth 2.0, MySQL

**Design spec:** `docs/designs/2026-03-28-quickbooks-integration.md`

---

## File Structure

```
apps/qbo/                          # New Django app
├── __init__.py
├── apps.py                        # AppConfig
├── models.py                      # QBOConnection, QBOSyncLog
├── services.py                    # QBOService (mock boundary), QBOCustomerService, QBOVendorService
├── views.py                       # OAuth callback, connection status API
├── urls.py                        # /api/qbo/ endpoints
├── admin.py                       # QBOConnection, QBOSyncLog admin
└── migrations/
    └── 0001_initial.py

apps/contacts/
└── migrations/
    └── NNNN_add_qbo_ids_to_business.py   # Add qbo_customer_id, qbo_vendor_id

tests/
├── test_qbo_service.py            # QBOService unit tests (mocked)
├── test_qbo_customer_sync.py      # Customer sync logic tests
├── test_qbo_vendor_sync.py        # Vendor sync logic tests
├── test_qbo_connection.py         # OAuth flow and token management tests
└── test_qbo_display_name.py       # DisplayName generation logic tests
```

---

### Task 1: Developer Account Setup and Dependency Installation

**Files:**
- Modify: `requirements.txt`
- Modify: `minibini/settings.py`

This is a prep task — no tests, just environment setup.

- [ ] **Step 1: Register Intuit developer account**

Go to https://developer.intuit.com/ and create a free developer account. This gives you access to:
- Sandbox company with test data
- OAuth client credentials (client_id, client_secret)
- API Explorer for manual testing

Document the sandbox credentials. Do NOT commit them to the repo.

- [ ] **Step 2: Install python-quickbooks**

Add to `requirements.txt`:

```
python-quickbooks==0.9.8
```

Run:
```bash
pip install -r requirements.txt
```

- [ ] **Step 3: Add QBO settings to settings.py**

Add after the existing `EMAIL_*` settings block (around line 140):

```python
# QuickBooks Online Integration
QBO_CLIENT_ID = os.environ.get('QBO_CLIENT_ID', '')
QBO_CLIENT_SECRET = os.environ.get('QBO_CLIENT_SECRET', '')
QBO_REDIRECT_URI = os.environ.get('QBO_REDIRECT_URI', 'http://localhost:8000/api/qbo/callback/')
QBO_ENVIRONMENT = os.environ.get('QBO_ENVIRONMENT', 'sandbox')  # 'sandbox' or 'production'
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt minibini/settings.py
git commit -m "chore: add python-quickbooks dependency and QBO settings"
```

---

### Task 2: Create the `apps/qbo` Django App

**Files:**
- Create: `apps/qbo/__init__.py`
- Create: `apps/qbo/apps.py`
- Create: `apps/qbo/models.py` (empty initially)
- Create: `apps/qbo/services.py` (empty initially)
- Create: `apps/qbo/views.py` (empty initially)
- Create: `apps/qbo/urls.py` (empty initially)
- Create: `apps/qbo/admin.py` (empty initially)
- Modify: `minibini/settings.py` (INSTALLED_APPS)

- [ ] **Step 1: Create app directory and boilerplate files**

```python
# apps/qbo/__init__.py
# (empty)

# apps/qbo/apps.py
from django.apps import AppConfig

class QboConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.qbo'
    verbose_name = 'QuickBooks Online Integration'
```

```python
# apps/qbo/models.py
from django.db import models

# Models added in Task 3

# apps/qbo/services.py
# Services added in Task 5

# apps/qbo/views.py
# Views added in Task 7

# apps/qbo/urls.py
from django.urls import path
urlpatterns = []

# apps/qbo/admin.py
from django.contrib import admin
```

- [ ] **Step 2: Add to INSTALLED_APPS**

In `minibini/settings.py`, add `'apps.qbo'` to INSTALLED_APPS after `'apps.inventory'`:

```python
INSTALLED_APPS = [
    # ... existing apps ...
    'apps.inventory',
    'apps.qbo',
    # ...
]
```

- [ ] **Step 3: Verify the app loads**

```bash
python manage.py check
```

Expected: `System check identified no issues.`

- [ ] **Step 4: Commit**

```bash
git add apps/qbo/ minibini/settings.py
git commit -m "feat: create apps/qbo Django app skeleton"
```

---

### Task 3: QBOConnection and QBOSyncLog Models

**Files:**
- Modify: `apps/qbo/models.py`
- Modify: `apps/qbo/admin.py`
- Create: `apps/qbo/migrations/0001_initial.py` (auto-generated)
- Test: `tests/test_qbo_connection.py`

- [ ] **Step 1: Write the failing test for QBOConnection**

```python
# tests/test_qbo_connection.py
from django.test import TestCase
from django.utils import timezone
from apps.qbo.models import QBOConnection, QBOSyncLog


class QBOConnectionModelTest(TestCase):
    """Test QBOConnection model creation and methods."""

    def test_create_connection(self):
        """Can create a QBO connection record."""
        now = timezone.now()
        conn = QBOConnection.objects.create(
            realm_id='1234567890',
            access_token='test_access_token',
            refresh_token='test_refresh_token',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )
        self.assertEqual(conn.realm_id, '1234567890')
        self.assertTrue(conn.is_active)

    def test_is_access_token_expired(self):
        """is_access_token_expired returns True when token is past expiry."""
        now = timezone.now()
        conn = QBOConnection.objects.create(
            realm_id='123',
            access_token='tok',
            refresh_token='ref',
            access_token_expires_at=now - timezone.timedelta(minutes=5),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )
        self.assertTrue(conn.is_access_token_expired)

    def test_is_access_token_not_expired(self):
        """is_access_token_expired returns False when token is still valid."""
        now = timezone.now()
        conn = QBOConnection.objects.create(
            realm_id='123',
            access_token='tok',
            refresh_token='ref',
            access_token_expires_at=now + timezone.timedelta(minutes=30),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )
        self.assertFalse(conn.is_access_token_expired)

    def test_is_refresh_token_expiring_soon(self):
        """is_refresh_token_expiring_soon returns True within 7 days of expiry."""
        now = timezone.now()
        conn = QBOConnection.objects.create(
            realm_id='123',
            access_token='tok',
            refresh_token='ref',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=5),
            connected_at=now,
        )
        self.assertTrue(conn.is_refresh_token_expiring_soon)

    def test_str_representation(self):
        """String representation includes realm_id and status."""
        now = timezone.now()
        conn = QBOConnection.objects.create(
            realm_id='123',
            access_token='tok',
            refresh_token='ref',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )
        self.assertIn('123', str(conn))


class QBOSyncLogModelTest(TestCase):
    """Test QBOSyncLog model."""

    def test_create_sync_log(self):
        """Can create a sync log entry."""
        log = QBOSyncLog.objects.create(
            entity_type='customer',
            entity_id=42,
            qbo_entity_type='Customer',
            qbo_entity_id='99',
            action='create',
            status='success',
        )
        self.assertEqual(log.entity_type, 'customer')
        self.assertEqual(log.status, 'success')
        self.assertIsNotNone(log.synced_at)

    def test_create_failed_sync_log(self):
        """Can create a failed sync log with error message."""
        log = QBOSyncLog.objects.create(
            entity_type='invoice',
            entity_id=10,
            qbo_entity_type='Invoice',
            qbo_entity_id='',
            action='create',
            status='failed',
            error_message='Authentication expired',
        )
        self.assertEqual(log.status, 'failed')
        self.assertEqual(log.error_message, 'Authentication expired')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_connection -v2
```

Expected: ImportError — `cannot import name 'QBOConnection' from 'apps.qbo.models'`

- [ ] **Step 3: Implement the models**

```python
# apps/qbo/models.py
from django.db import models
from django.utils import timezone


class QBOConnection(models.Model):
    """
    Stores OAuth tokens and connection state for QuickBooks Online.
    Singleton per Minibini instance — only one active QBO connection at a time.
    """
    realm_id = models.CharField(max_length=50)
    access_token = models.TextField()
    refresh_token = models.TextField()
    access_token_expires_at = models.DateTimeField()
    refresh_token_expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    connected_at = models.DateTimeField()
    last_sync_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'qbo_connection'

    def __str__(self):
        status = 'active' if self.is_active else 'inactive'
        return f"QBO Connection {self.realm_id} ({status})"

    @property
    def is_access_token_expired(self):
        return timezone.now() >= self.access_token_expires_at

    @property
    def is_refresh_token_expiring_soon(self):
        """True if refresh token expires within 7 days."""
        return timezone.now() >= self.refresh_token_expires_at - timezone.timedelta(days=7)


class QBOSyncLog(models.Model):
    """Audit trail for all QBO sync operations."""
    entity_type = models.CharField(max_length=50)
    entity_id = models.IntegerField()
    qbo_entity_type = models.CharField(max_length=50)
    qbo_entity_id = models.CharField(max_length=50, blank=True)
    action = models.CharField(max_length=20)
    status = models.CharField(max_length=20)
    error_message = models.TextField(blank=True)
    synced_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'qbo_sync_log'
        ordering = ['-synced_at']

    def __str__(self):
        return f"{self.action} {self.entity_type}:{self.entity_id} → {self.qbo_entity_type} ({self.status})"
```

- [ ] **Step 4: Generate migration**

```bash
python manage.py makemigrations qbo
```

Expected: `0001_initial.py` created with QBOConnection and QBOSyncLog tables.

- [ ] **Step 5: Register in admin**

```python
# apps/qbo/admin.py
from django.contrib import admin
from .models import QBOConnection, QBOSyncLog


@admin.register(QBOConnection)
class QBOConnectionAdmin(admin.ModelAdmin):
    list_display = ['realm_id', 'is_active', 'connected_at', 'last_sync_at']
    readonly_fields = ['access_token', 'refresh_token']


@admin.register(QBOSyncLog)
class QBOSyncLogAdmin(admin.ModelAdmin):
    list_display = ['entity_type', 'entity_id', 'qbo_entity_type', 'action', 'status', 'synced_at']
    list_filter = ['entity_type', 'action', 'status']
    ordering = ['-synced_at']
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
python manage.py test tests.test_qbo_connection -v2
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/qbo/models.py apps/qbo/admin.py apps/qbo/migrations/ tests/test_qbo_connection.py
git commit -m "feat: add QBOConnection and QBOSyncLog models"
```

---

### Task 4: Add QBO ID Fields to Business Model

**Files:**
- Modify: `apps/contacts/models.py`
- Create: `apps/contacts/migrations/NNNN_add_qbo_ids_to_business.py` (auto-generated)
- Modify: `apps/api/contacts/serializers.py`
- Test: `tests/test_qbo_connection.py` (add tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_qbo_connection.py`:

```python
from apps.contacts.models import Business


class BusinessQBOFieldsTest(TestCase):
    """Test QBO ID fields on Business model."""

    def _create_business(self, name='Test Corp', **kwargs):
        """Helper: create a Business with required Contact."""
        from apps.contacts.models import Contact
        contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', mobile_number='555-0000',
        )
        return Business.objects.create(
            business_name=name, default_contact=contact, **kwargs
        )

    def test_business_has_qbo_customer_id(self):
        """Business model has qbo_customer_id field, blank by default."""
        biz = self._create_business()
        self.assertEqual(biz.qbo_customer_id, '')

    def test_business_has_qbo_vendor_id(self):
        """Business model has qbo_vendor_id field, blank by default."""
        biz = self._create_business()
        self.assertEqual(biz.qbo_vendor_id, '')

    def test_business_can_be_both_customer_and_vendor(self):
        """A business can have both QBO customer and vendor IDs."""
        biz = self._create_business()
        biz.qbo_customer_id = '100'
        biz.qbo_vendor_id = '200'
        biz.save()
        biz.refresh_from_db()
        self.assertEqual(biz.qbo_customer_id, '100')
        self.assertEqual(biz.qbo_vendor_id, '200')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_connection.BusinessQBOFieldsTest -v2
```

Expected: FieldError or AttributeError — fields don't exist yet.

- [ ] **Step 3: Add fields to Business model**

In `apps/contacts/models.py`, add to the Business model after the `default_contact` field (around line 160):

```python
    # QuickBooks Online sync IDs
    qbo_customer_id = models.CharField(max_length=50, blank=True, default='')
    qbo_vendor_id = models.CharField(max_length=50, blank=True, default='')
```

- [ ] **Step 4: Generate migration**

```bash
python manage.py makemigrations contacts
```

- [ ] **Step 5: Update API serializer to include QBO fields (read-only)**

In `apps/api/contacts/serializers.py`, find the `BusinessSerializer` class and add `qbo_customer_id` and `qbo_vendor_id` to the `fields` list in `Meta`. Also add them to `read_only_fields`:

```python
read_only_fields = [..., 'qbo_customer_id', 'qbo_vendor_id']
```

These are informational — the API consumer can see sync status but can't set QBO IDs directly.

- [ ] **Step 6: Run tests to verify they pass**

```bash
python manage.py test tests.test_qbo_connection -v2
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/contacts/models.py apps/contacts/migrations/ apps/api/contacts/serializers.py tests/test_qbo_connection.py
git commit -m "feat: add qbo_customer_id and qbo_vendor_id to Business model"
```

---

### Task 5: QBOService — The Mock Boundary

**Files:**
- Modify: `apps/qbo/services.py`
- Test: `tests/test_qbo_service.py`

This is the thin wrapper around `python-quickbooks`. All QBO API calls go through this class. Tests mock at this boundary.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_qbo_service.py
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from apps.qbo.models import QBOConnection
from apps.qbo.services import QBOService


class QBOServiceConnectionTest(TestCase):
    """Test QBOService connection management."""

    def setUp(self):
        now = timezone.now()
        self.connection = QBOConnection.objects.create(
            realm_id='123456',
            access_token='valid_token',
            refresh_token='valid_refresh',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )

    def test_get_active_connection(self):
        """get_active_connection returns the active QBO connection."""
        conn = QBOService.get_active_connection()
        self.assertEqual(conn.realm_id, '123456')

    def test_get_active_connection_none_when_inactive(self):
        """get_active_connection returns None when no active connection."""
        self.connection.is_active = False
        self.connection.save()
        self.assertIsNone(QBOService.get_active_connection())

    def test_get_active_connection_none_when_empty(self):
        """get_active_connection returns None when no connections exist."""
        QBOConnection.objects.all().delete()
        self.assertIsNone(QBOService.get_active_connection())


class QBOServiceSyncLogTest(TestCase):
    """Test QBOService sync logging."""

    def test_log_sync_success(self):
        """log_sync creates a success log entry."""
        from apps.qbo.models import QBOSyncLog
        QBOService.log_sync(
            entity_type='customer',
            entity_id=42,
            qbo_entity_type='Customer',
            qbo_entity_id='99',
            action='create',
            status='success',
        )
        log = QBOSyncLog.objects.get(entity_id=42)
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.qbo_entity_id, '99')

    def test_log_sync_failure(self):
        """log_sync creates a failure log entry with error message."""
        from apps.qbo.models import QBOSyncLog
        QBOService.log_sync(
            entity_type='customer',
            entity_id=42,
            qbo_entity_type='Customer',
            qbo_entity_id='',
            action='create',
            status='failed',
            error_message='Auth expired',
        )
        log = QBOSyncLog.objects.get(entity_id=42)
        self.assertEqual(log.status, 'failed')
        self.assertEqual(log.error_message, 'Auth expired')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_service -v2
```

Expected: ImportError — `cannot import name 'QBOService'`

- [ ] **Step 3: Implement QBOService**

```python
# apps/qbo/services.py
import datetime
from django.conf import settings
from django.utils import timezone
from apps.qbo.models import QBOConnection, QBOSyncLog


class QBOService:
    """
    Thin wrapper around python-quickbooks API calls.
    This class is the mock boundary — tests mock methods on this class
    rather than mocking python-quickbooks internals.
    """

    @staticmethod
    def get_active_connection():
        """Return the active QBO connection, or None."""
        return QBOConnection.objects.filter(is_active=True).first()

    @staticmethod
    def get_client():
        """
        Build and return an authenticated QuickBooks client.
        Refreshes the access token if expired.
        Returns None if no active connection.
        """
        conn = QBOService.get_active_connection()
        if not conn:
            return None

        from quickbooks import QuickBooks
        from intuitlib.client import AuthClient

        auth_client = AuthClient(
            client_id=settings.QBO_CLIENT_ID,
            client_secret=settings.QBO_CLIENT_SECRET,
            redirect_uri=settings.QBO_REDIRECT_URI,
            environment=settings.QBO_ENVIRONMENT,
            access_token=conn.access_token,
            refresh_token=conn.refresh_token,
        )

        if conn.is_access_token_expired:
            auth_client.refresh()
            now = timezone.now()
            conn.access_token = auth_client.access_token
            conn.refresh_token = auth_client.refresh_token
            conn.access_token_expires_at = now + datetime.timedelta(hours=1)
            conn.refresh_token_expires_at = now + datetime.timedelta(days=100)
            conn.save()

        return QuickBooks(
            auth_client=auth_client,
            refresh_token=conn.refresh_token,
            company_id=conn.realm_id,
        )

    @staticmethod
    def log_sync(entity_type, entity_id, qbo_entity_type, qbo_entity_id,
                 action, status, error_message=''):
        """Create a sync log entry."""
        return QBOSyncLog.objects.create(
            entity_type=entity_type,
            entity_id=entity_id,
            qbo_entity_type=qbo_entity_type,
            qbo_entity_id=qbo_entity_id,
            action=action,
            status=status,
            error_message=error_message,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python manage.py test tests.test_qbo_service -v2
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/qbo/services.py tests/test_qbo_service.py
git commit -m "feat: add QBOService with connection management and sync logging"
```

---

### Task 6: DisplayName Generation Logic

**Files:**
- Modify: `apps/qbo/services.py`
- Test: `tests/test_qbo_display_name.py`

This is pure logic — no API calls. Determines the QBO DisplayName for a Business based on whether it already has a customer or vendor record in QBO.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_qbo_display_name.py
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.qbo.services import QBODisplayNameService


class DisplayNameGenerationTest(TestCase):
    """Test QBO DisplayName generation for customer/vendor records."""

    def _create_business(self, name='Acme Corp', **kwargs):
        """Helper: create a Business with required Contact."""
        contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', mobile_number='555-0000',
        )
        return Business.objects.create(
            business_name=name, default_contact=contact, **kwargs
        )

    def test_first_record_uses_plain_name(self):
        """First QBO record for a business uses the business name as-is."""
        biz = self._create_business()
        name = QBODisplayNameService.generate_display_name(biz, role='customer')
        self.assertEqual(name, 'Acme Corp')

    def test_vendor_first_uses_plain_name(self):
        """If vendor is created first, it gets the plain name."""
        biz = self._create_business()
        name = QBODisplayNameService.generate_display_name(biz, role='vendor')
        self.assertEqual(name, 'Acme Corp')

    def test_second_record_gets_suffix_customer(self):
        """If vendor exists, customer record gets (Customer) suffix."""
        biz = self._create_business(qbo_vendor_id='200')
        name = QBODisplayNameService.generate_display_name(biz, role='customer')
        self.assertEqual(name, 'Acme Corp (Customer)')

    def test_second_record_gets_suffix_vendor(self):
        """If customer exists, vendor record gets (Vendor) suffix."""
        biz = self._create_business(qbo_customer_id='100')
        name = QBODisplayNameService.generate_display_name(biz, role='vendor')
        self.assertEqual(name, 'Acme Corp (Vendor)')

    def test_both_exist_customer_gets_suffix(self):
        """If both exist, customer still gets suffix (other role exists)."""
        biz = self._create_business(qbo_customer_id='100', qbo_vendor_id='200')
        name = QBODisplayNameService.generate_display_name(biz, role='customer')
        self.assertEqual(name, 'Acme Corp (Customer)')

    def test_both_exist_vendor_gets_suffix(self):
        """If both exist, vendor still gets suffix (other role exists)."""
        biz = self._create_business(qbo_customer_id='100', qbo_vendor_id='200')
        name = QBODisplayNameService.generate_display_name(biz, role='vendor')
        self.assertEqual(name, 'Acme Corp (Vendor)')

    def test_long_name_truncated(self):
        """QBO DisplayName max is 500 chars. Suffix still fits."""
        long_name = 'A' * 495
        biz = self._create_business(name=long_name, qbo_customer_id='100')
        name = QBODisplayNameService.generate_display_name(biz, role='vendor')
        self.assertLessEqual(len(name), 500)
        self.assertTrue(name.endswith('(Vendor)'))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_display_name -v2
```

Expected: ImportError — `cannot import name 'QBODisplayNameService'`

- [ ] **Step 3: Implement QBODisplayNameService**

Add to `apps/qbo/services.py`:

```python
class QBODisplayNameService:
    """Generates QBO-compliant DisplayNames for customer/vendor records."""

    QBO_DISPLAY_NAME_MAX = 500

    @staticmethod
    def generate_display_name(business, role):
        """
        Generate a QBO DisplayName for a Business.

        Rules:
        - First QBO record for this business uses the plain business_name.
        - Second record gets a suffix: (Customer) or (Vendor).
        - role: 'customer' or 'vendor'
        """
        name = business.business_name
        other_role_field = (
            'qbo_vendor_id' if role == 'customer' else 'qbo_customer_id'
        )

        other_exists = bool(getattr(business, other_role_field, ''))

        if other_exists:
            suffix = f' ({role.capitalize()})'
            max_base = QBODisplayNameService.QBO_DISPLAY_NAME_MAX - len(suffix)
            name = name[:max_base] + suffix

        return name
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python manage.py test tests.test_qbo_display_name -v2
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/qbo/services.py tests/test_qbo_display_name.py
git commit -m "feat: add QBODisplayNameService for customer/vendor naming"
```

---

### Task 7: Customer Sync Service

**Files:**
- Modify: `apps/qbo/services.py`
- Test: `tests/test_qbo_customer_sync.py`

Pushes a Business to QBO as a Customer. Mocks the QBO API calls in tests.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_qbo_customer_sync.py
from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.qbo.models import QBOSyncLog
from apps.qbo.services import QBOCustomerSyncService


class CustomerSyncTest(TestCase):
    """Test syncing a Business to QBO as a Customer."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='John',
            last_name='Doe',
            email='john@acme.com',
            mobile_number='555-5678',
        )
        self.business = Business.objects.create(
            business_name='Acme Corp',
            business_phone='555-1234',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_customer_creates_qbo_record(self, mock_get_client):
        """push_customer creates a Customer in QBO and stores the ID."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_customer = MagicMock()
        mock_customer.Id = '42'
        mock_customer.save = MagicMock(return_value=mock_customer)

        with patch('apps.qbo.services.QBOCustomerSyncService._build_customer',
                   return_value=mock_customer):
            result = QBOCustomerSyncService.push_customer(self.business)

        self.business.refresh_from_db()
        self.assertEqual(self.business.qbo_customer_id, '42')
        self.assertEqual(result, '42')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_customer_skips_if_already_synced(self, mock_get_client):
        """push_customer returns existing ID if already synced."""
        self.business.qbo_customer_id = '42'
        self.business.save()

        result = QBOCustomerSyncService.push_customer(self.business)
        self.assertEqual(result, '42')
        mock_get_client.assert_not_called()

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_customer_logs_success(self, mock_get_client):
        """push_customer creates a sync log on success."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_customer = MagicMock()
        mock_customer.Id = '42'
        mock_customer.save = MagicMock(return_value=mock_customer)

        with patch('apps.qbo.services.QBOCustomerSyncService._build_customer',
                   return_value=mock_customer):
            QBOCustomerSyncService.push_customer(self.business)

        log = QBOSyncLog.objects.get(entity_type='customer')
        self.assertEqual(log.entity_id, self.business.pk)
        self.assertEqual(log.qbo_entity_id, '42')
        self.assertEqual(log.status, 'success')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_customer_logs_failure(self, mock_get_client):
        """push_customer logs failure and raises on API error."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_customer = MagicMock()
        mock_customer.save = MagicMock(side_effect=Exception('QBO API error'))

        with patch('apps.qbo.services.QBOCustomerSyncService._build_customer',
                   return_value=mock_customer):
            with self.assertRaises(Exception):
                QBOCustomerSyncService.push_customer(self.business)

        log = QBOSyncLog.objects.get(entity_type='customer')
        self.assertEqual(log.status, 'failed')
        self.assertIn('QBO API error', log.error_message)

    def test_push_customer_raises_without_connection(self):
        """push_customer raises if no active QBO connection."""
        with self.assertRaises(ValueError):
            QBOCustomerSyncService.push_customer(self.business)

    def test_build_customer_fields(self):
        """_build_customer maps Business/Contact fields correctly."""
        customer = QBOCustomerSyncService._build_customer(self.business)
        self.assertEqual(customer.CompanyName, 'Acme Corp')
        self.assertEqual(customer.DisplayName, 'Acme Corp')
        self.assertEqual(customer.PrimaryPhone.FreeFormNumber, '555-1234')
        self.assertEqual(customer.PrimaryEmailAddr.Address, 'john@acme.com')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_customer_sync -v2
```

Expected: ImportError — `cannot import name 'QBOCustomerSyncService'`

- [ ] **Step 3: Implement QBOCustomerSyncService**

Add to `apps/qbo/services.py`:

```python
class QBOCustomerSyncService:
    """Syncs Minibini Business records to QBO as Customers."""

    @staticmethod
    def push_customer(business):
        """
        Push a Business to QBO as a Customer.
        Returns the QBO Customer ID.
        Skips if already synced (qbo_customer_id is set).
        """
        if business.qbo_customer_id:
            return business.qbo_customer_id

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        customer = QBOCustomerSyncService._build_customer(business)

        try:
            customer.save(qb=client)
            business.qbo_customer_id = str(customer.Id)
            business.save(update_fields=['qbo_customer_id'])

            QBOService.log_sync(
                entity_type='customer',
                entity_id=business.pk,
                qbo_entity_type='Customer',
                qbo_entity_id=str(customer.Id),
                action='create',
                status='success',
            )
            return str(customer.Id)

        except Exception as e:
            QBOService.log_sync(
                entity_type='customer',
                entity_id=business.pk,
                qbo_entity_type='Customer',
                qbo_entity_id='',
                action='create',
                status='failed',
                error_message=str(e),
            )
            raise

    @staticmethod
    def _build_customer(business):
        """Build a QBO Customer object from a Business."""
        from quickbooks.objects.customer import Customer

        customer = Customer()
        customer.CompanyName = business.business_name
        customer.DisplayName = QBODisplayNameService.generate_display_name(
            business, role='customer'
        )

        if business.business_phone:
            from quickbooks.objects.base import PhoneNumber
            customer.PrimaryPhone = PhoneNumber()
            customer.PrimaryPhone.FreeFormNumber = business.business_phone

        # Use default contact's email if available
        default_contact = business.default_contact
        if default_contact and default_contact.email:
            from quickbooks.objects.base import EmailAddress
            customer.PrimaryEmailAddr = EmailAddress()
            customer.PrimaryEmailAddr.Address = default_contact.email

        return customer
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python manage.py test tests.test_qbo_customer_sync -v2
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/qbo/services.py tests/test_qbo_customer_sync.py
git commit -m "feat: add QBOCustomerSyncService for pushing businesses to QBO"
```

---

### Task 8: Vendor Sync Service

**Files:**
- Modify: `apps/qbo/services.py`
- Test: `tests/test_qbo_vendor_sync.py`

Same pattern as customer sync but creates QBO Vendor records.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_qbo_vendor_sync.py
from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.contacts.models import Business, Contact
from apps.qbo.models import QBOSyncLog
from apps.qbo.services import QBOVendorSyncService


class VendorSyncTest(TestCase):
    """Test syncing a Business to QBO as a Vendor."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Jane',
            last_name='Smith',
            email='jane@supply.com',
            mobile_number='555-0000',
        )
        self.business = Business.objects.create(
            business_name='Supply Co',
            business_phone='555-9999',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_vendor_creates_qbo_record(self, mock_get_client):
        """push_vendor creates a Vendor in QBO and stores the ID."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_vendor = MagicMock()
        mock_vendor.Id = '55'
        mock_vendor.save = MagicMock(return_value=mock_vendor)

        with patch('apps.qbo.services.QBOVendorSyncService._build_vendor',
                   return_value=mock_vendor):
            result = QBOVendorSyncService.push_vendor(self.business)

        self.business.refresh_from_db()
        self.assertEqual(self.business.qbo_vendor_id, '55')
        self.assertEqual(result, '55')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_vendor_skips_if_already_synced(self, mock_get_client):
        """push_vendor returns existing ID if already synced."""
        self.business.qbo_vendor_id = '55'
        self.business.save()

        result = QBOVendorSyncService.push_vendor(self.business)
        self.assertEqual(result, '55')
        mock_get_client.assert_not_called()

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_vendor_gets_suffix_when_customer_exists(self, mock_get_client):
        """Vendor gets (Vendor) suffix if customer record already exists."""
        self.business.qbo_customer_id = '42'
        self.business.save()

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        with patch('apps.qbo.services.QBOVendorSyncService._build_vendor') as mock_build:
            mock_vendor = MagicMock()
            mock_vendor.Id = '55'
            mock_vendor.save = MagicMock(return_value=mock_vendor)
            mock_build.return_value = mock_vendor

            QBOVendorSyncService.push_vendor(self.business)

            # Verify _build_vendor was called with the business
            mock_build.assert_called_once_with(self.business)

    def test_build_vendor_display_name_with_existing_customer(self):
        """_build_vendor uses suffixed DisplayName when customer exists."""
        self.business.qbo_customer_id = '42'
        self.business.save()

        vendor = QBOVendorSyncService._build_vendor(self.business)
        self.assertEqual(vendor.DisplayName, 'Supply Co (Vendor)')
        self.assertEqual(vendor.CompanyName, 'Supply Co')

    def test_build_vendor_display_name_first_record(self):
        """_build_vendor uses plain name when no customer exists."""
        vendor = QBOVendorSyncService._build_vendor(self.business)
        self.assertEqual(vendor.DisplayName, 'Supply Co')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_push_vendor_logs_success(self, mock_get_client):
        """push_vendor creates a sync log on success."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_vendor = MagicMock()
        mock_vendor.Id = '55'
        mock_vendor.save = MagicMock(return_value=mock_vendor)

        with patch('apps.qbo.services.QBOVendorSyncService._build_vendor',
                   return_value=mock_vendor):
            QBOVendorSyncService.push_vendor(self.business)

        log = QBOSyncLog.objects.get(entity_type='vendor')
        self.assertEqual(log.status, 'success')
        self.assertEqual(log.qbo_entity_id, '55')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_vendor_sync -v2
```

Expected: ImportError — `cannot import name 'QBOVendorSyncService'`

- [ ] **Step 3: Implement QBOVendorSyncService**

Add to `apps/qbo/services.py`:

```python
class QBOVendorSyncService:
    """Syncs Minibini Business records to QBO as Vendors."""

    @staticmethod
    def push_vendor(business):
        """
        Push a Business to QBO as a Vendor.
        Returns the QBO Vendor ID.
        Skips if already synced (qbo_vendor_id is set).
        """
        if business.qbo_vendor_id:
            return business.qbo_vendor_id

        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        vendor = QBOVendorSyncService._build_vendor(business)

        try:
            vendor.save(qb=client)
            business.qbo_vendor_id = str(vendor.Id)
            business.save(update_fields=['qbo_vendor_id'])

            QBOService.log_sync(
                entity_type='vendor',
                entity_id=business.pk,
                qbo_entity_type='Vendor',
                qbo_entity_id=str(vendor.Id),
                action='create',
                status='success',
            )
            return str(vendor.Id)

        except Exception as e:
            QBOService.log_sync(
                entity_type='vendor',
                entity_id=business.pk,
                qbo_entity_type='Vendor',
                qbo_entity_id='',
                action='create',
                status='failed',
                error_message=str(e),
            )
            raise

    @staticmethod
    def _build_vendor(business):
        """Build a QBO Vendor object from a Business."""
        from quickbooks.objects.vendor import Vendor

        vendor = Vendor()
        vendor.CompanyName = business.business_name
        vendor.DisplayName = QBODisplayNameService.generate_display_name(
            business, role='vendor'
        )

        if business.business_phone:
            from quickbooks.objects.base import PhoneNumber
            vendor.PrimaryPhone = PhoneNumber()
            vendor.PrimaryPhone.FreeFormNumber = business.business_phone

        default_contact = business.default_contact
        if default_contact and default_contact.email:
            from quickbooks.objects.base import EmailAddress
            vendor.PrimaryEmailAddr = EmailAddress()
            vendor.PrimaryEmailAddr.Address = default_contact.email

        return vendor
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python manage.py test tests.test_qbo_vendor_sync -v2
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/qbo/services.py tests/test_qbo_vendor_sync.py
git commit -m "feat: add QBOVendorSyncService for pushing businesses as vendors"
```

---

### Task 9: OAuth Flow — API Endpoints

**Files:**
- Modify: `apps/qbo/views.py`
- Modify: `apps/qbo/urls.py`
- Modify: `apps/api/urls.py`
- Test: `tests/test_qbo_connection.py` (add OAuth tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_qbo_connection.py`:

```python
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from unittest.mock import patch, MagicMock

User = get_user_model()


class QBOOAuthFlowTest(TestCase):
    """Test the OAuth connection flow API endpoints."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(codename='can_manage_config', content_type__app_label='core')
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)

        self.worker = User.objects.create_user(username='worker', password='testpass')

    def test_connect_url_requires_auth(self):
        """QBO connect endpoint requires authentication."""
        response = self.client.get('/api/qbo/connect/')
        self.assertEqual(response.status_code, 302)  # redirect to login

    def test_connect_url_requires_can_manage_config(self):
        """QBO connect endpoint requires can_manage_config permission."""
        self.client.login(username='worker', password='testpass')
        response = self.client.get('/api/qbo/connect/')
        self.assertEqual(response.status_code, 403)

    @patch('apps.qbo.views.AuthClient')
    def test_connect_redirects_to_intuit(self, mock_auth_class):
        """QBO connect endpoint redirects to Intuit authorization URL."""
        mock_auth = MagicMock()
        mock_auth.get_authorization_url.return_value = 'https://intuit.com/oauth?state=123'
        mock_auth_class.return_value = mock_auth

        self.client.login(username='admin', password='testpass')
        response = self.client.get('/api/qbo/connect/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('intuit.com', response.url)

    def test_status_returns_not_connected(self):
        """Status endpoint returns not_connected when no connection exists."""
        self.client.login(username='admin', password='testpass')
        response = self.client.get('/api/qbo/status/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'not_connected')

    def test_status_returns_connected(self):
        """Status endpoint returns connected when active connection exists."""
        from django.utils import timezone
        now = timezone.now()
        QBOConnection.objects.create(
            realm_id='123',
            access_token='tok',
            refresh_token='ref',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )
        self.client.login(username='admin', password='testpass')
        response = self.client.get('/api/qbo/status/')
        data = response.json()
        self.assertEqual(data['status'], 'connected')
        self.assertEqual(data['realm_id'], '123')

    @patch('apps.qbo.views.AuthClient')
    def test_callback_creates_connection(self, mock_auth_class):
        """OAuth callback exchanges code for tokens and creates QBOConnection."""
        mock_auth = MagicMock()
        mock_auth.access_token = 'new_access_token'
        mock_auth.refresh_token = 'new_refresh_token'
        mock_auth_class.return_value = mock_auth

        self.client.login(username='admin', password='testpass')
        # Set the CSRF state token in session (normally set by connect view)
        session = self.client.session
        session['qbo_csrf_token'] = 'test_state'
        session.save()

        response = self.client.get('/api/qbo/callback/', {
            'code': 'auth_code_123',
            'realmId': '9876543210',
            'state': 'test_state',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/#/settings', response.url)

        conn = QBOConnection.objects.get(is_active=True)
        self.assertEqual(conn.realm_id, '9876543210')
        self.assertEqual(conn.access_token, 'new_access_token')

    @patch('apps.qbo.views.AuthClient')
    def test_callback_deactivates_prior_connections(self, mock_auth_class):
        """OAuth callback deactivates any existing active connections."""
        from django.utils import timezone
        now = timezone.now()
        old_conn = QBOConnection.objects.create(
            realm_id='old_realm',
            access_token='old_tok',
            refresh_token='old_ref',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )

        mock_auth = MagicMock()
        mock_auth.access_token = 'new_tok'
        mock_auth.refresh_token = 'new_ref'
        mock_auth_class.return_value = mock_auth

        self.client.login(username='admin', password='testpass')
        session = self.client.session
        session['qbo_csrf_token'] = 'test_state'
        session.save()

        self.client.get('/api/qbo/callback/', {
            'code': 'code', 'realmId': 'new_realm', 'state': 'test_state',
        })

        old_conn.refresh_from_db()
        self.assertFalse(old_conn.is_active)
        self.assertEqual(QBOConnection.objects.filter(is_active=True).count(), 1)

    def test_callback_rejects_invalid_state(self):
        """OAuth callback rejects requests with invalid CSRF state token."""
        self.client.login(username='admin', password='testpass')
        session = self.client.session
        session['qbo_csrf_token'] = 'correct_state'
        session.save()

        response = self.client.get('/api/qbo/callback/', {
            'code': 'auth_code', 'realmId': '123', 'state': 'wrong_state',
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(QBOConnection.objects.count(), 0)

    @patch('apps.qbo.views.AuthClient')
    def test_disconnect_deactivates_connection(self, mock_auth_class):
        """Disconnect endpoint deactivates the active connection."""
        from django.utils import timezone
        now = timezone.now()
        conn = QBOConnection.objects.create(
            realm_id='123',
            access_token='tok',
            refresh_token='ref',
            access_token_expires_at=now + timezone.timedelta(hours=1),
            refresh_token_expires_at=now + timezone.timedelta(days=100),
            connected_at=now,
        )
        self.client.login(username='admin', password='testpass')
        response = self.client.post('/api/qbo/disconnect/')
        self.assertEqual(response.status_code, 200)
        conn.refresh_from_db()
        self.assertFalse(conn.is_active)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_connection.QBOOAuthFlowTest -v2
```

Expected: 404 — URL patterns don't exist yet.

- [ ] **Step 3: Implement views**

```python
# apps/qbo/views.py
import datetime
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required, permission_required

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from intuitlib.client import AuthClient
from intuitlib.enums import Scopes

from apps.api.permissions import CanManageConfig
from apps.qbo.models import QBOConnection


# --- OAuth browser-redirect endpoints (not DRF) ---
# These use Django decorators because they involve browser redirects,
# not XHR calls from the SPA.

@login_required
@permission_required('core.can_manage_config', raise_exception=True)
@require_GET
def qbo_connect(request):
    """Initiate OAuth flow — redirect to Intuit authorization page."""
    auth_client = AuthClient(
        client_id=settings.QBO_CLIENT_ID,
        client_secret=settings.QBO_CLIENT_SECRET,
        redirect_uri=settings.QBO_REDIRECT_URI,
        environment=settings.QBO_ENVIRONMENT,
    )
    url = auth_client.get_authorization_url(scopes=[Scopes.ACCOUNTING])
    request.session['qbo_csrf_token'] = auth_client.state_token
    return redirect(url)


@login_required
@permission_required('core.can_manage_config', raise_exception=True)
@require_GET
def qbo_callback(request):
    """OAuth callback — exchange code for tokens and store connection."""
    auth_code = request.GET.get('code')
    realm_id = request.GET.get('realmId')
    state = request.GET.get('state')

    if not auth_code or not realm_id:
        return JsonResponse({'error': 'Missing code or realmId'}, status=400)

    # Validate CSRF state token to prevent OAuth CSRF attacks
    if state != request.session.get('qbo_csrf_token'):
        return JsonResponse({'error': 'Invalid state token'}, status=400)

    auth_client = AuthClient(
        client_id=settings.QBO_CLIENT_ID,
        client_secret=settings.QBO_CLIENT_SECRET,
        redirect_uri=settings.QBO_REDIRECT_URI,
        environment=settings.QBO_ENVIRONMENT,
    )
    auth_client.get_bearer_token(auth_code, realm_id=realm_id)

    now = timezone.now()

    # Deactivate any existing connections
    QBOConnection.objects.filter(is_active=True).update(is_active=False)

    QBOConnection.objects.create(
        realm_id=realm_id,
        access_token=auth_client.access_token,
        refresh_token=auth_client.refresh_token,
        access_token_expires_at=now + datetime.timedelta(hours=1),
        refresh_token_expires_at=now + datetime.timedelta(days=100),
        is_active=True,
        connected_at=now,
    )

    # Redirect to SPA settings page
    return redirect('/#/settings')


# --- DRF API endpoints (called by SPA via XHR) ---

@api_view(['GET'])
@permission_classes([IsAuthenticated, CanManageConfig])
def qbo_status(request):
    """Return current QBO connection status."""
    conn = QBOConnection.objects.filter(is_active=True).first()
    if not conn:
        return Response({'status': 'not_connected'})

    return Response({
        'status': 'connected',
        'realm_id': conn.realm_id,
        'connected_at': conn.connected_at.isoformat(),
        'last_sync_at': conn.last_sync_at.isoformat() if conn.last_sync_at else None,
        'refresh_token_expiring_soon': conn.is_refresh_token_expiring_soon,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, CanManageConfig])
def qbo_disconnect(request):
    """Disconnect from QBO — deactivate the active connection."""
    QBOConnection.objects.filter(is_active=True).update(is_active=False)
    return Response({'status': 'disconnected'})
```

- [ ] **Step 4: Add URL patterns**

```python
# apps/qbo/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('connect/', views.qbo_connect, name='qbo-connect'),
    path('callback/', views.qbo_callback, name='qbo-callback'),
    path('status/', views.qbo_status, name='qbo-status'),
    path('disconnect/', views.qbo_disconnect, name='qbo-disconnect'),
]
```

- [ ] **Step 5: Register in main API URLs**

In `apps/api/urls.py`, add the QBO URL include. Find the existing URL patterns list and add:

```python
path('qbo/', include('apps.qbo.urls')),
```

Add this alongside the other includes (after `path('expenses/', ...)`). Also add the import if not present:

```python
from django.urls import path, include
```

Note: QBO URLs are under `/api/qbo/` because they're included from the api urls.py which is mounted at `/api/`.

- [ ] **Step 6: Run tests to verify they pass**

```bash
python manage.py test tests.test_qbo_connection -v2
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/qbo/views.py apps/qbo/urls.py apps/api/urls.py tests/test_qbo_connection.py
git commit -m "feat: add QBO OAuth flow endpoints (connect, callback, status, disconnect)"
```

---

### Task 10: SPA — QBO Settings Component

**Files:**
- Create: `frontend/src/routes/SettingsPage.svelte`
- Create: `frontend/src/components/QBOConnectionCard.svelte`
- Modify: `frontend/src/App.svelte` (add route)
- Modify: `frontend/src/components/Nav.svelte` (add nav link)

This task adds the minimal SPA UI for managing the QBO connection.

- [ ] **Step 1: Create the QBO connection card component**

```svelte
<!-- frontend/src/components/QBOConnectionCard.svelte -->
<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';

  let status = $state(null);
  let loading = $state(true);
  let error = $state(null);
  let disconnecting = $state(false);

  async function loadStatus() {
    loading = true;
    error = null;
    try {
      status = await api.get('/api/qbo/status/');
    } catch (e) {
      // 403 means user doesn't have can_manage_config — hide the card
      if (e.status === 403) {
        status = null;
      } else {
        error = e.message || 'Failed to load QBO status';
      }
    } finally {
      loading = false;
    }
  }

  async function disconnect() {
    if (!confirm('Disconnect from QuickBooks Online?')) return;
    disconnecting = true;
    try {
      await api.post('/api/qbo/disconnect/');
      await loadStatus();
    } catch (e) {
      error = e.message || 'Failed to disconnect';
    } finally {
      disconnecting = false;
    }
  }

  onMount(() => {
    loadStatus();
  });
</script>

{#if loading}
  <p>Loading QuickBooks status...</p>
{:else if status === null}
  <!-- User lacks permission or endpoint unavailable — hide card -->
{:else if error}
  <p><strong>Error:</strong> {error}</p>
{:else}
  <fieldset>
    <legend><strong>QuickBooks Online</strong></legend>

    {#if status.status === 'connected'}
      <p>Status: <strong>Connected</strong></p>
      <p>Company ID: {status.realm_id}</p>
      <p>Connected: {new Date(status.connected_at).toLocaleDateString()}</p>
      {#if status.last_sync_at}
        <p>Last sync: {new Date(status.last_sync_at).toLocaleDateString()}</p>
      {/if}
      {#if status.refresh_token_expiring_soon}
        <p><strong>Warning:</strong> Connection expiring soon. Please reconnect.</p>
      {/if}
      <p>
        <button onclick={disconnect} disabled={disconnecting}>
          {disconnecting ? 'Disconnecting...' : 'Disconnect'}
        </button>
        <a href="/api/qbo/connect/">Reconnect</a>
      </p>
    {:else}
      <p>Status: <strong>Not connected</strong></p>
      <p><a href="/api/qbo/connect/">Connect to QuickBooks</a></p>
    {/if}
  </fieldset>
{/if}
```

- [ ] **Step 2: Create the Settings page**

```svelte
<!-- frontend/src/routes/SettingsPage.svelte -->
<script>
  import QBOConnectionCard from '../components/QBOConnectionCard.svelte';
</script>

<h2>Settings</h2>

<QBOConnectionCard />
```

This is intentionally minimal. Other settings (tax config, line item types, user management) will be added as they migrate from Django HTML to the SPA.

- [ ] **Step 3: Add the route to App.svelte**

In `frontend/src/App.svelte`, add the import and route:

```javascript
import SettingsPage from './routes/SettingsPage.svelte';
```

Add to the routes object:

```javascript
'/settings': SettingsPage,
```

- [ ] **Step 4: Add Settings to the navigation**

In `frontend/src/components/Nav.svelte`, add a Settings link alongside the existing nav items:

```html
<a href="#/settings">Settings</a>
```

- [ ] **Step 5: Verify manually**

Start the dev servers:
```bash
python manage.py runserver &
cd frontend && npm run dev
```

Navigate to `http://localhost:9000/#/settings`:
- Should show "Not connected" with a "Connect to QuickBooks" link
- The connect link navigates to `/api/qbo/connect/` which will fail without real QBO credentials — that's expected
- If the user lacks `can_manage_config`, the QBO card should be hidden

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/SettingsPage.svelte frontend/src/components/QBOConnectionCard.svelte frontend/src/App.svelte frontend/src/components/Nav.svelte
git commit -m "feat: add SPA settings page with QBO connection card"
```

---

### Task 11: Run Full Test Suite and Verify

**Files:** None — verification only.

- [ ] **Step 1: Run the full test suite**

```bash
python manage.py test -v2
```

Expected: All existing tests still pass. All new QBO tests pass.

- [ ] **Step 2: Verify no import issues**

```bash
python manage.py check
```

Expected: `System check identified no issues.`

- [ ] **Step 3: Review what was built**

Quick summary of what exists after this plan:

| Component | Location | Purpose |
|---|---|---|
| QBOConnection model | `apps/qbo/models.py` | OAuth tokens, connection state |
| QBOSyncLog model | `apps/qbo/models.py` | Audit trail for all sync operations |
| QBOService | `apps/qbo/services.py` | Connection management, client builder, logging (mock boundary) |
| QBODisplayNameService | `apps/qbo/services.py` | DisplayName generation with suffix logic |
| QBOCustomerSyncService | `apps/qbo/services.py` | Push Business → QBO Customer |
| QBOVendorSyncService | `apps/qbo/services.py` | Push Business → QBO Vendor |
| OAuth endpoints | `apps/qbo/views.py` | connect, callback, status, disconnect |
| Business.qbo_customer_id | `apps/contacts/models.py` | QBO Customer reference |
| Business.qbo_vendor_id | `apps/contacts/models.py` | QBO Vendor reference |
| Settings page | `frontend/src/routes/SettingsPage.svelte` | SPA settings hub |
| QBO connection card | `frontend/src/components/QBOConnectionCard.svelte` | Connect/disconnect/status UI |

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
git status
# If any unstaged changes from cleanup, add specific files:
git add apps/qbo/ tests/test_qbo_*.py && git commit -m "chore: QBO foundation cleanup"
```
