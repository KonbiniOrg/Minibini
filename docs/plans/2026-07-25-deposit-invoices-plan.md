# Deposit Invoices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deposit invoices per `docs/plans/deposit-invoices-spec.md` — deposit-ness carried by `AccountingCategory.is_deposit`, paid deposits become unsplittable credit atoms in the invoice wizard, derived indicators on three surfaces, plus invoice add-line alignment with the estimate picker flow.

**Architecture:** No Invoice/InvoiceLineItem schema change. A line is a deposit line iff its AC has `is_deposit=True` and it carries no `source_type='deposit'` source row; deduction lines claim their deposit through the existing `InvoiceLineItemSource` unique-together `(source_type, source_pk)`. Board/list/overview indicators are all derived server-side.

**Tech Stack:** Django 5.2 + DRF, Svelte 5 (runes), Vitest, Playwright.

## Global Constraints

- Branch: `feature/deposits`. Commit per task. NEVER merge/push/PR (RM reviews first).
- TDD every task: failing test → verify failure → minimal code → pass → commit.
- `python manage.py test <module> --noinput` always; NEVER two Django test runs at once (hook-enforced); NEVER judge results via piped exit codes — read the `OK`/`FAILED` summary line.
- NEVER write to the dev DB (no `manage.py migrate`, no shell ORM writes, no loaddata). `makemigrations` is fine; tests use their own DB.
- Subagents run only their task's test modules; the full backend suite runs once in Task 16 **without `--keepdb`** (this plan adds migrations).
- Error contract: services raise `ValidationError({'field': ['msg']})` for field problems, `ValidationError('sentence')` otherwise; never emit `{'error': ...}`; DELETE returns 200+JSON.
- Never call `.delete()` on a line item directly — `LineItemService.delete_line_item_with_renumber` only.
- Status constants, not string literals (`Invoice.STATUS_PAID`).
- Frontend: no `alert()`; route errors through `triageError`; `<tr>` always inside `<tbody>`; user-visible text never says "wizard" (UI label is "Reconcile") or "blep".
- New Configuration key must be added to: `fixtures/unit_test_data.json`, `fixtures/playwright/seed.json`, and every test `setUp()` that exercises code reading it.

---

### Task 1: `AccountingCategory.is_deposit` + invariants + freeze

**Files:**
- Modify: `apps/core/models.py` (AccountingCategory, lines 291-312)
- Modify: `apps/core/services.py` (`ConfigurationService.update_accounting_category`, lines ~1150-1161)
- Modify: `apps/api/templates_config/serializers.py:84-91` (AccountingCategorySerializer)
- Create: `apps/core/migrations/0028_accountingcategory_is_deposit.py` (via makemigrations)
- Modify: `fixtures/unit_test_data.json` (AC rows 901/902; add deposit AC pk 903)
- Test: `tests/test_deposit_category.py`

**Interfaces:**
- Produces: `AccountingCategory.is_deposit: BooleanField(default=False)`; `AccountingCategory.is_referenced() -> bool`; model `clean()` enforcing `is_deposit → taxable=False`; update-service freeze of `is_deposit`/`taxable` once referenced; serializer exposes `is_deposit` (writable) and `is_referenced` (read-only). Later tasks rely on `cat.is_deposit` and the serializer fields.

- [ ] **Step 1: Write failing tests** in `tests/test_deposit_category.py`:

```python
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.models import AccountingCategory
from apps.core.services import ConfigurationService


class DepositCategoryInvariantTest(TestCase):
    def test_is_deposit_requires_non_taxable(self):
        cat = AccountingCategory(code='DEP', name='Deposits',
                                 taxable=True, is_deposit=True)
        with self.assertRaises(ValidationError) as ctx:
            cat.full_clean()
        self.assertIn('is_deposit', ctx.exception.message_dict)

    def test_non_taxable_deposit_category_validates(self):
        cat = AccountingCategory(code='DEP', name='Deposits',
                                 taxable=False, is_deposit=True)
        cat.full_clean()  # must not raise

    def test_is_referenced_false_when_unused(self):
        cat = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        self.assertFalse(cat.is_referenced())

    def test_is_referenced_true_via_rate_scheme(self):
        from decimal import Decimal
        from apps.jobs.models import RateScheme
        cat = AccountingCategory.objects.create(
            code='SVC2', name='Service2', taxable=True)
        RateScheme.objects.create(
            name='Hourly-dep', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hours',
            accounting_category=cat)
        self.assertTrue(cat.is_referenced())


class DepositCategoryFreezeTest(TestCase):
    def setUp(self):
        from decimal import Decimal
        from apps.jobs.models import RateScheme
        self.cat = AccountingCategory.objects.create(
            code='SVC3', name='Service3', taxable=True)
        RateScheme.objects.create(
            name='Hourly-frz', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hours',
            accounting_category=self.cat)

    def test_taxable_frozen_once_referenced(self):
        with self.assertRaises(ValidationError):
            ConfigurationService.update_accounting_category(
                self.cat.pk, taxable=False)

    def test_is_deposit_frozen_once_referenced(self):
        with self.assertRaises(ValidationError):
            ConfigurationService.update_accounting_category(
                self.cat.pk, is_deposit=True)

    def test_name_editable_while_referenced(self):
        updated = ConfigurationService.update_accounting_category(
            self.cat.pk, name='Shop Service')
        self.assertEqual(updated.name, 'Shop Service')

    def test_taxable_editable_while_unreferenced(self):
        free = AccountingCategory.objects.create(
            code='FREE', name='Free', taxable=True)
        updated = ConfigurationService.update_accounting_category(
            free.pk, taxable=False, is_deposit=True)
        self.assertTrue(updated.is_deposit)

    def test_unchanged_frozen_values_pass_through(self):
        # Sending the same values (whole-form PATCH) must not trip the freeze.
        updated = ConfigurationService.update_accounting_category(
            self.cat.pk, taxable=True, is_deposit=False, name='Still Fine')
        self.assertEqual(updated.name, 'Still Fine')
```

