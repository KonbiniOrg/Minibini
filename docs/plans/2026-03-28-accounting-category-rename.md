# AccountingCategory Rename + QBO Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename `LineItemType` → `AccountingCategory`, add QBO account mapping fields, build chart of accounts pull endpoint and SPA category mapping UI.

**Architecture:** The rename is a codebase-wide refactor touching the model, all FK references (12+ fields across 8 models), forms, services, serializers, viewsets, admin, templates, tests, and fixtures. The QBO fields and mapping UI build on the renamed model. Database migration uses Django's `RenameModel` and `RenameField` operations.

**Tech Stack:** Django 5.2+, Django REST Framework, Svelte 5, python-quickbooks

**Design spec:** `docs/designs/2026-03-28-quickbooks-integration.md` (see "Accounting Categories" section)

**Prerequisite:** `docs/plans/2026-03-28-qbo-foundation.md` must be implemented first (QBOService, QBOConnection).

---

## File Structure

The rename touches many files. Grouped by type:

**Model + Migration (core changes):**
```
apps/core/models.py                    # Rename class, add QBO fields
apps/core/migrations/NNNN_rename_*.py  # RenameModel + AddFields
apps/jobs/migrations/NNNN_rename_*.py  # RenameField on Task, TaskBundle
apps/estimates/migrations/NNNN_*.py    # RenameField on TemplateBundle, TaskTemplate
apps/inventory/migrations/NNNN_*.py    # RenameField on PriceListItem, Material
apps/invoicing/migrations/NNNN_*.py    # RenameField on InvoiceLineItem (via BaseLineItem)
apps/purchasing/migrations/NNNN_*.py   # RenameField on PO/Bill line items (via BaseLineItem)
```

**Services:**
```
apps/core/services.py                  # ConfigurationService, TaxCalculationService
apps/jobs/services.py                  # Task creation with accounting_category
apps/estimates/services.py             # EstimateGenerationService (26 occurrences)
apps/purchasing/services.py            # Line item creation with accounting_category
```

**Forms:**
```
apps/core/forms.py                     # LineItemTypeForm → AccountingCategoryForm
apps/jobs/forms.py                     # TaskEditForm field rename
apps/estimates/forms.py                # Estimate forms field rename
apps/inventory/forms.py                # PriceListItemForm field + import rename
apps/purchasing/forms.py               # PO line item forms field + import rename
```

**Views (HTML, legacy but must not break):**
```
apps/core/views.py                     # Line item type CRUD views (rename)
apps/estimates/views.py                # 24 occurrences of line_item_type
apps/purchasing/views.py               # PO line item creation
```

**API:**
```
apps/api/templates_config/serializers.py  # Serializer + field renames
apps/api/templates_config/views.py        # ViewSet rename
apps/api/invoicing/serializers.py         # Field rename
apps/api/estimates/serializers.py         # Field rename
apps/api/purchasing/serializers.py        # Field rename
apps/api/inventory/serializers.py         # Field rename
apps/api/worksheets/serializers.py        # Field rename
apps/api/urls.py                          # Router registration rename
```

**QBO integration (new):**
```
apps/qbo/services.py                     # Add QBOAccountsService
apps/qbo/views.py                        # Add qbo_accounts endpoint
apps/qbo/urls.py                         # Add accounts URL
```

**SPA (new):**
```
frontend/src/components/AccountingCategoryMapping.svelte  # Category mapping UI
frontend/src/routes/SettingsPage.svelte                   # Add mapping component
```

**Admin, templates, tests, fixtures** — see individual tasks.

---

### Task 1: Add QBO Account Mapping Fields to LineItemType

**Files:**
- Modify: `apps/core/models.py`
- Create: `apps/core/migrations/NNNN_add_qbo_fields_to_lineitemtype.py` (auto-generated)
- Test: `tests/test_qbo_accounting_category.py`

Add the QBO fields *before* the rename — smaller migration, easier to debug.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_qbo_accounting_category.py
from django.test import TestCase
from apps.core.models import LineItemType


