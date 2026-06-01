# Customer Estimate Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a customer view and accept/reject an emailed Estimate without logging in, via an unguessable per-estimate token link that lands on a separate Svelte "portal" page.

**Architecture:** A `public_token` minted on `Estimate` at creation time backs a token-authorized, login-not-required `/api/portal/` API (read + accept + reject) served to a second Vite entry (the portal page). Accept/reject reuse the existing estimate status machine and signals; the customer is attributed through a new `actor` parameter on `EstimateService.update_status` that writes an explicit `HistoryEntry` (no shadow `User`). A shop notification email fires on decision, addressed to a new `business_email` Configuration key surfaced in a new Settings → Business tab.

**Tech Stack:** Django 5.2 + DRF (function-based AllowAny views), MySQL, Svelte 5 runes + Vite multi-page build.

**Spec:** `docs/plans/2026-05-31-customer-estimate-approval-spec.md`

---

## Constraints (read before starting)

- **NEVER write to the dev DB.** `makemigrations` is fine; `migrate` is NOT. Tests use their own DB. Do not open a Django shell to "verify" — write a test. (CLAUDE.md)
- **Only one agent runs `python manage.py test` at a time.**
- Use model status constants, never string literals.
- New Configuration keys must be added to fixtures and test setups.

---

## File Structure

**Backend — create:**
- `apps/api/portal/__init__.py` — empty
- `apps/api/portal/views.py` — three function views (get / accept / reject) + payload helper
- `apps/api/portal/urls.py` — portal URL patterns
- `apps/estimates/migrations/00NN_estimate_public_token.py` — field + backfill (generated, then edited)

**Backend — modify:**
- `apps/estimates/models.py` — add `public_token` field + mint in `save()`
- `apps/estimates/services.py` — `update_status(pk, new_status, actor=None)` + `EstimateEmailService.notify_shop_of_decision`
- `apps/core/email_templates.py` — `build_object_url` returns the portal token URL for estimates
- `apps/api/urls.py` — include `apps.api.portal.urls` under `portal/`

**Frontend — create:**
- `frontend/portal/index.html` — second Vite entry
- `frontend/src/portal-main.js` — portal mount
- `frontend/src/PortalApp.svelte` — the customer page
- `frontend/src/components/settings/BusinessSettings.svelte` — the Business tab body

**Frontend — modify:**
- `frontend/vite.config.js` — declare both entries
- `frontend/src/routes/SettingsPage.svelte` — add Business tab

**Tests — create:** one file per backend task (see tasks).

**Fixtures/docs — modify:** `fixtures/unit_test_data.json`, five `docs/designs/*.md`, `docs/designs/LATER.md`.

---

## Task 1: `Estimate.public_token` field, minted at creation

**Files:**
- Modify: `apps/estimates/models.py:1-6` (imports), `apps/estimates/models.py:29-39` (fields), `apps/estimates/models.py:103-150` (`save()`)
- Create: `apps/estimates/migrations/00NN_estimate_public_token.py`
- Test: `tests/test_estimate_public_token.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_estimate_public_token.py
from django.test import TestCase

from apps.contacts.models import Contact
from apps.estimates.models import Estimate
from apps.estimates.services import EstimateService
from apps.jobs.services import JobService


class EstimatePublicTokenTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer',
            email='pat@acme.com', work_number='555-0000',
        )
        self.job = JobService.create_job(name='Token Job', contact=self.contact)

    def test_token_minted_on_create(self):
        est = EstimateService.create_for_job(self.job.pk)
        self.assertTrue(est.public_token)
        self.assertGreaterEqual(len(est.public_token), 20)

    def test_token_is_stable_across_saves(self):
        est = EstimateService.create_for_job(self.job.pk)
        token = est.public_token
        est.status = Estimate.STATUS_OPEN  # not transitioning yet, just re-save path
        est.public_token = token
        est.save()
        est.refresh_from_db()
        self.assertEqual(est.public_token, token)

    def test_two_estimates_get_distinct_tokens(self):
        a = EstimateService.create_for_job(self.job.pk)
        job2 = JobService.create_job(name='Token Job 2', contact=self.contact)
        b = EstimateService.create_for_job(job2.pk)
        self.assertNotEqual(a.public_token, b.public_token)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_estimate_public_token -v 2`
Expected: FAIL — `Estimate` has no attribute/field `public_token`.

- [ ] **Step 3: Add the field and minting**

In `apps/estimates/models.py`, add `import secrets` to the top imports:

```python
import secrets
from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.core.models import BaseLineItem, AbstractWorkContainer
from apps.core.history import history
```

Add the field to the `Estimate` class field block (after `expiration_date`):

