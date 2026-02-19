# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Minibini is a Django-based job shop management system for handling jobs, estimates, work orders, invoicing, and purchasing. Pre-production state, rapidly evolving.

**Tech Stack:** Django 5.2+, MySQL, Python 3.12, plain semantic HTML (no CSS frameworks/JS)

## Essential Commands

```bash
# Development
python manage.py runserver              # Start dev server (auto-logs in dev_user)

# Database
python manage.py makemigrations         # Create migrations (OK to run)
python manage.py loaddata unit_test_data.json  # Load test fixtures

# Testing
python manage.py test                   # Run all tests
python manage.py test tests.test_foo    # Run specific test module

# Docker
docker compose up                       # Full stack (app, mysql, nginx)
```

**CRITICAL:** NEVER run `python manage.py migrate` - only the human user applies migrations to the development database. Creating migrations with `makemigrations` is fine; tests create their own test database automatically.

## Architecture

```
apps/
├── core/       # User model, Configuration, BaseLineItem, LineItemType
├── jobs/       # Job, Estimate, EstWorksheet, WorkOrder, Task, Templates (largest app)
├── contacts/   # Contact, Business, PaymentTerms
├── invoicing/  # Invoice, InvoiceLineItem, PriceListItem
└── purchasing/ # PurchaseOrder, Bill, line items
```

**Key Patterns:**
- Function-based views only (no CBVs)
- Service classes in `apps/*/services.py` contain business logic
- Signals in `apps/jobs/signals.py` handle status change side effects
- Abstract `BaseLineItem` shared by all line item types
- Template system: `WorkOrderTemplate` → `TaskTemplate` → `TaskMapping` → `ProductBundlingRule`

**Workflow:** Job → EstWorksheet (from template) → Estimate → WorkOrder → Invoice

## Template/HTML Conventions

- **No CSS frameworks, no JavaScript** (except datetime-local inputs)
- **Semantic HTML only:** `<p>`, `<strong>`, `<fieldset>`, `<table border="1">`
- **Django messages:** Use `messages.success()`/`error()` in views; NEVER duplicate message display in templates (base.html handles it)
- **Form pattern:** `<p><label><strong>Label</strong></label><br><input></p>`
- **Buttons:** Plain `<button>`, simple `<a>` links (no styling)

## Code Conventions

**Status Constants:** Always use model constants, not string literals:
```python
Job.objects.exclude(status__in=[Job.STATUS_COMPLETED, Job.STATUS_REJECTED])
```

**Document Numbers:** Only generate for NEW instances:
```python
if not instance.pk:
    instance.po_number = generate_next_number('po')
```

**Deletion:** Custom `delete()` methods exist - iterate instead of `QuerySet.delete()`:
```python
for contact in Contact.objects.filter(...):
    contact.delete()
```

**Transactions:** Wrap multi-model operations:
```python
with transaction.atomic():
    business = Business.objects.create(...)
    contact = Contact.objects.create(business=business, ...)
```

## Testing

**Use Test-Driven Development (TDD) for all code work:**
1. Write failing tests first
2. Verify tests fail for the expected reason
3. Write minimal code to make tests pass
4. Refactor while keeping tests green

- Tests in `/tests/` directory using Django TestCase
- Fixtures in `/fixtures/` (JSON format)
- Base test classes: `BaseTestCase`, `FixtureTestCase` in `tests/base.py`

## Key Files

- `README-C.md` - Comprehensive codebase documentation (read for detailed info)
- `apps/jobs/models.py` - Core models (747 lines)
- `apps/jobs/views.py` - Main views (66KB)
- `apps/core/services.py` - Business logic services
- `docs/` - Implementation plans and technical docs