class LineItemTypeQBOFieldsTest(TestCase):
    """Test QBO account mapping fields on LineItemType."""

    def test_qbo_item_id_default_blank(self):
        lit = LineItemType.objects.create(code='TST', name='Test')
        self.assertEqual(lit.qbo_item_id, '')

    def test_qbo_expense_account_id_default_blank(self):
        lit = LineItemType.objects.create(code='TST', name='Test')
        self.assertEqual(lit.qbo_expense_account_id, '')

    def test_can_set_both_account_ids(self):
        """A category can map to both income and expense accounts."""
        lit = LineItemType.objects.create(
            code='MAT', name='Materials',
            qbo_item_id='42',
            qbo_expense_account_id='99',
        )
        lit.refresh_from_db()
        self.assertEqual(lit.qbo_item_id, '42')
        self.assertEqual(lit.qbo_expense_account_id, '99')

    def test_can_set_income_only(self):
        """A service category maps to income only."""
        lit = LineItemType.objects.create(
            code='SVC', name='Service',
            qbo_item_id='42',
        )
        self.assertEqual(lit.qbo_item_id, '42')
        self.assertEqual(lit.qbo_expense_account_id, '')
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_accounting_category -v2
```

Expected: Error — fields don't exist yet.

- [ ] **Step 3: Add fields to model**

In `apps/core/models.py`, add to `LineItemType` after `is_active`:

```python
    # QBO account mappings (populated after connecting to QBO)
    qbo_item_id = models.CharField(max_length=50, blank=True, default='')
    qbo_expense_account_id = models.CharField(max_length=50, blank=True, default='')
```

- [ ] **Step 4: Generate migration**

```bash
python manage.py makemigrations core
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python manage.py test tests.test_qbo_accounting_category -v2
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/core/models.py apps/core/migrations/ tests/test_qbo_accounting_category.py
git commit -m "feat: add QBO account mapping fields to LineItemType"
```

---

### Task 2: Rename Model — LineItemType → AccountingCategory

**Files:**
- Modify: `apps/core/models.py`
- Create: `apps/core/migrations/NNNN_rename_lineitemtype.py` (hand-written)

This migration renames the model class and the database table. It does NOT rename FK fields — that comes in Task 3.

- [ ] **Step 1: Rename the model class**

In `apps/core/models.py`, rename `class LineItemType` to `class AccountingCategory`. Update `db_table`:

```python
class AccountingCategory(models.Model):
    """
    Defines accounting categories with default taxability and QBO account mappings.
    Examples: Service, Material, Product, Freight, Overhead, Storage
    """
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    taxable = models.BooleanField(default=True)
    default_description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    # QBO account mappings (populated after connecting to QBO)
    qbo_item_id = models.CharField(max_length=50, blank=True, default='')
    qbo_expense_account_id = models.CharField(max_length=50, blank=True, default='')

    class Meta:
        db_table = 'accounting_categories'
        ordering = ['name']
        verbose_name_plural = 'accounting categories'

    def __str__(self):
        return self.name
```

Also update the FK in `BaseLineItem` to point to the new name (keep the field name `line_item_type` for now — renamed in Task 3):

```python
    line_item_type = models.ForeignKey(
        'core.AccountingCategory',
        on_delete=models.PROTECT,
        related_name='%(class)s_items',
        null=True,
        blank=True
    )
```

- [ ] **Step 2: Hand-write the migration**

Create `apps/core/migrations/NNNN_rename_lineitemtype_to_accountingcategory.py`:

```python
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', 'NNNN_add_qbo_fields_to_lineitemtype'),  # previous migration
        # Cross-app deps required — all apps with FKs to LineItemType
        ('jobs', 'NNNN_latest'),
        ('estimates', 'NNNN_latest'),
        ('inventory', 'NNNN_latest'),
        ('invoicing', 'NNNN_latest'),
        ('purchasing', 'NNNN_latest'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='LineItemType',
            new_name='AccountingCategory',
        ),
        migrations.AlterModelTable(
            name='AccountingCategory',
            table='accounting_categories',
        ),
        migrations.AlterModelOptions(
            name='AccountingCategory',
            options={
                'ordering': ['name'],
                'verbose_name_plural': 'accounting categories',
            },
        ),
    ]
```

Note: `RenameModel` automatically updates all FKs that reference this model in all apps. Django handles the cross-app FK updates.

- [ ] **Step 3: Update imports throughout core app**

In `apps/core/models.py`, verify the `BaseLineItem` FK now says `'core.AccountingCategory'`.

In `apps/core/admin.py`:
```python
from .models import User, Configuration, AccountingCategory
```
Rename the admin class:
```python
@admin.register(AccountingCategory)
class AccountingCategoryAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'taxable', 'is_active', 'qbo_item_id', 'qbo_expense_account_id']
    list_filter = ['taxable', 'is_active']
    search_fields = ['code', 'name']
    ordering = ['name']