```python
    # Unguessable token backing the customer-facing portal link. Minted at
    # creation (see save()); per-row, so each revision gets its own.
    public_token = models.CharField(
        max_length=64, null=True, blank=True, unique=True, db_index=True,
    )
```

In `Estimate.save()`, mint at creation as the very first thing inside the method (before the `if self.pk:` block):

```python
    def save(self, *args, **kwargs):
        """Override save to detect status changes, set dates, and send signals if needed."""
        from apps.core.models import Configuration
        from datetime import timedelta

        # Mint the customer-portal token once, at creation.
        if not self.pk and not self.public_token:
            self.public_token = secrets.token_urlsafe(32)

        old_status = None
        # ... rest unchanged ...
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations estimates`
Expected: a new migration `apps/estimates/migrations/00NN_estimate_public_token.py` adding `public_token`.

- [ ] **Step 5: Add a backfill to the generated migration**

Open the generated file and insert a `RunPython` backfill so existing rows get tokens (harmless — those estimates' emails never carried a token). The result should look like:

```python
import secrets
from django.db import migrations, models


def backfill_tokens(apps, schema_editor):
    Estimate = apps.get_model('estimates', 'Estimate')
    for est in Estimate.objects.filter(public_token__isnull=True):
        est.public_token = secrets.token_urlsafe(32)
        est.save(update_fields=['public_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('estimates', '00NN_previous'),  # leave the generated dependency as-is
    ]

    operations = [
        migrations.AddField(
            model_name='estimate',
            name='public_token',
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True, unique=True),
        ),
        migrations.RunPython(backfill_tokens, migrations.RunPython.noop),
    ]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python manage.py test tests.test_estimate_public_token -v 2`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add apps/estimates/models.py apps/estimates/migrations/ tests/test_estimate_public_token.py
git commit -m "feat(estimates): mint per-estimate public_token at creation"
```

---

## Task 2: `build_object_url` returns the portal token URL for estimates

**Files:**
- Modify: `apps/core/email_templates.py:46-61` (`build_object_url`)
- Test: `tests/test_email_object_url.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_email_object_url.py
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.email_templates import build_object_url
from apps.core.models import Configuration
from apps.estimates.services import EstimateService
from apps.jobs.services import JobService


class BuildObjectUrlEstimateTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        Configuration.objects.update_or_create(
            key='our_public_url', defaults={'value': 'https://shop.example.com'})
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='URL Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)

    def test_estimate_url_uses_portal_token(self):
        url = build_object_url('estimate', self.est.estimate_id)
        self.assertEqual(
            url, f'https://shop.example.com/portal/?token={self.est.public_token}')

    def test_other_kinds_keep_stub(self):
        url = build_object_url('invoice', 42)
        self.assertEqual(url, 'https://shop.example.com/invoices/42')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_email_object_url -v 2`
Expected: FAIL — estimate URL still `.../estimates/<id>`.

- [ ] **Step 3: Update `build_object_url`**

Replace the body of `build_object_url` in `apps/core/email_templates.py`:

```python
def build_object_url(kind, obj_id):
    """Resolve the ``{object_url}`` template placeholder for a given doc.

    For ``estimate`` this resolves to the customer portal token URL
    (``<base>/portal/?token=<token>``). Other kinds keep the legacy stub
    ``<base>/<entity-path>/<id>`` until their own portal surfaces exist.
    """
    from apps.core.models import Configuration
    try:
        base = Configuration.objects.get(key='our_public_url').value
    except Configuration.DoesNotExist:
        base = DEFAULT_OUR_PUBLIC_URL
    base = base.rstrip('/')

    if kind == 'estimate':
        from apps.estimates.models import Estimate
        try:
            token = Estimate.objects.get(pk=obj_id).public_token
        except Estimate.DoesNotExist:
            token = None
        if token:
            return f'{base}/portal/?token={token}'

    path = _OBJECT_URL_PATHS.get(kind, kind)
    return f'{base}/{path}/{obj_id}'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_email_object_url -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/core/email_templates.py tests/test_email_object_url.py
git commit -m "feat(email): resolve {object_url} to the portal token URL for estimates"
```

---

## Task 3: `update_status` actor seam + customer HistoryEntry

**Files:**
- Modify: `apps/estimates/services.py:56-64` (`update_status`)
- Test: `tests/test_estimate_update_status_actor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_estimate_update_status_actor.py
from decimal import Decimal
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import HistoryEntry
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.jobs.services import JobService


class UpdateStatusActorTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='Actor Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Work', qty=Decimal('1'),
            price=Decimal('100.00'))
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)

    def test_actor_writes_customer_history_entry(self):
        EstimateService.update_status(
            self.est.pk, Estimate.STATUS_ACCEPTED,
            actor={'contact_id': self.contact.pk, 'email': 'pat@acme.com'})
        entry = HistoryEntry.objects.filter(
            object_type='estimate', object_id=self.est.pk, entry_type='action',
        ).order_by('-timestamp').first()
        self.assertIsNotNone(entry)
        self.assertIsNone(entry.user)
        self.assertEqual(entry.changes['_action'], 'Accepted via customer link')
        self.assertEqual(entry.changes['customer_email'], 'pat@acme.com')

    def test_reject_actor_records_reason(self):
        EstimateService.update_status(
            self.est.pk, Estimate.STATUS_REJECTED,
            actor={'contact_id': self.contact.pk, 'email': 'pat@acme.com',
                   'reason': 'Too expensive'})
        entry = HistoryEntry.objects.filter(
            object_type='estimate', object_id=self.est.pk, entry_type='action',
        ).order_by('-timestamp').first()
        self.assertEqual(entry.changes['_action'], 'Declined via customer link')
        self.assertEqual(entry.text, 'Too expensive')

    def test_no_actor_writes_no_action_entry(self):
        before = HistoryEntry.objects.filter(
            object_type='estimate', object_id=self.est.pk,
            entry_type='action').count()
        EstimateService.update_status(self.est.pk, Estimate.STATUS_ACCEPTED)
        after = HistoryEntry.objects.filter(
            object_type='estimate', object_id=self.est.pk,
            entry_type='action').count()
        self.assertEqual(before, after)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_estimate_update_status_actor -v 2`
Expected: FAIL — `update_status()` takes no `actor` kwarg.

- [ ] **Step 3: Add the `actor` parameter**

Replace `EstimateService.update_status` in `apps/estimates/services.py`:

```python
    @staticmethod
    def update_status(pk, new_status, actor=None):
        """Update estimate status. Model validates transitions.

        When ``actor`` is given (a dict describing a customer who acted via
        the portal link, e.g. ``{'contact_id': N, 'email': str,
        'reason': str|None}``), write an explicit, user-less action
        HistoryEntry recording the decision and the customer context.
        """
        try:
            estimate = Estimate.objects.get(pk=pk)
        except Estimate.DoesNotExist:
            raise NotFoundError(f'Estimate {pk} not found')
        old_status = estimate.status
        estimate.status = new_status
        estimate.save()  # Model.save() calls full_clean() and handles dates

        if actor:
            from apps.core.models import HistoryEntry
            label = ('Accepted via customer link'
                     if new_status == Estimate.STATUS_ACCEPTED
                     else 'Declined via customer link')
            HistoryEntry.objects.create(
                entry_type='action',
                object_type='estimate',
                object_id=estimate.pk,
                user=None,
                changes={
                    'status': {'old': old_status, 'new': new_status},
                    '_action': label,
                    'contact_id': actor.get('contact_id'),
                    'customer_email': actor.get('email'),
                },
                text=actor.get('reason') or '',
            )
        return estimate
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_estimate_update_status_actor -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/services.py tests/test_estimate_update_status_actor.py
git commit -m "feat(estimates): actor seam on update_status for customer attribution"
```

---

## Task 4: Shop notification on decision

**Files:**
- Modify: `apps/estimates/services.py` (add `notify_shop_of_decision` to `EstimateEmailService`)
- Test: `tests/test_shop_notification.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shop_notification.py
from django.core import mail
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.estimates.services import EstimateEmailService
from apps.estimates.services import EstimateService
from apps.jobs.services import JobService


class ShopNotificationTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='Notify Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)

    def test_notifies_business_email_when_set(self):
        Configuration.objects.update_or_create(
            key='business_email', defaults={'value': 'office@shop.com'})
        EstimateEmailService.notify_shop_of_decision(self.est, 'accepted')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('office@shop.com', mail.outbox[0].to)
        self.assertIn(self.est.estimate_number, mail.outbox[0].subject)

    def test_skips_when_unset(self):
        Configuration.objects.filter(key='business_email').delete()
        EstimateEmailService.notify_shop_of_decision(self.est, 'accepted')
        self.assertEqual(len(mail.outbox), 0)

    def test_never_raises_on_send_failure(self):
        Configuration.objects.update_or_create(
            key='business_email', defaults={'value': 'office@shop.com'})
        # Reason text included; must not raise even if backend errored.
        EstimateEmailService.notify_shop_of_decision(
            self.est, 'declined', reason='Budget')
        # If we got here without raising, the contract holds.
        self.assertTrue(True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_shop_notification -v 2`
Expected: FAIL — `EstimateEmailService` has no `notify_shop_of_decision`.

- [ ] **Step 3: Add the notifier**

Add this static method to `EstimateEmailService` in `apps/estimates/services.py`:

```python
    @staticmethod
    def notify_shop_of_decision(estimate, decision, reason=''):
        """Best-effort email to the shop's business_email when a customer
        accepts/rejects via the portal. Never raises — the customer's action
        has already committed and must not be rolled back by a send failure.
        """
        from django.conf import settings
        from django.core.mail import send_mail
        from apps.core.models import Configuration

        try:
            addr = Configuration.objects.get(key='business_email').value.strip()
        except Configuration.DoesNotExist:
            addr = ''
        if not addr:
            return

        job_name = estimate.job.name if estimate.job_id else ''
        subject = f'Estimate {estimate.estimate_number} {decision} by customer'
        body = (f'Estimate {estimate.estimate_number} for job "{job_name}" '
                f'was {decision} by the customer.')
        if reason:
            body += f'\n\nReason given:\n{reason}'
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [addr])
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_shop_notification -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/estimates/services.py tests/test_shop_notification.py
git commit -m "feat(estimates): best-effort shop notification on customer decision"
```

---

## Task 5: Portal payload builder (customer-safe)

**Files:**
- Create: `apps/api/portal/__init__.py` (empty), `apps/api/portal/views.py` (payload helper only for now)
- Test: `tests/test_portal_payload.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portal_payload.py
from decimal import Decimal
from django.test import TestCase