- [ ] **Step 2: Run to verify failure** (field/`is_referenced` don't exist):
`python manage.py test tests.test_deposit_category --noinput` → errors mentioning `is_deposit` / `is_referenced`.

- [ ] **Step 3: Implement.** In `apps/core/models.py`, inside `AccountingCategory`, after `is_active`:

```python
    is_deposit = models.BooleanField(default=False)  # Deposit-collection category
```

and add methods:

```python
    def clean(self):
        super().clean()
        if self.is_deposit and self.taxable:
            raise ValidationError({'is_deposit': [
                'A deposit category must be non-taxable.']})

    def is_referenced(self):
        """True if any row (line items, expenses, inventory, materials,
        rate schemes, fees) points at this category."""
        for rel in self._meta.related_objects:
            accessor = rel.get_accessor_name()
            if getattr(self, accessor).exists():
                return True
        return False
```

(`from django.core.exceptions import ValidationError` is already imported in models.py — verify, add if not.)

In `apps/core/services.py`, `update_accounting_category` — before applying changes:

```python
    FROZEN_WHEN_REFERENCED = ('taxable', 'is_deposit')

    @staticmethod
    def update_accounting_category(pk, **kwargs):
        cat = AccountingCategory.objects.get(pk=pk)
        frozen = [
            f for f in ConfigurationService.FROZEN_WHEN_REFERENCED
            if f in kwargs and kwargs[f] != getattr(cat, f)
        ]
        if frozen and cat.is_referenced():
            raise ValidationError(
                f"{' and '.join(frozen)} cannot change on a category that is "
                'in use. Retire this category and create a replacement instead.'
            )
        for field, value in kwargs.items():
            setattr(cat, field, value)
        cat.full_clean()
        cat.save()
        return cat
```

(Adapt to the existing method body — keep its current shape, add the freeze guard before the setattr loop. Read the real method first; it may whitelist fields.)

In `apps/api/templates_config/serializers.py`, extend fields:

```python
    is_referenced = serializers.SerializerMethodField()

    class Meta:
        model = AccountingCategory
        fields = ['id', 'code', 'name', 'taxable', 'is_deposit',
                  'default_description', 'is_active',
                  'qbo_item_id', 'qbo_expense_account_id', 'is_referenced']
        read_only_fields = ['id', 'is_referenced']

    def get_is_referenced(self, obj):
        return obj.is_referenced()
```

- [ ] **Step 4: Migration + fixtures.** `python manage.py makemigrations core` (expect `0028_accountingcategory_is_deposit`). In `fixtures/unit_test_data.json` add `"is_deposit": false` to AC rows 901/902 and append a deposit category + config key (config row used from Task 2 onward):

```json
{"model": "core.accountingcategory", "pk": 903,
 "fields": {"code": "DEP", "name": "Customer Deposits", "taxable": false,
            "default_description": "", "is_active": true, "is_deposit": true,
            "qbo_item_id": "", "qbo_expense_account_id": ""}},
{"model": "core.configuration", "pk": "default_deposit_accounting_category",
 "fields": {"value": "903"}}
```

(Match the exact field set of the neighboring AC rows in the fixture.)

- [ ] **Step 5: Run to verify pass:**
`python manage.py test tests.test_deposit_category tests.test_accounting_category tests.test_config_service_crud tests.test_api_templates_config --noinput` → read summary line, expect `OK`.

- [ ] **Step 6: Commit** `feat: AccountingCategory.is_deposit with non-taxable invariant and used-category freeze`

---

### Task 2: `default_deposit_accounting_category` settings key (backend)

**Files:**
- Modify: `apps/api/templates_config/views.py` (`settings_view` PATCH branch, next to the `default_material_accounting_category` block at :252)
- Test: `tests/test_deposit_settings_key.py`

**Interfaces:**
- Produces: PATCH `/api/settings/` validates the key — blank clears; non-blank must be an int pk of an **active, `is_deposit=True`** category, else 400 `{'default_deposit_accounting_category': '<msg>'}`. GET exposes it as a flat string key (existing behavior, no work).

- [ ] **Step 1: Failing tests** in `tests/test_deposit_settings_key.py` (mirror `test_api_templates_config` style):

```python
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.models import AccountingCategory, Configuration, User


class DepositSettingsKeyTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cfg', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_config'))
        self.client = APIClient()
        self.client.login(username='cfg', password='pw')
        self.dep = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        self.std = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=True)

    def _patch(self, value):
        return self.client.patch('/api/settings/',
            {'default_deposit_accounting_category': value}, format='json')

    def test_roundtrip(self):
        resp = self._patch(str(self.dep.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Configuration.objects.get(
                key='default_deposit_accounting_category').value,
            str(self.dep.pk))

    def test_rejects_non_deposit_category(self):
        resp = self._patch(str(self.std.pk))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('default_deposit_accounting_category', resp.json())

    def test_rejects_inactive(self):
        self.dep.is_active = False
        self.dep.save()
        self.assertEqual(self._patch(str(self.dep.pk)).status_code, 400)

    def test_rejects_unknown(self):
        self.assertEqual(self._patch('999999').status_code, 400)

    def test_blank_clears(self):
        self._patch(str(self.dep.pk))
        resp = self._patch('')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            Configuration.objects.get(
                key='default_deposit_accounting_category').value, '')
```

- [ ] **Step 2: Verify failure:** `python manage.py test tests.test_deposit_settings_key --noinput` → `test_rejects_non_deposit_category` FAILS (no validation yet; others may pass via the generic set path).

- [ ] **Step 3: Implement** in `settings_view` PATCH branch, immediately after the material block:

```python
    if 'default_deposit_accounting_category' in request.data:
        raw = request.data['default_deposit_accounting_category']
        raw = '' if raw is None else str(raw).strip()
        if raw != '':
            try:
                pk = int(raw)
            except (TypeError, ValueError):
                return Response(
                    {'default_deposit_accounting_category': 'must be a category id'},
                    status=400)
            if not AccountingCategory.objects.filter(
                    pk=pk, is_active=True, is_deposit=True).exists():
                return Response(
                    {'default_deposit_accounting_category':
                     'unknown, inactive, or not a deposit category'},
                    status=400)
```

- [ ] **Step 4: Verify pass:** `python manage.py test tests.test_deposit_settings_key --noinput` → `OK`.

- [ ] **Step 5: Commit** `feat: default_deposit_accounting_category settings key with deposit-category validation`

---

### Task 3: `SOURCE_DEPOSIT` + deposit-line helpers

**Files:**
- Modify: `apps/invoicing/models.py` (InvoiceLineItemSource :175-222, InvoiceLineItem :143-172)
- Create: migration via makemigrations (choices change → AlterField, no schema change)
- Test: `tests/test_deposit_line_helpers.py`

**Interfaces:**
- Produces: `InvoiceLineItemSource.SOURCE_DEPOSIT = 'deposit'` (+ choices entry + `resolve()` branch returning the deposit `InvoiceLineItem`); `InvoiceLineItem.is_deposit_line: bool` property; `InvoiceLineItem.is_deposit_deduction: bool` property. Everything later derives deposit-ness from these two properties.

- [ ] **Step 1: Failing tests** in `tests/test_deposit_line_helpers.py`:

```python
from decimal import Decimal
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.invoicing.models import (
    Invoice, InvoiceLineItem, InvoiceLineItemSource,
)
from apps.jobs.models import Job


class DepositLineHelperTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.dep_cat = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        self.std_cat = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=True)
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com',
            mobile_number='555')
        self.job = Job.objects.create(
            contact=self.contact, job_number='JOB-2026-0001',
            status=Job.STATUS_APPROVED)
        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT)

    def _line(self, cat, **kw):
        return InvoiceLineItem.objects.create(
            invoice=self.invoice, description='x', qty=Decimal('1'),
            price=Decimal('500.00'), accounting_category=cat, **kw)

    def test_deposit_line_property(self):
        li = self._line(self.dep_cat)
        self.assertTrue(li.is_deposit_line)
        self.assertFalse(li.is_deposit_deduction)

    def test_standard_line_is_not_deposit(self):
        li = self._line(self.std_cat)
        self.assertFalse(li.is_deposit_line)

    def test_deduction_is_not_a_deposit_line(self):
        dep = self._line(self.dep_cat)
        other = Invoice.objects.create(job=self.job,
                                       status=Invoice.STATUS_DRAFT)
        # A second draft on the same job is blocked by clean(); use a
        # second job if that applies — read Invoice.clean() first.
        ded = InvoiceLineItem.objects.create(
            invoice=other, description='Less deposit', qty=Decimal('1'),
            price=Decimal('-500.00'), accounting_category=self.dep_cat)
        InvoiceLineItemSource.objects.create(
            invoice_line_item=ded,
            source_type=InvoiceLineItemSource.SOURCE_DEPOSIT,
            source_pk=dep.pk)
        self.assertTrue(ded.is_deposit_deduction)
        self.assertFalse(ded.is_deposit_line)
        self.assertEqual(
            ded.sources.get(
                source_type=InvoiceLineItemSource.SOURCE_DEPOSIT
            ).resolve(), dep)

    def test_unique_claim_on_deposit(self):
        dep = self._line(self.dep_cat)
        ded = self._line(self.std_cat)
        InvoiceLineItemSource.objects.create(
            invoice_line_item=ded,
            source_type=InvoiceLineItemSource.SOURCE_DEPOSIT,
            source_pk=dep.pk)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                InvoiceLineItemSource.objects.create(
                    invoice_line_item=ded,
                    source_type=InvoiceLineItemSource.SOURCE_DEPOSIT,
                    source_pk=dep.pk)
```

Note for the implementer: `Invoice.clean()` enforces single-draft-per-job — if the second draft in `test_deduction_is_not_a_deposit_line` trips it, create the deduction's invoice on a second Job (same pattern as `setUp`'s job with `job_number='JOB-2026-0002'`).

- [ ] **Step 2: Verify failure:** `python manage.py test tests.test_deposit_line_helpers --noinput` → AttributeError on `SOURCE_DEPOSIT` / `is_deposit_line`.

- [ ] **Step 3: Implement** in `apps/invoicing/models.py`. On `InvoiceLineItemSource`:

```python
    SOURCE_DEPOSIT = 'deposit'
    SOURCE_TYPE_CHOICES = [
        (SOURCE_MATERIAL, 'Material'), (SOURCE_TASK, 'Task'),
        (SOURCE_EXPENSE, 'Expense'), (SOURCE_FEE, 'Fee'),
        (SOURCE_DEPOSIT, 'Deposit'),
    ]
```

and in `resolve()` add the branch (mirroring the existing ones, null-safe):

```python
        if self.source_type == self.SOURCE_DEPOSIT:
            return InvoiceLineItem.objects.filter(pk=self.source_pk).first()
```

On `InvoiceLineItem`:

```python
    @property
    def is_deposit_line(self):
        """A deposit charge: deposit-category line that is not a deduction."""
        return bool(
            self.accounting_category_id
            and self.accounting_category.is_deposit
            and not self.sources.filter(
                source_type=InvoiceLineItemSource.SOURCE_DEPOSIT).exists()
        )

    @property
    def is_deposit_deduction(self):
        return self.sources.filter(
            source_type=InvoiceLineItemSource.SOURCE_DEPOSIT).exists()
```

(`InvoiceLineItemSource` is defined after `InvoiceLineItem` in the module — reference it lazily inside the property body as written; Python resolves at call time.)

Run `python manage.py makemigrations invoicing` (choices-only AlterField).

- [ ] **Step 4: Verify pass:** `python manage.py test tests.test_deposit_line_helpers tests.test_invoice_line_item_source --noinput` → `OK`.

- [ ] **Step 5: Commit** `feat: deposit source type and deposit-line/deduction helpers`

---

### Task 4: deposit line creation path (`deposit=true`)

**Files:**
- Modify: `apps/invoicing/services.py` (`InvoiceService.add_line_item` :21-34; new `_resolve_deposit_category`)
- Test: `tests/test_deposit_line_creation.py`

**Interfaces:**
- Consumes: `AccountingCategory.is_deposit` (Task 1), fixture config key.
- Produces: `InvoiceService.add_line_item(invoice_pk, deposit=False, **kwargs)` — when `deposit` is truthy, stamps the configured default deposit AC server-side (coaching `ValidationError({'accounting_category': [...]})` when unset/invalid). The API `POST /api/invoices/{id}/line-items/` accepts `deposit: true` because `LineItemMixin` forwards `request.data` as kwargs.

- [ ] **Step 1: Failing tests** in `tests/test_deposit_line_creation.py`:

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceService
from apps.jobs.models import Job


class DepositLineCreationTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.dep_cat = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com',
            mobile_number='555')
        self.job = Job.objects.create(
            contact=contact, job_number='JOB-2026-0001',
            status=Job.STATUS_APPROVED)
        self.invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT)
        Configuration.objects.create(
            key='default_deposit_accounting_category',
            value=str(self.dep_cat.pk))

    def test_deposit_flag_stamps_default_category(self):
        li = InvoiceService.add_line_item(
            self.invoice.pk, deposit=True,
            description='Deposit on JOB-2026-0001',
            qty='1', price='5000.00', units='none')
        self.assertEqual(li.accounting_category_id, self.dep_cat.pk)
        self.assertTrue(li.is_deposit_line)

    def test_unset_key_raises_coaching_error(self):
        Configuration.objects.filter(
            key='default_deposit_accounting_category').delete()
        with self.assertRaises(ValidationError) as ctx:
            InvoiceService.add_line_item(
                self.invoice.pk, deposit=True, description='Deposit',
                qty='1', price='100.00', units='none')
        self.assertIn('accounting_category', ctx.exception.message_dict)
        self.assertIn('default_deposit_accounting_category',
                      str(ctx.exception))

    def test_dangling_key_raises(self):
        Configuration.objects.filter(
            key='default_deposit_accounting_category').update(value='999999')
        with self.assertRaises(ValidationError):
            InvoiceService.add_line_item(
                self.invoice.pk, deposit=True, description='Deposit',
                qty='1', price='100.00', units='none')

    def test_manual_line_with_deposit_category_still_works(self):
        # Hand-assigning the deposit AC (no flag) is equally a deposit line.
        li = InvoiceService.add_line_item(
            self.invoice.pk, description='Deposit',
            qty='1', price='100.00', units='none',
            accounting_category=self.dep_cat.pk)
        self.assertTrue(li.is_deposit_line)