```

In `apps/core/services.py`, update import:
```python
from .models import Configuration, EmailRecord, TempEmail, AccountingCategory
```

Update `ConfigurationService.create_line_item_type` and `update_line_item_type` — rename methods:
```python
    @staticmethod
    def create_accounting_category(**kwargs):
        return AccountingCategory.objects.create(**kwargs)

    @staticmethod
    def update_accounting_category(pk, **kwargs):
        try:
            category = AccountingCategory.objects.get(pk=pk)
        except AccountingCategory.DoesNotExist:
            raise NotFoundError(f'AccountingCategory with pk={pk} not found')
        for key, value in kwargs.items():
            setattr(category, key, value)
        category.save()
        return category
```

In `apps/core/forms.py`:
```python
from .models import AccountingCategory

class AccountingCategoryForm(forms.ModelForm):
    class Meta:
        model = AccountingCategory
        fields = ['code', 'name', 'taxable', 'default_description', 'is_active']
```

In `apps/core/views.py`, update import and all view function names:
- `from .models import User, AccountingCategory, ...`
- `from .forms import AccountingCategoryForm, ...`
- Rename `line_item_type_list` → `accounting_category_list`
- Rename `line_item_type_detail` → `accounting_category_detail`
- Rename `line_item_type_create` → `accounting_category_create`
- Rename `line_item_type_edit` → `accounting_category_edit`
- Update the service calls inside these views to use `ConfigurationService.create_accounting_category` and `update_accounting_category`

In `apps/core/urls.py`, update URL patterns:
```python
path('accounting-categories/', views.accounting_category_list, name='accounting_category_list'),
path('accounting-categories/create/', views.accounting_category_create, name='accounting_category_create'),
path('accounting-categories/<int:pk>/', views.accounting_category_detail, name='accounting_category_detail'),
path('accounting-categories/<int:pk>/edit/', views.accounting_category_edit, name='accounting_category_edit'),
```

- [ ] **Step 4: Update model references in other apps**

Each of these files has an import of `LineItemType` or references `'core.LineItemType'` in FK strings. Update them:

**`apps/jobs/models.py`** — Change FK string refs from `'core.LineItemType'` to `'core.AccountingCategory'` in Task and TaskBundle models.

**`apps/estimates/models.py`** — Change FK string refs in TemplateBundle and TaskTemplate.

**`apps/inventory/models.py`** — Change FK string refs in PriceListItem and Material.

**`apps/inventory/forms.py`** — Change import: `from apps.core.models import AccountingCategory` and update queryset filter.

**`apps/purchasing/forms.py`** — Change import and queryset filter.

**`apps/jobs/services.py`** — Update any references (these use FK field names, which haven't changed yet, so minimal changes).

**`apps/purchasing/services.py`** — Same.

- [ ] **Step 5: Run tests to verify nothing is broken**

```bash
python manage.py test -v2
```

Some tests will fail due to import changes. Fix any `LineItemType` references in test imports — but don't rename the FK field yet (that's Task 3).

Expected: After fixing imports, all tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/core/ apps/jobs/models.py apps/estimates/models.py apps/inventory/ apps/purchasing/
git commit -m "feat: rename LineItemType to AccountingCategory"
```

---

### Task 3: Rename FK Fields — line_item_type → accounting_category

**Files:**
- Modify: `apps/core/models.py` (BaseLineItem FK field name)
- Modify: `apps/jobs/models.py` (Task, TaskBundle)
- Modify: `apps/estimates/models.py` (TemplateBundle, TaskTemplate)
- Modify: `apps/inventory/models.py` (PriceListItem, Material)
- Create: migrations for each app (auto-generated or hand-written)

This is the broadest change — it renames the FK field (and DB column) from `line_item_type` to `accounting_category` everywhere. This includes ALL Python code (services, forms, views, serializers, tests), HTML templates, fixture files, and scripts. Expect to touch 100+ files. The test suite is the verification — all ~1800 tests must pass.

- [ ] **Step 1: Rename the FK field in BaseLineItem**

In `apps/core/models.py`, in the `BaseLineItem` class:

```python
    accounting_category = models.ForeignKey(
        'core.AccountingCategory',
        on_delete=models.PROTECT,
        related_name='%(class)s_items',
        null=True,
        blank=True
    )
```

- [ ] **Step 2: Rename FK fields in other models**

In `apps/jobs/models.py`:
- Task model: rename `line_item_type` field to `accounting_category`
- TaskBundle model: rename `line_item_type` field to `accounting_category`

In `apps/estimates/models.py`:
- TemplateBundle model: rename `line_item_type` field to `accounting_category`
- TaskTemplate model: rename `line_item_type` field to `accounting_category`

In `apps/inventory/models.py`:
- PriceListItem model: rename `line_item_type` field to `accounting_category`
- Material model: rename `line_item_type` field to `accounting_category`

- [ ] **Step 3: Generate or hand-write migrations**