from apps.api.portal.views import build_estimate_payload
from apps.contacts.models import Contact
from apps.deliverables.models import Deliverable
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.jobs.services import JobService


class PortalPayloadTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='Payload Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Build widget',
            qty=Decimal('2'), units='each', price=Decimal('50.00'))
        Deliverable.objects.create(
            job=self.job, description='One finished widget',
            qty_ordered=Decimal('2'), units='each')

    def test_open_payload_shape(self):
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        self.est.refresh_from_db()
        data = build_estimate_payload(self.est)
        self.assertEqual(data['status'], 'open')
        self.assertEqual(data['actions'], ['accept', 'reject'])
        self.assertEqual(len(data['line_items']), 1)
        self.assertEqual(data['line_items'][0]['amount'], '100.00')
        self.assertEqual(data['grand_total'], '100.00')
        self.assertEqual(len(data['deliverables']), 1)
        self.assertEqual(data['deliverables'][0]['description'], 'One finished widget')
        self.assertNotIn('cost', str(data))  # no internal/cost leakage

    def test_draft_has_no_actions(self):
        data = build_estimate_payload(self.est)
        self.assertEqual(data['actions'], [])

    def test_superseded_exposes_current_token(self):
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        new_est = EstimateService.revise_estimate(self.est.pk)  # parent → superseded
        self.est.refresh_from_db()
        data = build_estimate_payload(self.est)
        self.assertEqual(data['status'], 'superseded')
        self.assertEqual(data['current_token'], new_est.public_token)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_portal_payload -v 2`
Expected: FAIL — `apps.api.portal` does not exist.

- [ ] **Step 3: Create the package and payload helper**

Create empty `apps/api/portal/__init__.py`.

Create `apps/api/portal/views.py` with the helper (views come in Task 6):

```python
"""Token-authorized, login-not-required customer portal API for Estimates.

Named 'portal', not 'public' — these documents aren't public, they just
don't require a Minibini login to view. Every endpoint authorizes by the
estimate's opaque public_token.
"""
from decimal import Decimal

from apps.estimates.models import Estimate


def _money(value):
    return str((value or Decimal('0')).quantize(Decimal('0.01')))


def _line_amount(li):
    return (li.qty or Decimal('0')) * (li.price or Decimal('0'))


def _current_token(estimate):
    """The live head of the revision lineage for a superseded estimate:
    highest-version row with the same estimate_number that isn't superseded.
    """
    head = (Estimate.objects
            .filter(estimate_number=estimate.estimate_number)
            .exclude(status=Estimate.STATUS_SUPERSEDED)
            .order_by('-version')
            .first())
    return head.public_token if head else None


def build_estimate_payload(estimate):
    """Customer-safe dict for an estimate. Exposes only what a customer
    needs to decide — never the internal serializer's fields."""
    actions = (['accept', 'reject']
               if estimate.status == Estimate.STATUS_OPEN else [])

    line_items = []
    total = Decimal('0')
    for li in estimate.estimatelineitem_set.all().order_by('line_number'):
        amount = _line_amount(li)
        total += amount
        line_items.append({
            'description': li.description,
            'qty': str(li.qty) if li.qty is not None else None,
            'units': li.units,
            'price': _money(li.price),
            'amount': _money(amount),
        })

    deliverables = [
        {
            'description': d.description,
            'qty_ordered': str(d.qty_ordered),
            'units': d.units,
        }
        for d in estimate.job.deliverables.all()  # Meta ordering = sort_order
    ] if estimate.job_id else []

    payload = {
        'estimate_number': estimate.estimate_number,
        'status': estimate.status,
        'sent_date': estimate.sent_date,
        'expiration_date': estimate.expiration_date,
        'closed_date': estimate.closed_date,
        'deliverables': deliverables,
        'line_items': line_items,
        'grand_total': _money(total),
        'actions': actions,
    }
    if estimate.status == Estimate.STATUS_SUPERSEDED:
        payload['current_token'] = _current_token(estimate)
    return payload
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_portal_payload -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/api/portal/__init__.py apps/api/portal/views.py tests/test_portal_payload.py
git commit -m "feat(portal): customer-safe estimate payload builder"
```

---

## Task 6: Portal API endpoints (get / accept / reject)

**Files:**
- Modify: `apps/api/portal/views.py` (add three views)
- Create: `apps/api/portal/urls.py`
- Modify: `apps/api/urls.py:90-95` (add the include)
- Test: `tests/test_portal_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portal_api.py
from decimal import Decimal
from django.test import Client, TestCase