```

- [ ] **Step 2: Verify failure:** `python manage.py test tests.test_deposit_line_creation --noinput` → TypeError (`deposit` unexpected) or category unset.

- [ ] **Step 3: Implement** in `apps/invoicing/services.py`:

```python
    @staticmethod
    def _resolve_deposit_category():
        """The configured default deposit AC, or a coaching error."""
        from apps.core.models import AccountingCategory, Configuration
        cfg = Configuration.objects.filter(
            key='default_deposit_accounting_category').first()
        pk = (cfg.value or '').strip() if cfg else ''
        if not pk:
            raise ValidationError({'accounting_category': [
                'No default deposit accounting category is configured. '
                'Set the default_deposit_accounting_category setting '
                'in Settings.']})
        try:
            return AccountingCategory.objects.get(
                pk=pk, is_active=True, is_deposit=True)
        except (AccountingCategory.DoesNotExist, ValueError, TypeError):
            raise ValidationError({'accounting_category': [
                f'The configured default deposit accounting category '
                f'({pk!r}) does not exist, is inactive, or is not a '
                f'deposit category.']})
```

and change `add_line_item`'s signature/head:

```python
    @staticmethod
    def add_line_item(invoice_pk, deposit=False, **kwargs):
        """Add a manual line item to a draft invoice. deposit=True stamps
        the configured default deposit accounting category."""
        try:
            invoice = Invoice.objects.get(pk=invoice_pk)
        except Invoice.DoesNotExist:
            raise NotFoundError(f'Invoice {invoice_pk} not found')
        InvoiceService._validate_draft(invoice)
        if deposit:
            kwargs['accounting_category'] = (
                InvoiceService._resolve_deposit_category())
        from apps.core.services import LineItemService
        kwargs = LineItemService.normalize_fk_kwargs(InvoiceLineItem, kwargs)
        li = InvoiceLineItem(invoice=invoice, **kwargs)
        li.full_clean()
        LineItemService.save_line_item(li)
        return li
```

Check `LineItemMixin.line_items` (apps/api/mixins.py:201-227): if it filters/validates kwargs before calling `add_line_item(**data)`, ensure `deposit` passes through (it forwards `request.data` — verify, adjust only if it strips unknown keys).

- [ ] **Step 4: Verify pass:** `python manage.py test tests.test_deposit_line_creation tests.test_api_line_item_mixin --noinput` → `OK`.

- [ ] **Step 5: Commit** `feat: deposit line creation with server-stamped default category`

---

### Task 5: wizard pool deposit credits + pull + locks

**Files:**
- Modify: `apps/invoicing/services.py` (`InvoiceWizardService`: `get_source_pool` :540-767, `_resolve_atom` :873, `_atom_source_type` :888, `_assert_atom_billable` :854, `_atom_qty_and_price` :937, `_atom_description` :926, `_atom_category` :916, `_atom_detail` :948; override `add_atoms_to_new_line_item`/`add_atoms_to_line_item`; guard in `update_line_item` :64-80)
- Test: `tests/test_deposit_wizard.py`

**Interfaces:**
- Consumes: Task 3 helpers/`SOURCE_DEPOSIT`; `BaseWizardService` (`apps/core/wizard.py`) hooks: `_create_source`, `_atom_computed_amount`, `add_atoms_to_new_line_item(container, atoms)`.
- Produces: pool gains a group `{'task_id': None, 'name': 'Deposit credits', 'has_billable_atoms': True, 'atoms': [...]}` with atoms `{'type': 'deposit', 'id': <deposit line pk>, ...}`; `POST line-items-from-atoms` with `{'atoms': [{'type': 'deposit', 'id': N}]}` creates the locked deduction line; deduction `qty`/`price`/`accounting_category` edits rejected.

- [ ] **Step 1: Failing tests** in `tests/test_deposit_wizard.py`. Reuse the standard wizard preamble (see `tests/test_invoice_wizard_service.py:106-130`):

```python
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.invoicing.models import (
    Invoice, InvoiceLineItem, InvoiceLineItemSource,
)
from apps.invoicing.services import InvoiceService, InvoiceWizardService
from apps.jobs.models import Job


def _deposit_group(pool):
    return next((g for g in pool['tasks']
                 if g['name'] == 'Deposit credits'), None)


class DepositCreditPoolTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.dep_cat = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        self.std_cat = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=True)
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com',
            mobile_number='555')
        self.job = Job.objects.create(
            contact=contact, job_number='JOB-2026-0001',
            status=Job.STATUS_APPROVED)
        # Paid deposit invoice with one deposit line.
        self.dep_invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_OPEN,
            invoice_number='INV-1042')
        self.dep_line = InvoiceLineItem.objects.create(
            invoice=self.dep_invoice, description='Deposit',
            qty=Decimal('1'), price=Decimal('5000.00'),
            accounting_category=self.dep_cat)
        Invoice.objects.filter(pk=self.dep_invoice.pk).update(
            status=Invoice.STATUS_PAID)
        self.dep_invoice.refresh_from_db()
        # The draft being composed.
        self.draft = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT)

    def test_paid_deposit_appears_as_available_credit(self):
        pool = InvoiceWizardService.get_source_pool(self.draft)
        group = _deposit_group(pool)
        self.assertIsNotNone(group)
        atom = group['atoms'][0]
        self.assertEqual(atom['type'], 'deposit')
        self.assertEqual(atom['id'], self.dep_line.pk)
        self.assertEqual(atom['state'], 'available')
        self.assertEqual(Decimal(str(atom['amount'])),
                         Decimal('-5000.00'))

    def test_unpaid_deposit_not_offered(self):
        Invoice.objects.filter(pk=self.dep_invoice.pk).update(
            status=Invoice.STATUS_OPEN)
        pool = InvoiceWizardService.get_source_pool(self.draft)
        self.assertIsNone(_deposit_group(pool))

    def test_other_jobs_deposits_not_offered(self):
        contact2 = Contact.objects.create(
            first_name='K', last_name='E', email='k@e.com',
            mobile_number='556')
        job2 = Job.objects.create(
            contact=contact2, job_number='JOB-2026-0002',
            status=Job.STATUS_APPROVED)
        draft2 = Invoice.objects.create(job=job2,
                                        status=Invoice.STATUS_DRAFT)
        pool = InvoiceWizardService.get_source_pool(draft2)
        self.assertIsNone(_deposit_group(pool))

    def test_pull_creates_locked_negative_deduction(self):
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            self.draft, [{'type': 'deposit', 'id': self.dep_line.pk}])
        self.assertEqual(li.qty, Decimal('1'))
        self.assertEqual(li.price, Decimal('-5000.00'))
        self.assertEqual(li.accounting_category_id, self.dep_cat.pk)
        self.assertIn('INV-1042', li.description)
        self.assertTrue(li.is_deposit_deduction)
        # And it is claimed in the pool now.
        pool = InvoiceWizardService.get_source_pool(self.draft)
        atom = _deposit_group(pool)['atoms'][0]
        self.assertEqual(atom['state'], 'claimed_by_current')

    def test_claimed_deposit_shows_claimed_by_other(self):
        InvoiceWizardService.add_atoms_to_new_line_item(
            self.draft, [{'type': 'deposit', 'id': self.dep_line.pk}])
        Invoice.objects.filter(pk=self.draft.pk).update(
            status=Invoice.STATUS_OPEN)
        contactx = Contact.objects.filter(email='j@d.com').first()
        draft2 = Invoice.objects.create(job=self.job,
                                        status=Invoice.STATUS_DRAFT)
        pool = InvoiceWizardService.get_source_pool(draft2)
        atom = _deposit_group(pool)['atoms'][0]
        self.assertEqual(atom['state'], 'claimed_by_other')

    def test_deleting_deduction_releases_claim(self):
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            self.draft, [{'type': 'deposit', 'id': self.dep_line.pk}])
        InvoiceService.delete_line_item(li.pk)
        pool = InvoiceWizardService.get_source_pool(self.draft)
        self.assertEqual(_deposit_group(pool)['atoms'][0]['state'],
                         'available')

    def test_deposit_atom_cannot_be_bundled(self):
        with self.assertRaises(ValidationError):
            InvoiceWizardService.add_atoms_to_new_line_item(
                self.draft, [
                    {'type': 'deposit', 'id': self.dep_line.pk},
                    {'type': 'deposit', 'id': self.dep_line.pk},
                ])

    def test_deduction_amount_is_locked(self):
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            self.draft, [{'type': 'deposit', 'id': self.dep_line.pk}])
        with self.assertRaises(ValidationError):
            InvoiceService.update_line_item(li.pk, price='-1.00')
        with self.assertRaises(ValidationError):
            InvoiceService.update_line_item(li.pk, qty='2')
        updated = InvoiceService.update_line_item(
            li.pk, description='Less deposit (thanks!)')
        self.assertEqual(updated.description, 'Less deposit (thanks!)')

    def test_deposit_lines_of_current_draft_not_offered(self):
        # A deposit line on the draft being composed is not a credit.
        InvoiceLineItem.objects.create(
            invoice=self.draft, description='Deposit', qty=Decimal('1'),
            price=Decimal('100.00'), accounting_category=self.dep_cat)
        pool = InvoiceWizardService.get_source_pool(self.draft)
        group = _deposit_group(pool)
        ids = [a['id'] for a in (group['atoms'] if group else [])]
        self.assertNotIn(
            self.draft.invoicelineitem_set.get(price=Decimal('100.00')).pk,
            ids)
```

- [ ] **Step 2: Verify failure:** `python manage.py test tests.test_deposit_wizard --noinput` → no `Deposit credits` group.

- [ ] **Step 3: Implement** in `InvoiceWizardService`:

**(a) Pool group** — in `get_source_pool`, after the Fees group (:760-765), before `return`:

```python
        # Deposit credits — deposit lines on PAID invoices of this job.
        # (Deduction lines carry a 'deposit' source row and are excluded;
        # paid-only means you never deduct money not actually held.)
        deposit_lines = (
            InvoiceLineItem.objects
            .filter(invoice__job=job,
                    invoice__status=Invoice.STATUS_PAID,
                    accounting_category__is_deposit=True)
            .exclude(sources__source_type=InvoiceLineItemSource.SOURCE_DEPOSIT)
            .select_related('invoice')
            .order_by('invoice__sent_date', 'pk')
        )
        deposit_atoms = []
        for li in deposit_lines:
            key = (InvoiceLineItemSource.SOURCE_DEPOSIT, li.pk)
            state_info = claims.get(key) or default_state
            deposit_atoms.append({
                'type': 'deposit',
                'id': li.pk,
                'description': f'Deposit credit — {li.invoice.display_number}',
                'sub_info': li.description,
                'qty': Decimal('1'),
                'rate': -li.total_amount,
                'units': 'none',
                'amount': -li.total_amount,
                **state_info,
            })
        if deposit_atoms:
            task_list.append({
                'task_id': None,
                'name': 'Deposit credits',
                'has_billable_atoms': any(
                    a['state'] == 'available' for a in deposit_atoms),
                'atoms': deposit_atoms,
            })