For each app, create a migration with `RenameField`. This renames both the Python field and the database column.

```bash
python manage.py makemigrations core jobs estimates inventory invoicing purchasing
```

If Django doesn't auto-detect the rename, hand-write migrations using `migrations.RenameField`:

```python
# Example for apps/invoicing/migrations/NNNN_rename_line_item_type.py
from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('invoicing', 'NNNN_previous'),
        ('core', 'NNNN_rename_lineitemtype_to_accountingcategory'),
    ]
    operations = [
        migrations.RenameField(
            model_name='invoicelineitem',
            old_name='line_item_type',
            new_name='accounting_category',
        ),
    ]
```

Repeat for every model that had a `line_item_type` FK:
- `core` app: no concrete models (BaseLineItem is abstract — subclass tables get the column)
- `invoicing` app: InvoiceLineItem
- `purchasing` app: PurchaseOrderLineItem, BillLineItem
- `estimates` app: EstimateLineItem, TemplateBundle, TaskTemplate
- `jobs` app: Task, TaskBundle
- `inventory` app: PriceListItem, Material

- [ ] **Step 4: Update all Python code referencing `line_item_type`**

This is a codebase-wide search-and-replace. Every `.py` file that references `line_item_type` as a field name needs updating. Key locations:

**Services:**
- `apps/core/services.py` — `TaxCalculationService.get_effective_taxability()`: change `line_item.line_item_type` → `line_item.accounting_category`
- `apps/jobs/services.py` — all task creation/copy code
- `apps/purchasing/services.py` — line item creation code

**Forms:**
- `apps/core/forms.py` — field list
- `apps/jobs/forms.py` — `TaskEditForm` fields list
- `apps/inventory/forms.py` — `PriceListItemForm` fields and queryset
- `apps/purchasing/forms.py` — PO line item forms

**API Serializers:**
- `apps/api/templates_config/serializers.py` — all serializer field lists
- `apps/api/invoicing/serializers.py` — InvoiceLineItemSerializer fields
- `apps/api/estimates/serializers.py` — EstimateLineItemSerializer fields
- `apps/api/purchasing/serializers.py` — PO and Bill line item serializer fields
- `apps/api/inventory/serializers.py` — PriceListItemSerializer fields
- `apps/api/worksheets/serializers.py` — Task and bundle serializer fields

**HTML Templates (minimal — these are being replaced):**
- Search for `line_item_type` in `templates/` directory
- Replace with `accounting_category` in template variable references
- Approximately 20 template files need updates

**Management commands:**
- `apps/core/management/commands/validate_data.py`

- [ ] **Step 5: Update API ViewSet and URL**

In `apps/api/templates_config/views.py`:
```python
from apps.core.models import Configuration, AccountingCategory

class AccountingCategoryViewSet(viewsets.ModelViewSet):
    queryset = AccountingCategory.objects.all()
    serializer_class = AccountingCategorySerializer
    # ... rest stays the same but update service calls
```

In `apps/api/templates_config/serializers.py`:
```python
from apps.core.models import Configuration, AccountingCategory

class AccountingCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingCategory
        fields = ['id', 'code', 'name', 'taxable', 'default_description', 'is_active',
                  'qbo_item_id', 'qbo_expense_account_id']
        read_only_fields = ['id']
```

In `apps/api/urls.py`:
```python
from apps.api.templates_config.views import ..., AccountingCategoryViewSet

router.register(r'accounting-categories', AccountingCategoryViewSet, basename='accounting-category')
```

Also update the api_root response to list `'accounting-categories'` instead of `'line-item-types'`.

- [ ] **Step 6: Run full test suite**

```bash
python manage.py test -v2
```

Fix all failures — they should all be field name references (`line_item_type` → `accounting_category`). This is mechanical but there are ~30 test files to update.

- [ ] **Step 7: Rename HTML template files**

```bash
mv templates/core/line_item_type_list.html templates/core/accounting_category_list.html
mv templates/core/line_item_type_detail.html templates/core/accounting_category_detail.html
mv templates/core/line_item_type_form.html templates/core/accounting_category_form.html
```

Update template references in the renamed views (Task 2) to point to new filenames. Also grep for `{% url 'core:line_item_type` across all templates and update to `{% url 'core:accounting_category`.

- [ ] **Step 8: Update fixture files**