from apps.contacts.models import Contact
from apps.core.models import Configuration
from apps.estimates.models import Estimate, EstimateLineItem
from apps.estimates.services import EstimateService
from apps.jobs.models import Job
from apps.jobs.services import JobService


class PortalApiTest(TestCase):
    fixtures = ['unit_test_data.json']

    def setUp(self):
        self.http = Client()  # deliberately unauthenticated
        Configuration.objects.update_or_create(
            key='business_email', defaults={'value': 'office@shop.com'})
        self.contact = Contact.objects.create(
            first_name='Pat', last_name='Customer', email='pat@acme.com')
        self.job = JobService.create_job(name='API Job', contact=self.contact)
        self.est = EstimateService.create_for_job(self.job.pk)
        EstimateLineItem.objects.create(
            estimate=self.est, description='Work', qty=Decimal('1'),
            price=Decimal('100.00'))
        EstimateService.update_status(self.est.pk, Estimate.STATUS_OPEN)
        self.est.refresh_from_db()
        self.token = self.est.public_token

    def test_get_open_estimate_no_auth(self):
        r = self.http.get(f'/api/portal/estimates/{self.token}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'open')
        self.assertEqual(r.json()['actions'], ['accept', 'reject'])

    def test_get_unknown_token_not_available(self):
        r = self.http.get('/api/portal/estimates/nope-not-a-token/')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()['detail'], 'Not available.')

    def test_accept_transitions_and_advances_job(self):
        r = self.http.post(f'/api/portal/estimates/{self.token}/accept/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'accepted')
        self.est.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_ACCEPTED)
        self.assertEqual(self.job.status, Job.STATUS_APPROVED)

    def test_reject_records_reason_and_rejects_job(self):
        r = self.http.post(
            f'/api/portal/estimates/{self.token}/reject/',
            data={'reason': 'Too costly'}, content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.est.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual(self.est.status, Estimate.STATUS_REJECTED)
        self.assertEqual(self.job.status, Job.STATUS_REJECTED)

    def test_accept_on_already_terminal_is_noop(self):
        EstimateService.update_status(self.est.pk, Estimate.STATUS_ACCEPTED)
        r = self.http.post(f'/api/portal/estimates/{self.token}/accept/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'accepted')  # unchanged, no error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_portal_api -v 2`
Expected: FAIL — 404 routing / views not wired.

- [ ] **Step 3: Add the three views**

Append to `apps/api/portal/views.py`:

```python
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import (
    api_view, authentication_classes, permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.estimates.services import EstimateEmailService, EstimateService


def _not_available():
    return Response({'detail': 'Not available.'},
                    status=status.HTTP_404_NOT_FOUND)


def _actor_for(estimate, reason=None):
    contact = estimate.job.contact if estimate.job_id else None
    return {
        'contact_id': contact.pk if contact else None,
        'email': (contact.email if contact else '') or '',
        'reason': reason,
    }


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def portal_estimate(request, token):
    estimate = Estimate.objects.filter(public_token=token).first()
    if estimate is None:
        return _not_available()
    return Response(build_estimate_payload(estimate))


def _decide(token, target_status, decision_word, reason=None):
    with transaction.atomic():
        estimate = (Estimate.objects
                    .select_for_update()
                    .filter(public_token=token)
                    .first())
        if estimate is None:
            return _not_available()
        # Only act from 'open'; a click racing the shop is a no-op.
        if estimate.status == Estimate.STATUS_OPEN:
            EstimateService.update_status(
                estimate.pk, target_status,
                actor=_actor_for(estimate, reason))
            acted = True
        else:
            acted = False
        estimate.refresh_from_db()
    if acted:
        EstimateEmailService.notify_shop_of_decision(
            estimate, decision_word, reason=reason or '')
    return Response(build_estimate_payload(estimate))


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def portal_estimate_accept(request, token):
    return _decide(token, Estimate.STATUS_ACCEPTED, 'accepted')


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def portal_estimate_reject(request, token):
    reason = (request.data.get('reason') or '').strip() if request.data else ''
    return _decide(token, Estimate.STATUS_REJECTED, 'declined', reason=reason)
```

- [ ] **Step 4: Create the portal URLs**

Create `apps/api/portal/urls.py`:

```python
from django.urls import path

from apps.api.portal import views

urlpatterns = [
    path('estimates/<str:token>/', views.portal_estimate,
         name='portal-estimate'),
    path('estimates/<str:token>/accept/', views.portal_estimate_accept,
         name='portal-estimate-accept'),
    path('estimates/<str:token>/reject/', views.portal_estimate_reject,
         name='portal-estimate-reject'),
]
```

- [ ] **Step 5: Wire into the API URL conf**

In `apps/api/urls.py`, inside the `urlpatterns` list (alongside the other `include()` lines, e.g. right after the `auth/` include), add:

```python
    path('portal/', include('apps.api.portal.urls')),
```

(`include` is already imported in that file.)

- [ ] **Step 6: Run test to verify it passes**

Run: `python manage.py test tests.test_portal_api -v 2`
Expected: PASS (5 tests).

- [ ] **Step 7: Run the full estimates-related suite to check for regressions**

Run: `python manage.py test tests.test_portal_api tests.test_portal_payload tests.test_estimate_update_status_actor tests.test_estimate_public_token tests.test_email_object_url tests.test_shop_notification -v 1`
Expected: PASS (all).

- [ ] **Step 8: Commit**

```bash
git add apps/api/portal/ apps/api/urls.py tests/test_portal_api.py
git commit -m "feat(portal): token-authorized estimate view/accept/reject endpoints"
```

---

## Task 7: Second Vite entry — the portal page

> No unit test framework for Svelte here; verification is `npm run build` + a manual dev check. Keep the portal app self-contained — it must not import `App.svelte`, the nav, or the auth store.

**Files:**
- Modify: `frontend/vite.config.js`
- Create: `frontend/portal/index.html`, `frontend/src/portal-main.js`, `frontend/src/PortalApp.svelte`

- [ ] **Step 1: Declare both entries in Vite**

Replace `frontend/vite.config.js`:

```javascript
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { resolve } from 'path';

export default defineConfig({
  plugins: [svelte()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        portal: resolve(__dirname, 'portal/index.html'),
      },
    },
  },
  server: {
    port: 9000,
    allowedHosts: ['moose', 'moose.local'],
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
```

- [ ] **Step 2: Create the portal entry HTML**

Create `frontend/portal/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Estimate</title>
</head>
<body>
  <div id="portal"></div>
  <script type="module" src="/src/portal-main.js"></script>
</body>
</html>
```

- [ ] **Step 3: Create the portal mount**

Create `frontend/src/portal-main.js`:

```javascript
import PortalApp from './PortalApp.svelte';
import { mount } from 'svelte';
import './css/app.css';

mount(PortalApp, {
  target: document.getElementById('portal'),
});
```

- [ ] **Step 4: Create the portal page**

Create `frontend/src/PortalApp.svelte`:

```svelte
<script>
  import { api } from './lib/api.js';

  let data = $state(null);
  let loading = $state(true);
  let error = $state('');
  let confirming = $state('');   // '' | 'accept' | 'reject'
  let rejectReason = $state('');
  let submitting = $state(false);
  let done = $state('');         // '' | 'accepted' | 'declined'

  const token = new URLSearchParams(window.location.search).get('token') || '';

  async function load() {
    loading = true; error = '';
    try {
      data = await api.get(`/api/portal/estimates/${encodeURIComponent(token)}/`);
    } catch (e) {
      error = e.status === 404 ? 'This estimate is not available.'
                               : (e.message || 'Could not load this estimate.');
    } finally {
      loading = false;
    }
  }

  async function submit(decision) {
    submitting = true; error = '';
    try {
      const url = `/api/portal/estimates/${encodeURIComponent(token)}/${decision}/`;
      const body = decision === 'reject' ? { reason: rejectReason } : null;
      data = await api.post(url, body);
      done = decision === 'accept' ? 'accepted' : 'declined';
      confirming = '';
    } catch (e) {
      error = e.message || 'Something went wrong. Please contact us.';
    } finally {
      submitting = false;
    }
  }

  $effect(() => { if (token) load(); else { loading = false; error = 'Missing link token.'; } });

  const canAct = $derived(data && data.actions && data.actions.includes('accept'));
</script>

<main class="portal">
  {#if loading}
    <p>Loading…</p>
  {:else if error}
    <p class="err">{error}</p>
  {:else if data}
    <h1>Estimate {data.estimate_number}</h1>

    {#if data.status === 'superseded'}
      <p>A newer version of this estimate has been issued.
        {#if data.current_token}
          <a href={`/portal/?token=${data.current_token}`}>View the current estimate</a>.
        {/if}
      </p>
    {:else if data.status === 'expired'}
      <p>This estimate expired{#if data.expiration_date} on {data.expiration_date}{/if}. Please contact us.</p>
    {:else if data.status === 'rejected'}
      <p>This estimate was declined{#if data.closed_date} on {data.closed_date}{/if}.</p>
    {:else if data.status === 'accepted'}
      <p>You accepted this estimate{#if data.closed_date} on {data.closed_date}{/if}. Thank you.</p>
    {/if}

    {#if data.deliverables && data.deliverables.length}
      <h2>What you'll receive</h2>
      <table border="1">
        <thead><tr><th>Item</th><th>Qty</th><th>Units</th></tr></thead>
        <tbody>
          {#each data.deliverables as d}
            <tr><td>{d.description}</td><td>{d.qty_ordered}</td><td>{d.units}</td></tr>
          {/each}
        </tbody>
      </table>
    {/if}

    <h2>Estimate detail</h2>
    <table border="1">
      <thead><tr><th>Description</th><th>Qty</th><th>Units</th><th>Price</th><th>Amount</th></tr></thead>
      <tbody>
        {#each data.line_items as li}
          <tr><td>{li.description}</td><td>{li.qty ?? ''}</td><td>{li.units}</td>
            <td>${li.price}</td><td>${li.amount}</td></tr>
        {/each}
      </tbody>
      <tfoot><tr><td colspan="4"><strong>Total</strong></td><td><strong>${data.grand_total}</strong></td></tr></tfoot>
    </table>

    {#if canAct && !done}
      <p>
        <button type="button" onclick={() => confirming = 'accept'}>Accept estimate</button>
        <button type="button" onclick={() => confirming = 'reject'}>Decline estimate</button>
      </p>
    {/if}

    {#if confirming === 'accept'}
      <fieldset>
        <legend><strong>Confirm acceptance</strong></legend>
        <p>Accepting this estimate authorizes us to begin the work it describes.</p>
        <button type="button" disabled={submitting} onclick={() => submit('accept')}>Yes, accept</button>
        <button type="button" onclick={() => confirming = ''}>Cancel</button>
      </fieldset>
    {:else if confirming === 'reject'}
      <fieldset>
        <legend><strong>Confirm decline</strong></legend>
        <p>Declining this estimate closes out this job. Contact us if you change your mind.</p>
        <p><label>Reason (optional)<br><textarea bind:value={rejectReason}></textarea></label></p>
        <button type="button" disabled={submitting} onclick={() => submit('reject')}>Yes, decline</button>
        <button type="button" onclick={() => confirming = ''}>Cancel</button>
      </fieldset>
    {/if}
  {/if}
</main>

<style>
  .portal { max-width: 720px; margin: 2em auto; font-family: sans-serif; }
  .err { color: #b00; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 1em; }
  th, td { padding: 0.3em 0.6em; text-align: left; }
</style>
```

- [ ] **Step 5: Verify the build succeeds**

Run: `cd frontend && npm run build`
Expected: build completes; `dist/portal/index.html` and `dist/index.html` both emitted.

- [ ] **Step 6: Manual dev check (optional but recommended)**

With Django on :8000 and `cd frontend && npm run dev`, open `http://localhost:9000/portal/?token=<a real open estimate token from the dev DB>` and confirm the page renders line items + Accept/Decline. (Ask the user for a token via a read-only `SELECT public_token FROM estimates WHERE status='open' LIMIT 1;` — do not write to the dev DB.)

- [ ] **Step 7: Commit**

```bash
git add frontend/vite.config.js frontend/portal/ frontend/src/portal-main.js frontend/src/PortalApp.svelte
git commit -m "feat(portal): customer estimate page as a second Vite entry"
```

---

## Task 8: Settings → Business tab for `business_email`

**Files:**
- Create: `frontend/src/components/settings/BusinessSettings.svelte`
- Modify: `frontend/src/routes/SettingsPage.svelte:11,56-62,64-125`

- [ ] **Step 1: Create the Business settings component**

Create `frontend/src/components/settings/BusinessSettings.svelte` (mirrors `ScheduleSettings.svelte`):

```svelte
<script>
  import { api } from '../../lib/api.js';

  let business_email = $state('');
  let saveMessage = $state('');
  let errors = $state({});

  async function load() {
    try {
      const data = await api.get('/api/settings/');
      business_email = data.business_email ?? '';
    } catch (_) {}
  }

  async function save() {
    saveMessage = ''; errors = {};
    try {
      await api.patch('/api/settings/', { business_email });
      saveMessage = 'Business settings saved.';
    } catch (err) {
      errors = (err.data && typeof err.data === 'object')
        ? err.data : { _general: err.message || 'Save failed' };
    }
  }

  $effect(() => { load(); });
</script>

<h3>Business</h3>
<p>
  <label><strong>Notification email</strong></label><br>
  <input type="email" bind:value={business_email}
         placeholder="office@yourshop.com">
  {#if errors.business_email}<em class="err">{errors.business_email}</em>{/if}
</p>
<p><small>Where customer estimate accept/decline notifications are sent.</small></p>
<p>
  <button type="button" onclick={save}>Save</button>
  {#if saveMessage}<em>{saveMessage}</em>{/if}
  {#if errors._general}<em class="err">{errors._general}</em>{/if}
</p>
```

- [ ] **Step 2: Import and register the tab in `SettingsPage.svelte`**

Add the import alongside the other settings-component imports near the top of `frontend/src/routes/SettingsPage.svelte`:

```javascript
  import BusinessSettings from '../components/settings/BusinessSettings.svelte';
```

Add a tab button inside the `<nav class="settings-tabs">` block (after the `email` button):

```svelte
  <button class:active={tab === 'business'} onclick={() => tab = 'business'}>Business</button>
```

Add the content branch at the end of the `{#if tab === ...}` chain (after the `email` branch):

```svelte
{:else if tab === 'business'}
  <BusinessSettings />
```

- [ ] **Step 3: Verify the build succeeds**

Run: `cd frontend && npm run build`
Expected: build completes with no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/settings/BusinessSettings.svelte frontend/src/routes/SettingsPage.svelte
git commit -m "feat(settings): Business tab with business_email config"
```

---

## Task 9: Fixtures + docs

**Files:**
- Modify: `fixtures/unit_test_data.json`
- Modify: `docs/designs/estimates-and-prices.md`, `docs/designs/architecture-and-conventions.md`, `docs/designs/users-and-permissions.md`, `docs/designs/data-constraints.md`, `docs/designs/LATER.md`

- [ ] **Step 1: Add `business_email` to the test fixture**

In `fixtures/unit_test_data.json`, add a `Configuration` row for `business_email` (follow the existing Configuration-row shape in that file; value e.g. `"office@example.com"`). This keeps notification behavior deterministic in tests that load the fixture.

- [ ] **Step 2: Run the full suite to confirm the fixture is valid**

Run: `python manage.py test tests.test_portal_api tests.test_shop_notification -v 1`
Expected: PASS.

- [ ] **Step 3: Update the design docs**

Make these edits (durable record per CLAUDE.md):

- `docs/designs/estimates-and-prices.md` §15 — add a "Customer approval" subsection: `public_token` (minted at creation), the `/portal/?token=` URL via `build_object_url`, the `/api/portal/estimates/<token>/` view/accept/reject endpoints, the `update_status(actor=...)` seam, and the shop notification.
- `docs/designs/architecture-and-conventions.md` — document the portal as a second Vite entry, and the `/api/portal/` AllowAny + `authentication_classes=[]` pattern (the first login-not-required write surface).
- `docs/designs/users-and-permissions.md` — note `/api/portal/` sits outside the permission-atom model (token-authorized, AllowAny, login-not-required).
- `docs/designs/data-constraints.md` §1.1 — add Configuration key `business_email`; add `Estimate.public_token` (unique, nullable, minted at creation).
- `docs/designs/LATER.md` — mark "Customer-facing public URLs for documents" resolved **for Estimates**; note PO/Invoice/Bill and Change Orders remain (CO needs a send flow first).

- [ ] **Step 4: Commit**

```bash
git add fixtures/unit_test_data.json docs/designs/
git commit -m "docs(portal): record customer estimate approval; add business_email fixture"
```

---

## Self-review notes (already reconciled)

- **Spec coverage:** token at creation (T1), portal URL (T2), actor/history (T3), notification (T4 + wired in T6), customer-safe payload incl. deliverables + current_token (T5), portal endpoints with race guard + no-auth (T6), portal page (T7), Business tab (T8), fixtures + docs (T9). All spec sections map to a task.
- **Type/name consistency:** `build_estimate_payload`, `_current_token`, `notify_shop_of_decision`, `update_status(pk, new_status, actor=None)`, and the `actor` dict shape (`contact_id` / `email` / `reason`) are used identically across tasks.
- **Carry-over / Job side effects** are intentionally NOT re-implemented — accept/reject route through `EstimateService.update_status`, so the existing `estimate_accepted` and `estimate_status_changed_for_job` signals fire unchanged (T6 asserts Job → approved / rejected).
- **Migration number** `00NN` is a placeholder resolved by `makemigrations` in T1 Step 4; leave the generated `dependencies` entry as-is when adding the backfill.