```

(Match the exact local names in the method: `job`, `claims`, `default_state`, `task_list` — read the surrounding code and use its names. `total_amount` is the BaseLineItem qty×price property; verify its exact name in `apps/core/models.py` and use that.)

**(b) Hooks** — extend each per its existing dispatch style:

```python
    # _resolve_atom: add branch
        if atom_type == 'deposit':
            try:
                return InvoiceLineItem.objects.select_related(
                    'invoice', 'accounting_category').get(pk=atom_id)
            except InvoiceLineItem.DoesNotExist:
                raise ValidationError(f'Deposit line {atom_id} not found')

    # _atom_source_type: add branch
        if isinstance(atom_instance, InvoiceLineItem):
            return InvoiceLineItemSource.SOURCE_DEPOSIT

    # _assert_atom_billable: add branch (before super/other checks)
        if isinstance(instance, InvoiceLineItem):
            if not (instance.accounting_category_id
                    and instance.accounting_category.is_deposit):
                raise ValidationError('Not a deposit line.')
            if instance.invoice.status != Invoice.STATUS_PAID:
                raise ValidationError(
                    'A deposit can only be deducted once its invoice is paid.')
            return

    # _atom_category
        if isinstance(atom_instance, InvoiceLineItem):
            return atom_instance.accounting_category

    # _atom_description
        if isinstance(atom_instance, InvoiceLineItem):
            return f'Less deposit ({atom_instance.invoice.display_number})'

    # _atom_qty_and_price
        if isinstance(atom_instance, InvoiceLineItem):
            return Decimal('1'), total_price

    # _atom_computed_amount (override in InvoiceWizardService if the base
    # helper doesn't dispatch; deposit credit is the negated line total)
        if isinstance(atom_instance, InvoiceLineItem):
            return -atom_instance.total_amount
```

Also verify `_atom_units` (:904) returns `'none'` for InvoiceLineItem, and `_atom_detail` (:948) has a deposit branch mirroring the fee branch.

**(c) Same-job + no-bundling guard** — override in `InvoiceWizardService`:

```python
    @classmethod
    def add_atoms_to_new_line_item(cls, container, atoms):
        cls._assert_deposit_atom_rules(container, atoms)
        return super().add_atoms_to_new_line_item(container, atoms)

    @classmethod
    def add_atoms_to_line_item(cls, line_item, atoms):
        cls._assert_deposit_atom_rules(line_item.invoice, atoms,
                                       appending_to=line_item)
        return super().add_atoms_to_line_item(line_item, atoms)

    @classmethod
    def _assert_deposit_atom_rules(cls, invoice, atoms, appending_to=None):
        deposit_refs = [a for a in atoms
                        if a.get('type') == 'deposit']
        if not deposit_refs:
            if appending_to is not None and appending_to.is_deposit_deduction:
                raise ValidationError(
                    'A deposit deduction line cannot take other atoms.')
            return
        if len(atoms) > 1 or appending_to is not None:
            raise ValidationError(
                'A deposit credit must be pulled as its own line.')
        dep = InvoiceLineItem.objects.filter(
            pk=deposit_refs[0].get('id')).select_related('invoice').first()
        if dep is not None and dep.invoice.job_id != invoice.job_id:
            raise ValidationError(
                'A deposit can only be deducted on its own job.')
```

**(d) Deduction lock** — in `InvoiceService.update_line_item` (:64-80), after loading the line and validating draft:

```python
        if line_item.is_deposit_deduction:
            locked = {'qty', 'price', 'accounting_category',
                      'accounting_category_id', 'inventory_item'}
            touched = locked & set(kwargs.keys())
            if touched:
                raise ValidationError(
                    'A deposit deduction is locked to its deposit — only '
                    'the description can be edited.')
```

- [ ] **Step 4: Verify pass:**
`python manage.py test tests.test_deposit_wizard tests.test_invoice_wizard_service tests.test_invoice_wizard_api tests.test_invoice_apply_everything --noinput` → `OK`. (`apply_everything`/`send_all_atoms` walk `state == 'available'` atoms — the deposit group flows through them by construction; if a test there assumes only task groups, fix the assertion, not the feature. But confirm seeding deliberately: seed/send-all pulling a deposit credit automatically is CORRECT per spec — it is an available atom.)

- [ ] **Step 5: Commit** `feat: deposit credits in the invoice wizard pool with locked whole-amount deduction`

---

### Task 6: serializer exposure (per-line + invoice-level + summary)

**Files:**
- Modify: `apps/api/invoicing/serializers.py` (`InvoiceLineItemSerializer` :53-84, `InvoiceSerializer` :87-179, `InvoiceSummarySerializer` :182-243)
- Modify: `apps/api/invoicing/views.py` (`get_queryset` :86-141 — summary annotation)
- Test: `tests/test_deposit_serializers.py`

**Interfaces:**
- Produces: `InvoiceLineItemSerializer.is_deposit` (bool, per line); `InvoiceSerializer.is_deposit` (bool, invoice-level, from prefetched lines); `InvoiceSummarySerializer.is_deposit` (bool, from `has_deposit` annotation). Frontend tasks 12–14 consume `inv.is_deposit` / `li.is_deposit`.

- [ ] **Step 1: Failing tests** in `tests/test_deposit_serializers.py` (API-level, mirroring `tests/test_api_invoice_list.py` setup style — `can_manage_financials` user, APIClient login):

```python
from decimal import Decimal
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.invoicing.models import (
    Invoice, InvoiceLineItem, InvoiceLineItemSource,
)
from apps.jobs.models import Job


class DepositSerializerTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.user = User.objects.create_user(username='fin', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials'))
        self.client = APIClient()
        self.client.login(username='fin', password='pw')
        self.dep_cat = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        self.std_cat = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=True)
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com',
            mobile_number='555')
        self.job = Job.objects.create(
            contact=contact, job_number='JOB-2026-0001',
            status=Job.STATUS_APPROVED)
        self.deposit_inv = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_DRAFT)
        self.dep_line = InvoiceLineItem.objects.create(
            invoice=self.deposit_inv, description='Deposit',
            qty=Decimal('1'), price=Decimal('5000.00'),
            accounting_category=self.dep_cat)

    def test_detail_exposes_line_and_invoice_flags(self):
        data = self.client.get(
            f'/api/invoices/{self.deposit_inv.pk}/').json()
        self.assertTrue(data['is_deposit'])
        line = next(l for l in data['line_items']
                    if l['line_item_id'] == self.dep_line.pk)
        self.assertTrue(line['is_deposit'])

    def test_summary_list_exposes_invoice_flag(self):
        data = self.client.get('/api/invoices/?summary=true').json()
        rows = data['results'] if isinstance(data, dict) else data
        row = next(r for r in rows
                   if r['invoice_id'] == self.deposit_inv.pk)
        self.assertTrue(row['is_deposit'])

    def test_deduction_does_not_mark_invoice_as_deposit(self):
        other = Invoice.objects.create(job=self.job,
                                       status=Invoice.STATUS_DRAFT)
        # single-draft-per-job guard: read Invoice.clean(); if it blocks,
        # promote self.deposit_inv to STATUS_OPEN via queryset update first.
        Invoice.objects.filter(pk=self.deposit_inv.pk).update(
            status=Invoice.STATUS_PAID)
        ded = InvoiceLineItem.objects.create(
            invoice=other, description='Less deposit', qty=Decimal('1'),
            price=Decimal('-5000.00'), accounting_category=self.dep_cat)
        InvoiceLineItemSource.objects.create(
            invoice_line_item=ded,
            source_type=InvoiceLineItemSource.SOURCE_DEPOSIT,
            source_pk=self.dep_line.pk)
        data = self.client.get(f'/api/invoices/{other.pk}/').json()
        self.assertFalse(data['is_deposit'])
```

(Note: create `other` BEFORE flipping `deposit_inv` to paid if the single-draft guard fires on create — order shown handles it; adjust per `Invoice.clean()`.)

- [ ] **Step 2: Verify failure:** `python manage.py test tests.test_deposit_serializers --noinput` → KeyError `is_deposit`.

- [ ] **Step 3: Implement.**

`InvoiceLineItemSerializer`: add `'is_deposit'` to fields and:

```python
    is_deposit = serializers.SerializerMethodField()

    def get_is_deposit(self, obj):
        return obj.is_deposit_line
```

`InvoiceSerializer`: add `'is_deposit'` to fields and:

```python
    is_deposit = serializers.SerializerMethodField()

    def get_is_deposit(self, obj):
        return any(li.is_deposit_line
                   for li in obj.invoicelineitem_set.all())
```

`InvoiceSummarySerializer`: add `'is_deposit'` to fields and:

```python
    is_deposit = serializers.BooleanField(
        source='has_deposit', read_only=True, default=False)
```

`InvoiceViewSet.get_queryset` — in the summary branch, add:

```python
        from django.db.models import Exists, OuterRef
        deposit_line = (
            InvoiceLineItem.objects
            .filter(invoice=OuterRef('pk'),
                    accounting_category__is_deposit=True)
            .exclude(sources__source_type=InvoiceLineItemSource.SOURCE_DEPOSIT)
        )
        qs = qs.annotate(has_deposit=Exists(deposit_line))