In all fixture JSON files, rename the FK field:
- `"line_item_type"` → `"accounting_category"` in field references
- Model references: `"core.lineitemtype"` → `"core.accountingcategory"` (Django's natural key format)

Files (find all with `grep -rl "line_item_type\|lineitemtype" fixtures/`):
- `fixtures/unit_test_data.json`
- `fixtures/jobs_basic_data.json`
- `fixtures/mixed_lineitems.json`
- `fixtures/webserver_test_data.json`
- `fixtures/webserver_test_data_old.json`
- `fixtures/workorder_from_estimate.json`
- `fixtures/featuredata/line_item_type_test_data.json`
- `fixtures/large_datasets/data-lineitemtypes.json`
- Any others found by the grep

- [ ] **Step 9: Update scripts**

`scripts/seed_data.sh` has ~118 references to `line_item_type` and `line-item-types`. Update API endpoint references and field names.

- [ ] **Step 10: Update CLAUDE.md**

Replace all references to `LineItemType` with `AccountingCategory`, update URL structure section (`/api/line-item-types/` → `/api/accounting-categories/`), and update the Architecture section model listing.

- [ ] **Step 11: Grep verification — confirm nothing was missed**

```bash
grep -rn "LineItemType\|line_item_type\|line-item-type" apps/ templates/ tests/ fixtures/ scripts/ CLAUDE.md --include="*.py" --include="*.html" --include="*.json" --include="*.sh" --include="*.md" | grep -v migrations/ | grep -v __pycache__
```

Expected: No matches (migrations are excluded — they retain old names as part of history).

- [ ] **Step 12: Run full test suite**

```bash
python manage.py test -v2
```

Expected: All tests pass.

- [ ] **Step 13: Commit**

```bash
git add -u  # stages all modified tracked files (100+ files, specific listing impractical)
git add apps/*/migrations/
git commit -m "feat: rename line_item_type FK to accounting_category across all models"
```

---

### Task 4: Rename Test Files (Cosmetic)

**Files:**
- Rename: test files with `line_item_type` in their names
- Modify: test class names and variable names (cosmetic, functionality already updated in Task 3)

Note: Test *imports* and *field references* were already updated in Task 3 (required for tests to pass). This task is purely cosmetic — renaming files and class names for consistency.

- [ ] **Step 1: Rename test files**

```bash
mv tests/test_line_item_type.py tests/test_accounting_category.py
mv tests/test_line_item_type_views.py tests/test_accounting_category_views.py
mv tests/test_line_item_type_ui.py tests/test_accounting_category_ui.py
mv tests/test_line_item_type_integration.py tests/test_accounting_category_integration.py
mv tests/test_estimate_line_item_type.py tests/test_estimate_accounting_category.py
mv tests/test_price_list_item_line_item_type.py tests/test_price_list_item_accounting_category.py
mv tests/test_price_list_item_type_ui.py tests/test_price_list_item_category_ui.py
mv tests/test_po_line_item_type.py tests/test_po_accounting_category.py
mv tests/test_bill_line_item_type.py tests/test_bill_accounting_category.py
```

- [ ] **Step 2: Update imports and references in all test files**

Search and replace across all test files:
- `from apps.core.models import ... LineItemType ...` → `AccountingCategory`
- `LineItemType.objects.create(` → `AccountingCategory.objects.create(`
- `line_item_type=` → `accounting_category=` (as keyword arguments)
- `self.line_item_type` → `self.accounting_category` (in setUp and test methods)
- Class names like `LineItemTypeTest` → `AccountingCategoryTest`
- URL references: `line-item-types` → `accounting-categories` in API tests

This touches ~30 test files. Use grep to find them all:
```bash
grep -rl "LineItemType\|line_item_type\|line-item-type" tests/
```

- [ ] **Step 3: Update the QBO test file**

In `tests/test_qbo_accounting_category.py`, update import:
```python
from apps.core.models import AccountingCategory
```

And update test class to use new name:
```python
class AccountingCategoryQBOFieldsTest(TestCase):
    def test_qbo_item_id_default_blank(self):
        cat = AccountingCategory.objects.create(code='TST', name='Test')
        self.assertEqual(cat.qbo_item_id, '')
    # ... etc
```

- [ ] **Step 4: Run full test suite**

```bash
python manage.py test -v2
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "refactor: rename test files and references for AccountingCategory"
```

---

### Task 5: QBO Chart of Accounts Pull

**Files:**
- Modify: `apps/qbo/services.py`
- Modify: `apps/qbo/views.py`
- Modify: `apps/qbo/urls.py`
- Test: `tests/test_qbo_accounts.py`

New service and endpoint to pull income and expense accounts from QBO for the category mapping UI.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_qbo_accounts.py
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from apps.qbo.services import QBOAccountsService

User = get_user_model()


class QBOAccountsServiceTest(TestCase):
    """Test pulling chart of accounts from QBO."""

    @patch('apps.qbo.services.QBOService.get_client')
    def test_get_income_items(self, mock_get_client):
        """Returns Service and NonInventory Items from QBO."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_item_1 = MagicMock()
        mock_item_1.Id = '1'
        mock_item_1.Name = 'CNC Machining'
        mock_item_1.Type = 'Service'

        mock_item_2 = MagicMock()
        mock_item_2.Id = '2'
        mock_item_2.Name = 'Materials Sales'
        mock_item_2.Type = 'NonInventory'

        with patch('quickbooks.objects.item.Item.filter',
                   return_value=[mock_item_1, mock_item_2]):
            items = QBOAccountsService.get_income_items()

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['id'], '1')
        self.assertEqual(items[0]['name'], 'CNC Machining')

    @patch('apps.qbo.services.QBOService.get_client')
    def test_get_expense_accounts(self, mock_get_client):
        """Returns expense and COGS accounts from QBO."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_account = MagicMock()
        mock_account.Id = '10'
        mock_account.Name = 'Shop Supplies'
        mock_account.AccountType = 'Expense'
        mock_account.AccountSubType = 'SuppliesMaterials'

        with patch('quickbooks.objects.account.Account.filter',
                   return_value=[mock_account]):
            accounts = QBOAccountsService.get_expense_accounts()

        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]['name'], 'Shop Supplies')

    def test_raises_without_connection(self):
        """Raises ValueError if no active QBO connection."""
        with self.assertRaises(ValueError):
            QBOAccountsService.get_income_items()


class QBOAccountsEndpointTest(TestCase):
    """Test the /api/qbo/accounts/ endpoint."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(codename='can_manage_config', content_type__app_label='core')
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)

    @patch('apps.qbo.views.QBOAccountsService')
    def test_accounts_endpoint_returns_both_types(self, mock_service):
        """Endpoint returns income and expense accounts."""
        mock_service.get_income_items.return_value = [
            {'id': '1', 'name': 'CNC Machining', 'type': 'Service'}
        ]
        mock_service.get_expense_accounts.return_value = [
            {'id': '10', 'name': 'Supplies', 'type': 'Expense', 'sub_type': 'SuppliesMaterials'}
        ]

        self.client.login(username='admin', password='testpass')
        response = self.client.get('/api/qbo/accounts/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('income_items', data)
        self.assertIn('expense_accounts', data)

    def test_accounts_endpoint_requires_permission(self):
        """Endpoint requires can_manage_config."""
        worker = User.objects.create_user(username='worker', password='testpass')
        self.client.login(username='worker', password='testpass')
        response = self.client.get('/api/qbo/accounts/')
        self.assertEqual(response.status_code, 403)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_accounts -v2
```

Expected: ImportError — `QBOAccountsService` doesn't exist.

- [ ] **Step 3: Implement QBOAccountsService**

Add to `apps/qbo/services.py`:

```python
class QBOAccountsService:
    """Pulls Items and chart of accounts from QBO for category mapping."""

    @staticmethod
    def get_income_items():
        """Return Service and NonInventory Items from QBO as list of dicts.
        QBO invoices use Items (not accounts directly) for line items.
        Each Item is linked to an income account in QBO."""
        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        from quickbooks.objects.item import Item
        items = Item.filter(Active=True, qb=client)
        # Filter to Service and NonInventory types (suitable for invoice lines)
        return [
            {
                'id': str(i.Id),
                'name': i.Name,
                'type': getattr(i, 'Type', ''),
            }
            for i in items
            if getattr(i, 'Type', '') in ('Service', 'NonInventory')
        ]

    @staticmethod
    def get_expense_accounts():
        """Return expense + COGS accounts from QBO as list of dicts."""
        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')

        from quickbooks.objects.account import Account
        expense = Account.filter(AccountType='Expense', Active=True, qb=client)
        cogs = Account.filter(AccountType='Cost of Goods Sold', Active=True, qb=client)
        return [
            {
                'id': str(a.Id),
                'name': a.Name,
                'type': a.AccountType,
                'sub_type': getattr(a, 'AccountSubType', ''),
            }
            for a in list(expense) + list(cogs)
        ]
```

- [ ] **Step 4: Add the endpoint**

In `apps/qbo/views.py`, add:

```python
from apps.qbo.services import QBOAccountsService

@api_view(['GET'])
@permission_classes([IsAuthenticated, CanManageConfig])
def qbo_accounts(request):
    """Return QBO Items (for invoice lines) and expense accounts (for bills) for category mapping."""
    try:
        items = QBOAccountsService.get_income_items()
        expense = QBOAccountsService.get_expense_accounts()
        return Response({
            'income_items': items,
            'expense_accounts': expense,
        })
    except ValueError as e:
        return Response({'error': str(e)}, status=400)
```

In `apps/qbo/urls.py`, add:

```python
path('accounts/', views.qbo_accounts, name='qbo-accounts'),
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python manage.py test tests.test_qbo_accounts -v2
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/qbo/services.py apps/qbo/views.py apps/qbo/urls.py tests/test_qbo_accounts.py
git commit -m "feat: add QBO chart of accounts pull for category mapping"
```

---

### Task 6: API Endpoint for Updating Category Mappings

**Files:**
- Modify: `apps/api/templates_config/serializers.py`
- Modify: `apps/api/templates_config/views.py`
- Test: `tests/test_qbo_accounting_category.py` (add tests)

The existing AccountingCategory API already supports PATCH, but the QBO fields need to be writable by users with `can_manage_config`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_qbo_accounting_category.py`:

```python
from django.test import Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from apps.core.models import AccountingCategory

User = get_user_model()


class AccountingCategoryMappingAPITest(TestCase):
    """Test updating QBO account mappings via API."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username='admin', password='testpass')
        perm = Permission.objects.get(codename='can_manage_config', content_type__app_label='core')
        self.admin.user_permissions.add(perm)
        self.admin = User.objects.get(pk=self.admin.pk)

        self.category = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=False
        )

    def test_patch_qbo_income_account(self):
        """Can set QBO income account via PATCH."""
        self.client.login(username='admin', password='testpass')
        response = self.client.patch(
            f'/api/accounting-categories/{self.category.pk}/',
            data='{"qbo_item_id": "42"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.category.refresh_from_db()
        self.assertEqual(self.category.qbo_item_id, '42')

    def test_patch_qbo_expense_account(self):
        """Can set QBO expense account via PATCH."""
        self.client.login(username='admin', password='testpass')
        response = self.client.patch(
            f'/api/accounting-categories/{self.category.pk}/',
            data='{"qbo_expense_account_id": "99"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.category.refresh_from_db()
        self.assertEqual(self.category.qbo_expense_account_id, '99')

    def test_get_includes_qbo_fields(self):
        """GET response includes QBO mapping fields."""
        self.client.login(username='admin', password='testpass')
        response = self.client.get(f'/api/accounting-categories/{self.category.pk}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('qbo_item_id', data)
        self.assertIn('qbo_expense_account_id', data)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python manage.py test tests.test_qbo_accounting_category.AccountingCategoryMappingAPITest -v2
```

Expected: 404 (URL not found) or fields missing from serializer.

- [ ] **Step 3: Verify serializer includes QBO fields**

In `apps/api/templates_config/serializers.py`, confirm `AccountingCategorySerializer` includes the QBO fields. It should already from Task 3 Step 5, but verify:

```python
class AccountingCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingCategory
        fields = ['id', 'code', 'name', 'taxable', 'default_description', 'is_active',
                  'qbo_item_id', 'qbo_expense_account_id']
        read_only_fields = ['id']
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python manage.py test tests.test_qbo_accounting_category -v2
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/api/templates_config/serializers.py tests/test_qbo_accounting_category.py
git commit -m "feat: expose QBO account mapping fields on AccountingCategory API"
```

---

### Task 7: SPA — Accounting Category Mapping Component

**Files:**
- Create: `frontend/src/components/AccountingCategoryMapping.svelte`
- Modify: `frontend/src/routes/SettingsPage.svelte`

- [ ] **Step 1: Create the mapping component**

```svelte
<!-- frontend/src/components/AccountingCategoryMapping.svelte -->
<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';

  let categories = $state([]);
  let qboAccounts = $state(null);
  let loading = $state(true);
  let saving = $state(null);  // ID of category being saved
  let error = $state(null);
  let success = $state(null);

  async function loadData() {
    loading = true;
    error = null;
    try {
      const [catData, acctData] = await Promise.all([
        api.get('/api/accounting-categories/'),
        api.get('/api/qbo/accounts/').catch(() => null),
      ]);
      categories = catData.results || catData;
      qboAccounts = acctData;
    } catch (e) {
      if (e.status === 403) {
        categories = [];
        return;
      }
      error = e.message || 'Failed to load data';
    } finally {
      loading = false;
    }
  }

  async function saveMapping(category, field, value) {
    saving = category.id;
    error = null;
    success = null;
    try {
      await api.patch(`/api/accounting-categories/${category.id}/`, {
        [field]: value,
      });
      success = `Updated ${category.name}`;
      setTimeout(() => success = null, 3000);
    } catch (e) {
      error = e.message || 'Failed to save';
    } finally {
      saving = null;
    }
  }

  onMount(() => {
    loadData();
  });
</script>

{#if loading}
  <p>Loading accounting categories...</p>
{:else if categories.length === 0}
  <!-- No permission or no categories -->
{:else}
  <fieldset>
    <legend><strong>Accounting Category Mappings</strong></legend>

    {#if error}
      <p><strong>Error:</strong> {error}</p>
    {/if}
    {#if success}
      <p><strong>{success}</strong></p>
    {/if}

    {#if !qboAccounts}
      <p>Connect to QuickBooks to map categories to QBO accounts.</p>
    {:else}
      <table border="1">
        <thead>
          <tr>
            <th>Category</th>
            <th>Taxable</th>
            <th>QBO Item (Income)</th>
            <th>QBO Expense Account</th>
          </tr>
        </thead>
        <tbody>
          {#each categories as cat}
            <tr>
              <td><strong>{cat.name}</strong> ({cat.code})</td>
              <td>{cat.taxable ? 'Yes' : 'No'}</td>
              <td>
                <select
                  value={cat.qbo_item_id}
                  onchange={(e) => saveMapping(cat, 'qbo_item_id', e.target.value)}
                  disabled={saving === cat.id}
                >
                  <option value="">-- None --</option>
                  {#each qboAccounts.income_items as item}
                    <option value={item.id}>{item.name}</option>
                  {/each}
                </select>
              </td>
              <td>
                <select
                  value={cat.qbo_expense_account_id}
                  onchange={(e) => saveMapping(cat, 'qbo_expense_account_id', e.target.value)}
                  disabled={saving === cat.id}
                >
                  <option value="">-- None --</option>
                  {#each qboAccounts.expense_accounts as acct}
                    <option value={acct.id}>{acct.name}</option>
                  {/each}
                </select>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </fieldset>
{/if}
```

- [ ] **Step 2: Add to SettingsPage**

In `frontend/src/routes/SettingsPage.svelte`:

```svelte
<script>
  import QBOConnectionCard from '../components/QBOConnectionCard.svelte';
  import AccountingCategoryMapping from '../components/AccountingCategoryMapping.svelte';
</script>

<h2>Settings</h2>

<QBOConnectionCard />

<AccountingCategoryMapping />
```

- [ ] **Step 3: Verify manually**

Start both Django and Vite dev servers (both are needed — the SPA proxies API calls to Django):

```bash
./dev.sh
```

Navigate to `http://localhost:9000/#/settings`:
- Should show the QBO connection card (from foundation plan)
- Below it, accounting categories table
- If QBO is not connected, shows "Connect to QuickBooks to map categories"
- If QBO is connected, shows dropdowns with QBO accounts
- Selecting a dropdown auto-saves via PATCH

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AccountingCategoryMapping.svelte frontend/src/routes/SettingsPage.svelte
git commit -m "feat: add SPA accounting category to QBO account mapping UI"
```

---

### Task 8: Run Full Test Suite and Verify

**Files:** None — verification only.

- [ ] **Step 1: Run full test suite**

```bash
python manage.py test -v2
```

Expected: All tests pass.

- [ ] **Step 2: Verify no import issues**

```bash
python manage.py check
```

Expected: `System check identified no issues.`

- [ ] **Step 3: Verify API endpoints**

```bash
python manage.py runserver &
# Test the renamed endpoint
curl -s http://localhost:8000/api/accounting-categories/ | python -m json.tool
# Verify old endpoint returns 404
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/line-item-types/
```

Expected: New endpoint returns categories, old endpoint returns 404.

- [ ] **Step 4: Review what was built**

| Component | Location | Purpose |
|---|---|---|
| AccountingCategory model | `apps/core/models.py` | Renamed from LineItemType, with QBO fields |
| QBO fields | `qbo_item_id`, `qbo_expense_account_id` | Map to QBO Items (income) and accounts (expense) |
| FK rename | All models | `line_item_type` → `accounting_category` |
| API endpoint | `/api/accounting-categories/` | CRUD with QBO fields writable |
| QBO accounts pull | `/api/qbo/accounts/` | Chart of accounts for mapping UI |
| QBOAccountsService | `apps/qbo/services.py` | Pull income + expense accounts from QBO |
| Mapping UI | `AccountingCategoryMapping.svelte` | Dropdown mapping in SPA settings |

- [ ] **Step 5: Commit if any cleanup needed**

```bash
git status
git add apps/ tests/ frontend/ && git commit -m "chore: accounting category rename cleanup"
```