```

To avoid N+1 on the detail path, extend the non-summary queryset's prefetches with `'invoicelineitem_set__sources'` and `select_related`/`prefetch_related` of `'invoicelineitem_set__accounting_category'` (match the existing prefetch style in `get_queryset`).

- [ ] **Step 4: Verify pass:** `python manage.py test tests.test_deposit_serializers tests.test_api_invoice_list tests.test_api_invoicing --noinput` → `OK`.

- [ ] **Step 5: Commit** `feat: expose derived deposit flags on invoice serializers`

---

### Task 7: board `deposit_state`

**Files:**
- Modify: `apps/jobs/services.py` (`BoardService`: `_serialize_job` :2143-2163 and its call sites in the four column payload builders)
- Test: `tests/test_deposit_board_state.py`

**Interfaces:**
- Consumes: Task 3 (`SOURCE_DEPOSIT`, deposit-line query shape).
- Produces: every board job dict gains `deposit_state`: `'requested'` (a sent-unpaid deposit invoice exists: status open/partly-paid), `'paid'` (a paid, unclaimed-by-live-invoice deposit line exists and nothing is requested), or `None`. `BoardService._deposit_states(job_ids) -> dict[int, str]` bulk helper.

- [ ] **Step 1: Failing tests** in `tests/test_deposit_board_state.py`:

```python
from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.invoicing.models import (
    Invoice, InvoiceLineItem, InvoiceLineItemSource,
)
from apps.jobs.models import Job
from apps.jobs.services import BoardService


class DepositBoardStateTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.dep_cat = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com',
            mobile_number='555')
        self.job = Job.objects.create(
            contact=contact, job_number='JOB-2026-0001',
            status=Job.STATUS_IN_PROGRESS)

    def _deposit_invoice(self, status):
        inv = Invoice.objects.create(job=self.job,
                                     status=Invoice.STATUS_DRAFT)
        li = InvoiceLineItem.objects.create(
            invoice=inv, description='Deposit', qty=Decimal('1'),
            price=Decimal('5000.00'), accounting_category=self.dep_cat)
        Invoice.objects.filter(pk=inv.pk).update(status=status)
        return inv, li

    def test_no_deposit_none(self):
        self.assertEqual(
            BoardService._deposit_states([self.job.pk]), {})

    def test_draft_deposit_none(self):
        self._deposit_invoice(Invoice.STATUS_DRAFT)
        self.assertEqual(
            BoardService._deposit_states([self.job.pk]), {})

    def test_sent_unpaid_is_requested(self):
        self._deposit_invoice(Invoice.STATUS_OPEN)
        self.assertEqual(
            BoardService._deposit_states([self.job.pk]),
            {self.job.pk: 'requested'})

    def test_paid_unclaimed_is_paid(self):
        self._deposit_invoice(Invoice.STATUS_PAID)
        self.assertEqual(
            BoardService._deposit_states([self.job.pk]),
            {self.job.pk: 'paid'})

    def test_requested_wins_over_paid(self):
        self._deposit_invoice(Invoice.STATUS_PAID)
        self._deposit_invoice(Invoice.STATUS_OPEN)
        self.assertEqual(
            BoardService._deposit_states([self.job.pk]),
            {self.job.pk: 'requested'})

    def test_claimed_deposit_clears_paid(self):
        _, dep_line = self._deposit_invoice(Invoice.STATUS_PAID)
        final = Invoice.objects.create(job=self.job,
                                       status=Invoice.STATUS_DRAFT)
        ded = InvoiceLineItem.objects.create(
            invoice=final, description='Less deposit', qty=Decimal('1'),
            price=Decimal('-5000.00'), accounting_category=self.dep_cat)
        InvoiceLineItemSource.objects.create(
            invoice_line_item=ded,
            source_type=InvoiceLineItemSource.SOURCE_DEPOSIT,
            source_pk=dep_line.pk)
        self.assertEqual(
            BoardService._deposit_states([self.job.pk]), {})

    def test_serialized_job_carries_state(self):
        self._deposit_invoice(Invoice.STATUS_OPEN)
        data = BoardService.get_board_data()
        card = next(
            (j for section in data.values() if isinstance(section, list)
             for j in section if j.get('job_id') == self.job.pk), None)
        # get_board_data's exact shape: locate the job dict wherever the
        # in-progress jobs live (read the method; adjust traversal), then:
        self.assertIsNotNone(card)
        self.assertEqual(card['deposit_state'], 'requested')
```

(The last test's traversal must match `get_board_data()`'s real payload shape — read `apps/jobs/services.py:1850+` and fix the navigation, keeping the assertion.)

- [ ] **Step 2: Verify failure:** `python manage.py test tests.test_deposit_board_state --noinput` → AttributeError `_deposit_states`.

- [ ] **Step 3: Implement** in `BoardService`:

```python
    @staticmethod
    def _deposit_states(job_ids):
        """job_id -> 'requested' | 'paid' for jobs with live deposit
        signals; jobs absent from the dict have none."""
        from apps.invoicing.models import (
            Invoice, InvoiceLineItem, InvoiceLineItemSource,
        )
        rows = list(
            InvoiceLineItem.objects
            .filter(invoice__job_id__in=job_ids,
                    accounting_category__is_deposit=True,
                    invoice__status__in=[
                        Invoice.STATUS_OPEN, Invoice.STATUS_PARTLY_PAID,
                        Invoice.STATUS_PAID])
            .exclude(
                sources__source_type=InvoiceLineItemSource.SOURCE_DEPOSIT)
            .values_list('pk', 'invoice__job_id', 'invoice__status')
        )
        claimed = set(
            InvoiceLineItemSource.objects
            .filter(source_type=InvoiceLineItemSource.SOURCE_DEPOSIT,
                    source_pk__in=[pk for pk, _, _ in rows])
            .exclude(invoice_line_item__invoice__status=
                     Invoice.STATUS_CANCELLED)
            .values_list('source_pk', flat=True)
        )
        states = {}
        for pk, job_id, status in rows:
            if status in (Invoice.STATUS_OPEN, Invoice.STATUS_PARTLY_PAID):
                states[job_id] = 'requested'
            elif pk not in claimed and states.get(job_id) != 'requested':
                states[job_id] = 'paid'
        return states
```

Thread it through serialization: change `_serialize_job(job)` to `_serialize_job(job, deposit_states=None)` adding

```python
        'deposit_state': (deposit_states or {}).get(job.job_id),
```

and at each column builder (pipeline/approved/unpaid/closed payload methods), compute `deposit_states = BoardService._deposit_states([j.job_id for j in jobs])` once per job list and pass it down (including through `_serialize_pipeline_job`/`_serialize_unpaid_job`, which call or extend `_serialize_job` — read :2174-2249 and thread consistently).

- [ ] **Step 4: Verify pass:** `python manage.py test tests.test_deposit_board_state --noinput` plus the existing board module (`ls tests/ | grep -i board` — run whichever `tests.test_*board*` modules exist) → `OK`.

- [ ] **Step 5: Commit** `feat: board jobs carry derived deposit_state`

---

### Task 8: invoice `line-items-from-service` action (backend)

**Files:**
- Modify: `apps/invoicing/services.py` (new `InvoiceService.add_line_item_from_service`)
- Modify: `apps/api/invoicing/views.py` (new action, alongside :162)
- Test: `tests/test_invoice_line_from_service.py`

**Interfaces:**
- Consumes: `ServiceItem` (`apps/estimates/models.py:428`, `template_id`/`template_name`/`rate_scheme` → `effective_accounting_category`); estimate mirror at `apps/estimates/services.py:409-435` and `apps/api/estimates/views.py:137-153`.
- Produces: `POST /api/invoices/{id}/line-items-from-service/` `{service_item, qty}` → 201 with `InvoiceLineItemSerializer` data. Pure billing line: snapshots description/units/price/AC from the ServiceItem's rate scheme; **no Task, no source row**.

- [ ] **Step 1: Failing tests** in `tests/test_invoice_line_from_service.py`:

```python
from decimal import Decimal
from django.contrib.auth.models import Permission
from django.test import TestCase
from rest_framework.test import APIClient

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.estimates.models import ServiceItem
from apps.invoicing.models import Invoice
from apps.jobs.models import Job, RateScheme, Task


class InvoiceLineFromServiceTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.user = User.objects.create_user(username='fin', password='pw')
        self.user.user_permissions.add(
            Permission.objects.get(codename='can_manage_financials'))
        self.client = APIClient()
        self.client.login(username='fin', password='pw')
        self.cat = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=True)
        self.scheme = RateScheme.objects.create(
            name='CNC-hourly', algorithm=RateScheme.ENTERED_TIME,
            rate=Decimal('90.00'), unit_label='hours',
            accounting_category=self.cat)
        self.svc = ServiceItem.objects.create(
            template_name='CNC Routing', rate_scheme=self.scheme)
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com',
            mobile_number='555')
        job = Job.objects.create(contact=contact,
                                 job_number='JOB-2026-0001',
                                 status=Job.STATUS_APPROVED)
        self.invoice = Invoice.objects.create(
            job=job, status=Invoice.STATUS_DRAFT)

    def test_creates_priced_line_no_task(self):
        before = Task.objects.count()
        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-service/',
            {'service_item': self.svc.pk, 'qty': '3'}, format='json')
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data['description'], 'CNC Routing')
        self.assertEqual(Decimal(data['qty']), Decimal('3'))
        self.assertEqual(Decimal(data['price']), Decimal('90.00'))
        self.assertEqual(data['accounting_category'], self.cat.pk)
        self.assertEqual(Task.objects.count(), before)  # no job side effects
        self.assertEqual(data['sources'], [])

    def test_unknown_service_404(self):
        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-service/',
            {'service_item': 999999, 'qty': '1'}, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_non_draft_rejected(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(
            status=Invoice.STATUS_OPEN)
        resp = self.client.post(
            f'/api/invoices/{self.invoice.pk}/line-items-from-service/',
            {'service_item': self.svc.pk, 'qty': '1'}, format='json')
        self.assertEqual(resp.status_code, 400)
```

(Check the real `ServiceItem` required fields — if `template_name`/creation kwargs differ, mirror the setUp in `tests/` modules that create ServiceItems, e.g. grep `ServiceItem.objects.create` under `tests/`. `RateScheme.ENTERED_TIME` constant name likewise — use whatever `tests/test_invoice_wizard_service.py` uses.)

- [ ] **Step 2: Verify failure:** `python manage.py test tests.test_invoice_line_from_service --noinput` → 404 on the route.

- [ ] **Step 3: Implement.** Service (mirror `apps/estimates/services.py:409-435`, minus `service_item` linkage since `InvoiceLineItem` has no such FK):

```python
    @staticmethod
    def add_line_item_from_service(invoice_pk, service_item_pk, qty):
        """Ad-hoc service billing: snapshot description/units/price/AC off
        the ServiceItem's rate scheme. No Task, no source row — pure line."""
        from apps.estimates.models import ServiceItem
        try:
            invoice = Invoice.objects.get(pk=invoice_pk)
        except Invoice.DoesNotExist:
            raise NotFoundError(f'Invoice {invoice_pk} not found')
        InvoiceService._validate_draft(invoice)
        try:
            service_item = ServiceItem.objects.select_related(
                'rate_scheme').get(pk=service_item_pk)
        except ServiceItem.DoesNotExist:
            raise NotFoundError(f'ServiceItem {service_item_pk} not found')
        from apps.core.services import LineItemService
        scheme = service_item.rate_scheme
        li = InvoiceLineItem(
            invoice=invoice,
            description=service_item.template_name,
            qty=qty,
            units=scheme.unit_label or 'none',
            price=scheme.rate,
            accounting_category=service_item.effective_accounting_category,
        )
        li.full_clean()
        LineItemService.save_line_item(li)
        return li
```

(Use the same qty-coercion helper the estimate version uses — `_decimal_or_invalid`; import or replicate its usage per the estimate mirror.)

View action in `InvoiceViewSet` (mirror `apps/api/estimates/views.py:137-153`):

```python
    @action(detail=True, methods=['post'], url_path='line-items-from-service')
    def line_items_from_service(self, request, pk=None):
        """Ad-hoc service billing line (no Task, no atoms)."""
        invoice = self.get_object()
        try:
            line_item = InvoiceService.add_line_item_from_service(
                invoice.pk,
                request.data.get('service_item'),
                request.data.get('qty'),
            )
        except NotFoundError as e:
            return Response({'detail': str(e)},
                            status=status.HTTP_404_NOT_FOUND)
        serializer = InvoiceLineItemSerializer(line_item)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
```

- [ ] **Step 4: Verify pass:** `python manage.py test tests.test_invoice_line_from_service --noinput` → `OK`.

- [ ] **Step 5: Commit** `feat: invoice line-items-from-service action for ad-hoc service billing`

---

### Task 9: AC manager frontend (`is_deposit` checkbox + freeze)

**Files:**
- Modify: `frontend/src/components/settings/AccountingCategories.svelte`
- Test: `frontend/tests/components/settings/AccountingCategories.test.js` (extend)

**Interfaces:**
- Consumes: serializer fields `is_deposit`, `is_referenced` (Task 1).
- Produces: form checkbox "Deposit category (non-taxable)"; `taxable` and `is_deposit` checkboxes disabled while editing a category with `is_referenced: true` (with a title hint "In use — retire and replace to change"); table gains a Deposit column.

- [ ] **Step 1: Failing Vitest.** Extend the existing spec with (adapt to its render/mock helpers):

```js
it('disables taxable and deposit checkboxes for a referenced category', async () => {
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/accounting-categories/')) {
      return Promise.resolve({ results: [
        { id: 1, code: 'SVC', name: 'Service', taxable: true,
          is_deposit: false, is_active: true, is_referenced: true,
          default_description: '', qbo_item_id: '', qbo_expense_account_id: '' },
      ] });
    }
    return Promise.resolve({ results: [] });
  });
  const { getByRole, findByRole } = render(AccountingCategories);
  await fireEvent.click(await findByRole('button', { name: /edit/i }));
  expect(getByRole('checkbox', { name: /taxable by default/i })).toBeDisabled();
  expect(getByRole('checkbox', { name: /deposit category/i })).toBeDisabled();
});

it('sends is_deposit on create', async () => {
  // open the add form, fill code+name, tick the deposit checkbox,
  // untick taxable, save; assert api.post payload includes
  // is_deposit: true, taxable: false.
});
```

(Write the second test fully against the component's real add-form flow — mirror the spec's existing create test.)

- [ ] **Step 2: Run to verify failure:** `cd frontend && npm run test:run -- tests/components/settings/AccountingCategories.test.js` → no such checkbox.

- [ ] **Step 3: Implement** in `AccountingCategories.svelte`:
- `emptyForm` gains `is_deposit: false`; `startEdit` copies `is_deposit`; track `editingReferenced = $state(false)` set in `startEdit(cat)` from `cat.is_referenced`.
- Form, next to the Taxable checkbox:

```svelte
    <p>
      <label>
        <input type="checkbox" bind:checked={form.taxable}
               disabled={editing && editingReferenced}
               title={editing && editingReferenced
                 ? 'In use — retire and replace to change' : ''}>
        <strong>Taxable by default</strong>
      </label>
    </p>
    <p>
      <label>
        <input type="checkbox" bind:checked={form.is_deposit}
               disabled={editing && editingReferenced}
               title={editing && editingReferenced
                 ? 'In use — retire and replace to change' : ''}
               onchange={(e) => { if (e.target.checked) form.taxable = false; }}>
        <strong>Deposit category (non-taxable)</strong>
      </label>
    </p>
```

- Table: add `<th>Deposit</th>` / `<td>{cat.is_deposit ? 'Yes' : 'No'}</td>` after the Taxable column.
- Reset `editingReferenced = false` when opening the add form.

- [ ] **Step 4: Verify pass:** `cd frontend && npm run test:run -- tests/components/settings/AccountingCategories.test.js` → pass.

- [ ] **Step 5: Commit** `feat: deposit checkbox and used-category freeze in the category manager`

---

### Task 10: `DefaultDepositCategorySetting` component

**Files:**
- Create: `frontend/src/components/settings/DefaultDepositCategorySetting.svelte`
- Modify: `frontend/src/routes/SettingsPage.svelte` (mount in the Accounting tab after `DefaultMaterialCategorySetting`)
- Test: `frontend/tests/components/settings/DefaultDepositCategorySetting.test.js`

**Interfaces:**
- Consumes: `/api/settings/` GET/PATCH (`default_deposit_accounting_category`), `/api/accounting-categories/` (`is_deposit`, `is_active`).
- Produces: settings fieldset "Deposits" with a dropdown of active deposit categories only, note text, Save.

- [ ] **Step 1: Failing Vitest** (clone `DefaultMaterialCategorySetting.test.js` shape):

```js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));
import { api } from '@/lib/api.js';
import DefaultDepositCategorySetting
  from '@/components/settings/DefaultDepositCategorySetting.svelte';

const cats = [
  { id: 1, name: 'Service', is_active: true, is_deposit: false },
  { id: 2, name: 'Customer Deposits', is_active: true, is_deposit: true },
  { id: 3, name: 'Old Deposits', is_active: false, is_deposit: true },
];

beforeEach(() => {
  api.get.mockReset(); api.patch.mockReset();
  api.get.mockImplementation((url) =>
    url.startsWith('/api/settings/')
      ? Promise.resolve({ default_deposit_accounting_category: '' })
      : Promise.resolve({ results: cats }));
});

describe('DefaultDepositCategorySetting', () => {
  it('lists only active deposit categories', async () => {
    const { findByLabelText, queryByRole } = render(DefaultDepositCategorySetting);
    const select = await findByLabelText(/default deposit category/i);
    expect(select.querySelectorAll('option')).toHaveLength(2); // None + Deposits
    expect(queryByRole('option', { name: 'Service' })).toBeNull();
    expect(queryByRole('option', { name: 'Old Deposits' })).toBeNull();
  });

  it('saves the picked category', async () => {
    api.patch.mockResolvedValue({});
    const { findByLabelText, getByRole } = render(DefaultDepositCategorySetting);
    const select = await findByLabelText(/default deposit category/i);
    await fireEvent.change(select, { target: { value: '2' } });
    await fireEvent.click(getByRole('button', { name: /save/i }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      '/api/settings/', { default_deposit_accounting_category: '2' }));
  });
});
```

- [ ] **Step 2: Verify failure:** `cd frontend && npm run test:run -- tests/components/settings/DefaultDepositCategorySetting.test.js` → module not found.

- [ ] **Step 3: Implement** — copy `DefaultMaterialCategorySetting.svelte` verbatim, then: rename state to `defaultDepositCategoryId`, key to `default_deposit_accounting_category`, `activeCategories` → `depositCategories = $derived(categories.filter(c => c.is_active && c.is_deposit))`, legend **Deposits**, label `Default deposit category` (`id="default-deposit-category"`), success text `Default deposit category saved.`, and the small note:

```svelte
    <p><small>Deposit lines are stamped with this category. Deposit
    categories are always non-taxable — deposits must not be taxed.</small></p>
```

Mount in `SettingsPage.svelte` Accounting tab after `<DefaultMaterialCategorySetting />` (line ~78): `<DefaultDepositCategorySetting />` + import.

- [ ] **Step 4: Verify pass:** run the spec → pass.

- [ ] **Step 5: Commit** `feat: default deposit category setting`

---

### Task 11: PriceListPicker deposit entry

**Files:**
- Modify: `frontend/src/components/PriceListPicker.svelte`
- Test: `frontend/tests/components/PriceListPicker.test.js` (extend)

**Interfaces:**
- Produces: new props `depositSurface = false`, `depositEnabled = true`. When `depositSurface` is true, the freeform footer shows an extra button **Add Deposit** emitting `onChoose({ type: 'deposit', typed: pickerQuery })`; disabled with `title="Set a deposit category in Settings first"` when `!depositEnabled`. Estimate/task surfaces (no prop) unchanged.

- [ ] **Step 1: Failing Vitest** (extend the existing spec, matching its render helpers):

```js
it('shows an Add Deposit button on the deposit surface', async () => {
  const onChoose = vi.fn();
  const { getByRole } = render(PriceListPicker,
    { props: { open: true, onChoose, depositSurface: true } });
  await fireEvent.click(getByRole('button', { name: /add deposit/i }));
  expect(onChoose).toHaveBeenCalledWith({ type: 'deposit', typed: '' });
});

it('disables Add Deposit when no deposit category is configured', () => {
  const { getByRole } = render(PriceListPicker,
    { props: { open: true, onChoose: vi.fn(),
               depositSurface: true, depositEnabled: false } });
  expect(getByRole('button', { name: /add deposit/i })).toBeDisabled();
});

it('has no deposit button off the deposit surface', () => {
  const { queryByRole } = render(PriceListPicker,
    { props: { open: true, onChoose: vi.fn() } });
  expect(queryByRole('button', { name: /add deposit/i })).toBeNull();
});
```

- [ ] **Step 2: Verify failure** → no such button.

- [ ] **Step 3: Implement:** add the two props; in the freeform footer (non-`taskSurface` branch), after the existing Add Line button:

```svelte
  {#if depositSurface}
    <button type="button" onclick={() => onChoose?.({ type: 'deposit', typed: pickerQuery })}
            disabled={!depositEnabled}
            title={depositEnabled ? '' : 'Set a deposit category in Settings first'}>
      Add Deposit
    </button>
  {/if}
```

- [ ] **Step 4: Verify pass:** `cd frontend && npm run test:run -- tests/components/PriceListPicker.test.js` → pass.

- [ ] **Step 5: Commit** `feat: invoice-surface deposit entry in the price list picker`

---

### Task 12: `InvoiceAddLineForm` + InvoicePanel rewire

**Files:**
- Create: `frontend/src/components/invoices/InvoiceAddLineForm.svelte`
- Modify: `frontend/src/components/invoices/InvoicePanel.svelte` (:34-37 state, :88-91 handlers, :322-356 markup)
- Test: `frontend/tests/components/invoices/InvoiceAddLineForm.test.js` (new), `frontend/tests/components/invoices/InvoicePanel.test.js` (extend)

**Interfaces:**
- Consumes: picker payloads (`service`/`inventory`/`freeform`/`deposit`), `POST /api/invoices/{id}/line-items/` (with `deposit: true` for deposits), `POST /api/invoices/{id}/line-items-from-service/` (Task 8), `categories` (with `is_deposit`), `invoice.job_number`.
- Produces: create flows through picker+form; `LineItemModal` remains edit-only. Deposit choice form: amount + prefilled editable description, no AC select (server stamps).

- [ ] **Step 1: Failing Vitest** for the new form (model on `EstimateAddLineForm.test.js`):

```js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));
import { api } from '@/lib/api.js';
import InvoiceAddLineForm from '@/components/invoices/InvoiceAddLineForm.svelte';

const cats = [{ id: 7, code: 'SVC', name: 'Service' }];
beforeEach(() => { api.post.mockReset();
                   api.post.mockResolvedValue({ line_item_id: 1 }); });

describe('InvoiceAddLineForm', () => {
  it('deposit choice posts a deposit line with prefilled description', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(InvoiceAddLineForm, {
      props: { open: true, choice: { type: 'deposit', typed: '' },
               invoiceId: 42, jobNumber: 'JOB-2026-0042',
               categories: cats, onSaved } });
    const desc = getByLabelText(/description/i);
    expect(desc.value).toBe('Deposit on JOB-2026-0042');
    await fireEvent.input(getByLabelText(/amount/i),
                          { target: { value: '5000' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/invoices/42/line-items/', {
      deposit: true, description: 'Deposit on JOB-2026-0042',
      qty: '1', units: 'none', price: '5000',
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('service choice posts to line-items-from-service', async () => {
    const choice = { type: 'service',
                     serviceItem: { template_id: 11, template_name: 'CNC' } };
    const { getByLabelText, getByRole } = render(InvoiceAddLineForm, {
      props: { open: true, choice, invoiceId: 42, jobNumber: 'J',
               categories: cats, onSaved: vi.fn() } });
    await fireEvent.input(getByLabelText(/quantity/i),
                          { target: { value: '3' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith(
      '/api/invoices/42/line-items-from-service/',
      { service_item: 11, qty: '3' });
  });

  it('freeform requires an accounting category', async () => {
    const { getByRole, findByText } = render(InvoiceAddLineForm, {
      props: { open: true, choice: { type: 'freeform', typed: 'Misc' },
               invoiceId: 42, jobNumber: 'J', categories: cats,
               onSaved: vi.fn() } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    await findByText(/accounting category is required/i);
    expect(api.post).not.toHaveBeenCalled();
  });

  it('inventory choice posts inventory_item + qty', async () => {
    const choice = { type: 'inventory',
                     inventoryItem: { inventory_item_id: 9 } };
    const { getByLabelText, getByRole } = render(InvoiceAddLineForm, {
      props: { open: true, choice, invoiceId: 42, jobNumber: 'J',
               categories: cats, onSaved: vi.fn() } });
    await fireEvent.input(getByLabelText(/quantity/i),
                          { target: { value: '2' } });
    await fireEvent.click(getByRole('button', { name: /add/i }));
    expect(api.post).toHaveBeenCalledWith('/api/invoices/42/line-items/',
      { inventory_item: 9, qty: '2' });
  });
});
```

- [ ] **Step 2: Verify failure** → module not found.

- [ ] **Step 3: Implement `InvoiceAddLineForm.svelte`.** Start from `EstimateAddLineForm.svelte` (read it in full first); props `{ open, choice, invoiceId, jobNumber, categories, onSaved, onClose }`. Differences:
- API base `/api/invoices/${invoiceId}` (service → `/line-items-from-service/`, others → `/line-items/`).
- No `is_material` marker anywhere (invoices have no material hand-line concept).
- New `isDeposit = choice?.type === 'deposit'` branch: fields = Description (prefill `choice.typed || 'Deposit on ' + jobNumber`) + Amount (number input, label **Amount**); posts `{ deposit: true, description, qty: '1', units: 'none', price: amount }`. No AC select shown for deposits.
- Freeform: description/qty/units/price/AC-select (AC required, message `Accounting Category is required.`).
- Error handling identical to the estimate form (`error = e.message || 'Could not add line.'`; deposit path errors from `triageError` field mapping welcome but match the estimate form's simpler pattern).

**Rewire `InvoicePanel.svelte`:**

```js
  // state (replacing create-mode LineItemModal usage)
  let pickerOpen = $state(false);
  let addChoice = $state(null);
  function openAddItem() { pickerOpen = true; }
  function handleChoose(choice) { pickerOpen = false; addChoice = choice; }
  function handleLineAdded() { addChoice = null; loadInvoice(); }
  let hasDepositCategory = $derived(
    categories.some((c) => c.is_active !== false && c.is_deposit));
```

Markup: keep the Add Line Item button calling `openAddItem`; add

```svelte
  <PriceListPicker open={pickerOpen} onChoose={handleChoose}
    depositSurface={true} depositEnabled={hasDepositCategory}
    onclose={() => { pickerOpen = false; }} />
  <InvoiceAddLineForm
    open={addChoice != null}
    choice={addChoice}
    invoiceId={invoice.invoice_id}
    jobNumber={invoice.job_number}
    {categories}
    onSaved={handleLineAdded}
    onClose={() => { addChoice = null; }} />
```

`LineItemModal` stays for edit only: `modalMode` fixed to `'edit'`, opened by `openEditItem` (drop the `'create'` path). Imports: add `PriceListPicker`, `InvoiceAddLineForm`.

Extend `InvoicePanel.test.js`: the existing "add line" test(s) change to assert the picker opens; add one test that a `deposit` choice renders the deposit form (mirror the panel spec's existing modal-flow assertions).

- [ ] **Step 4: Verify pass:** `cd frontend && npm run test:run -- tests/components/invoices/InvoiceAddLineForm.test.js tests/components/invoices/InvoicePanel.test.js tests/components/LineItemModal.test.js` → pass.

- [ ] **Step 5: Commit** `feat: invoice add-line adopts the picker flow with a deposit entry`

---

### Task 13: wizard UI — deposit credit atoms

**Files:**
- Modify: `frontend/src/components/wizards/WizardAtomRow.svelte`
- Test: `frontend/tests/components/wizards/WizardAtomRow.test.js` (extend or create alongside existing wizard specs)

**Interfaces:**
- Consumes: pool atoms `{type: 'deposit', description: 'Deposit credit — INV-1042', amount: '-5000.00', state, ...}` (Task 5). The group flows through `WizardSourcePool` untouched (it renders `sourcePool.tasks` generically).
- Produces: `[deposit]` type label; negative amounts render as `−$5,000.00 credit`.

- [ ] **Step 1: Failing Vitest:**

```js
it('labels deposit atoms and shows the credit amount', () => {
  const atom = { type: 'deposit', id: 5,
                 description: 'Deposit credit — INV-1042',
                 qty: '1', rate: '-5000.00', units: 'none',
                 amount: '-5000.00', state: 'available' };
  const { getByText } = render(WizardAtomRow,
    { props: { atom, selected: false, onToggle: vi.fn() } });
  getByText('[deposit]');
  getByText(/credit/i);
});
```

(Match the component's real props — read the existing usages/spec first; if row rendering needs a harness, follow the `_Harness` convention from `docs/designs/frontend-testing.md`.)

- [ ] **Step 2: Verify failure** → `[material]` label instead.

- [ ] **Step 3: Implement:** extend the type ternary:

```svelte
<small>[{atom.type === 'task' ? 'task' : atom.type === 'expense' ? 'expense'
  : atom.type === 'fee' ? 'fee' : atom.type === 'deposit' ? 'deposit'
  : 'material'}]</small>
```

and where `formatDetail` renders, branch for deposits:

```svelte
{#if atom.type === 'deposit'}
  <span>{fmtMoney(Math.abs(Number(atom.amount)))} credit</span>
{:else}
  ...existing detail...
{/if}
```

(Use the file's existing money formatter; if none, format as the row already formats `amount`.)

- [ ] **Step 4: Verify pass:** run the spec → pass.

- [ ] **Step 5: Commit** `feat: deposit credit rendering in the reconcile atom rows`

---

### Task 14: indicator pills (invoice list, job overview, board card)

**Files:**
- Modify: `frontend/src/routes/invoices/InvoiceListPage.svelte`
- Modify: `frontend/src/lib/jobOverview.js` (`invoiceStat` :517-538)
- Modify: `frontend/src/components/board/JobCard.svelte`
- Test: `frontend/tests/components/invoices/InvoiceListPage.test.js`, `frontend/tests/lib/jobOverview.test.js`, `frontend/tests/components/board/JobCard.test.js` (extend each)

**Interfaces:**
- Consumes: `inv.is_deposit` (Task 6) in list/overview payloads; `job.deposit_state` (Task 7) on board jobs.
- Produces: list status cell gains a `DEPOSIT` pill; overview invoice stat label gains `· deposit`; JobCard shows `DEP REQUESTED` / `DEP PAID` pill.

- [ ] **Step 1: Failing Vitests** (one per surface, added to the existing specs using their established render/mock patterns):

```js
// InvoiceListPage.test.js — row data includes is_deposit: true
it('shows a DEPOSIT pill next to the status', async () => {
  // mock the list GET with one row { ..., status: 'open', is_deposit: true }
  // render, then:
  await findByText('DEPOSIT');
});

// jobOverview.test.js
it('marks deposit invoices in the invoicing block', () => {
  const model = invoicingBlock({
    invoices: [{ display_number: 'INV-1042', status: 'open',
                 sent_date: '2026-07-20T00:00:00Z', total: '5000',
                 is_deposit: true }],
    scopeTotal: 10000, invoicedTotal: 5000, now: NOW });
  const stat = model.stats.find((s) => s.label.includes('INV-1042'));
  expect(stat.label).toContain('deposit');
});

// JobCard.test.js
it('renders the deposit pill from deposit_state', () => {
  const { getByText, rerender } = render(JobCard,
    { props: { job: { ...baseJob, deposit_state: 'requested' } } });
  getByText('DEP REQUESTED');
});
```

(`NOW`/`baseJob`: reuse each spec's existing fixtures.)

- [ ] **Step 2: Verify failure** on all three.

- [ ] **Step 3: Implement.**

`InvoiceListPage.svelte` status cell:

```svelte
  <td>
    {inv.status}
    {#if inv.is_deposit}<span class="deposit-pill">DEPOSIT</span>{/if}
  </td>
```

with local style (matches the JobCard doc-pill scale):

```css
  .deposit-pill { font-size: 9px; padding: 1px 6px; border-radius: 8px;
                  font-weight: 600; background: #e0e7ff; color: #3730a3;
                  margin-left: 6px; }
```

`jobOverview.js` `invoiceStat` first line:

```js
  const s = { label: inv.is_deposit
      ? `${inv.display_number} · deposit`
      : inv.display_number,
    value: fmtMoney(invoiceTotal(inv)) };
```

`JobCard.svelte`, next to the hold banner block:

```svelte
  {#if job.deposit_state}
    <div class="deposit-banner"
         class:deposit-paid={job.deposit_state === 'paid'}>
      {job.deposit_state === 'paid' ? 'DEP PAID' : 'DEP REQUESTED'}
    </div>
  {/if}
```

```css
  .deposit-banner { font-size: 9px; font-weight: 700; text-align: center;
                    padding: 1px 0; border-radius: 8px;
                    background: #fef3c7; color: #b45309; }
  .deposit-banner.deposit-paid { background: #dcfce7; color: #15803d; }
```

- [ ] **Step 4: Verify pass:** `cd frontend && npm run test:run -- tests/components/invoices/InvoiceListPage.test.js tests/lib/jobOverview.test.js tests/components/board/JobCard.test.js` then the full `npm run test:run` → all pass.

- [ ] **Step 5: Commit** `feat: derived deposit indicators on invoice list, job overview, and board card`

---

### Task 15: E2E — seed rows + two specs

**Files:**
- Modify: `fixtures/playwright/seed.json` (hand-append rows in dumpdata shape)
- Create: `e2e/specs/deposits/deposit-creation.spec.js`, `e2e/specs/deposits/deposit-credit.spec.js`
- Create: `docs/ui-flows/deposits.md` (checklist the specs trace to — match the existing `docs/ui-flows/` format)

**Interfaces:**
- Consumes: everything shipped above; e2e personas (`finjobs`, `configtime`), `apiAs`/`loadBackdrop` fixtures.
- Produces: browser-level proof of the deposit flow. QBO is unreachable in e2e, so **the paid deposit is seeded**, and send/pay transitions are not driven.

- [ ] **Step 1: Seed additions** (hand-append, mirroring existing rows' field shape exactly — open `seed.json` and copy a neighboring `core.accountingcategory` / `invoicing.invoice` / `invoicing.invoicelineitem` row as the template; all AC rows in the seed also need `"is_deposit"` added to match the new model — verify whether the seed's dumpdata rows carry every field; if they omit defaults, only the new rows need it):
  - `core.accountingcategory`: pk clear of existing ones, `code: "DEP"`, `name: "Customer Deposits"`, `taxable: false`, `is_deposit: true`, `is_active: true`.
  - `core.configuration`: pk `"default_deposit_accounting_category"`, value = that AC pk as string.
  - One **paid** deposit invoice on a seeded job that has in_progress status and no other draft: `invoicing.invoice` row (`status: "paid"`, `invoice_number: "INV-E2E-DEP-1"`, plausible `created_date`/`sent_date`/`closed_date` within the seed's date span so the rebaser shifts them coherently), plus its `invoicing.invoicelineitem` row (deposit AC, qty 1, price 5000, line_number 1). Pick the job by inspecting `seed.json` (a `jobs.job` row with `status: "in_progress"`) and record its pk in the spec via `loadBackdrop()` lookup by job_number rather than hard-coding.
  - Run `cd e2e && npx playwright test --list` first to confirm the seed loads (reset pipeline runs `loaddata`); a `loaddata` failure here means a field-shape mismatch — fix the appended rows.

- [ ] **Step 2: `deposit-creation.spec.js`** — persona `finjobs`:
  1. Find an invoice-less approved/in_progress job (reuse the `findInvoicelessJob` helper pattern from `e2e/specs/invoice-seeding-and-send/draft-placeholder.spec.js`).
  2. `#/jobs/{id}/invoice` → Start Invoice → Add Line Item → picker → click **Add Deposit** → description prefilled `Deposit on {job_number}` → amount 2500 → Add.
  3. Assert the line renders with the deposit category and 2500; navigate to `#/invoices`, assert the row shows the `DEPOSIT` pill.
  4. Cleanup: discard the draft via API (`api.del .../?confirm=true`), same as the existing spec.

- [ ] **Step 3: `deposit-credit.spec.js`** — persona `finjobs`:
  1. `loadBackdrop()`; locate the seeded paid-deposit job.
  2. Job Board: assert the job's chip/card shows `DEP PAID` (In Progress area — hover the chip to reveal the card, per `JobChipStrip` behavior).
  3. `#/jobs/{id}/invoice` → Start Invoice → open Reconcile ("Show Tasks & Materials") → assert a `Deposit credits` group with `Deposit credit — INV-E2E-DEP-1` and a `[deposit]` row → pull it ("Add Here") → assert a line `Less deposit (INV-E2E-DEP-1)` with amount −5,000.00 appears.
  4. Re-open the pool: the credit shows as claimed. Board card no longer shows `DEP PAID`? — **no**: the claim is on a *draft* (live) invoice, so `DEP PAID` clears; assert that.
  5. Cleanup: discard the draft; board shows `DEP PAID` again (claim released).

- [ ] **Step 4: Run** `cd e2e && npx playwright test specs/deposits/ --reporter=line` → read the pass/fail summary directly (no piping). Fix selectors against the real DOM as needed.

- [ ] **Step 5: Commit** `e2e: deposit creation and credit-deduction specs with seeded paid deposit`

---

### Task 16: docs + full-suite verification

**Files:**
- Modify: `docs/designs/invoicing-and-expenses.md` (new "Deposits" section: concept, category flag, creation path, pool rules, deduction lock, indicators; fix stale `taxable_override` at §118/§298), `docs/designs/estimates-and-prices.md` (§687 stale mention), `docs/designs/data-constraints.md` (AccountingCategory field table: `is_deposit` + invariants + freeze; §1.1 new Configuration key; InvoiceLineItemSource `deposit` type), `docs/designs/jobs-and-tasks.md` (board card `deposit_state` pill), `docs/designs/architecture-and-conventions.md` (only if it enumerates picker payload types), `docs/designs/LATER.md` (new entry below)
- Delete: `docs/plans/deposit-invoices-spec.md` and this plan (per docs convention — plans are disposable once shipped) — **only after RM approves the branch**; leave both in place at commit time, note for RM.

**Steps:**

- [ ] **Step 1: LATER.md entry** for the pre-existing claim asymmetry the deposit path inherits:

```markdown
- **Cancelled invoices keep their atom-claim rows.** — _added 2026-07-25_
  `InvoiceService.cancel` only flips status; `InvoiceLineItemSource` rows
  survive. The pool shows such atoms (incl. deposit credits) as available
  — the claim exclusion is logical — but re-pulling one hits the DB
  unique constraint → 409 `atoms_already_claimed`. Pre-existing for
  task/material/fee atoms; deposits inherit it.
  _Done when:_ cancel releases claims (or re-claim reuses the dead row).
```

- [ ] **Step 2: Update the design docs** listed above. Keep each addition in the doc's existing voice; the invoicing doc's Deposits section should state: deposit-ness = deposit-category line without a deposit source row; paid-only credit; whole-amount lock; requested/paid/consumed indicator states; negative-total invoices rejected by QBO at push (accepted guard).

- [ ] **Step 3: Full verification** (single runner, no pipes, fresh DB because this plan adds migrations):
  - `python manage.py test --noinput` (NO `--keepdb`) → write output to a file if long, then read the `Ran N tests` + `OK`/`FAILED` lines.
  - `cd frontend && npm run test:run` → all pass.
  - `cd e2e && npx playwright test` → all pass (includes the two new specs).
  - `cd frontend && npm run build` → succeeds (Svelte strict-mode gate).

- [ ] **Step 4: Commit** `docs: deposit invoices reference updates` — then report to RM: branch ready for review; do NOT merge/push/PR.

---

## Self-review notes (already applied)

- Spec coverage: every spec section maps to a task (category flag+freeze → 1; settings key → 2/10; source type+helpers → 3; creation path → 4/11/12; pool/deduction/locks → 5/13; indicators → 6/7/14; picker alignment → 8/11/12; QBO → no code (Task 5 note); edge cases → tests in 5/6/7; e2e → 15; docs → 16).
- The `apply-everything`/`send-all` interaction with deposit credits is deliberate (they are available atoms) — Task 5 Step 4 calls it out so the implementer doesn't "fix" it.
- Exact local variable names inside `get_source_pool` / board builders are to be read from the file — the plan gives the code shape and the line ranges, and says to adopt the file's names.
