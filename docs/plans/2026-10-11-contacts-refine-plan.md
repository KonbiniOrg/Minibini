# Contacts Refine (phone lists + active/inactive status) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed phone columns on Contact and Business with an ordered phone list, add an active/inactive status to both with deactivation rules, a freeze on records that point at inactive parties, and two-way QBO status sync.

**Architecture:** Model + migration + fixture fold first (Phase A), then the status rules and freeze guards in the service layer (Phase B), then the SPA (Phase C), then QBO push/pull as the last, separately shippable phase (Phase D). Every rule lives in a service; viewsets stay thin. The freeze guard mirrors the existing `_assert_job_not_on_hold` helper and its call sites.

**Tech Stack:** Django 5.2 / DRF / MySQL (JSONField), Svelte 5 runes + Vitest, Playwright, python-quickbooks 0.9.8.

**Spec:** `docs/plans/2026-10-11-contacts-refine-design.md` — read it first; section numbers below (§3.1, §4.2, …) refer to it.

**Branch:** `feature/contacts-refine` — every commit lands here. Never create another branch or worktree.

## Global Constraints

- Never write to the dev DB: no `migrate`, no `shell` ORM writes, no `loaddata`. Tests only (`python manage.py test <module> --noinput`, foreground, with a timeout). One Django test run at a time. Never judge a piped test run by exit code — read the `OK` / `FAILED` line.
- After the migration lands (Task 1), every full-suite run is WITHOUT `--keepdb`.
- The nealseed/seed.json transform (Task 2) is a one-time, field-level rewrite authorized by RM for this change only. Never regenerate nealseed from source.
- Status constants only (`Job.STATUS_COMPLETED`, never `'completed'`).
- Error contract: services raise `ValidationError('<sentence>')` or `ValidationError({'field': ['msg']})`; viewsets do not catch-and-reshape except for the existing 409 duplicate flow. All DELETEs return 200 + JSON.
- Phone entry shape is exactly `{"number": str, "label": str}`; first entry is primary; `phones_digits` is never exposed by any serializer.
- `is_active` is read-only through serializers; only `ContactService.deactivate_*` / `reactivate_*` flip it.
- Open-record definitions (§4.1): job open = draft/submitted/approved/in_progress/work_complete; invoice open = draft/open/partly-paid; PO open = draft/issued/partly_received.
- User-visible text: "timeslip" never "blep"; no "wizard".
- Links navigate, buttons act; no blur-saves; confirm only the business deactivation (RM decision) and deletes.
- Frontend errors go through `triageError` to `FieldError` / `FormMessage` / overlay.
- `__init__.py` files stay empty. Never call `.delete()` on a line item directly. Never `QuerySet.update()` where `save()` has side effects (history, default-contact upkeep).
- E2E specs ship with the user-reachable flows (Task 14). Pure-backend tasks are exempt.
- Docs in `docs/designs/` are updated in Task 15 (and Task 19 for QBO) — same branch, before the final suite run.

## Review Focus

Inputs the spec implies but no single task's tests exercise by default — each line names the owning task that adds the pinned test:

1. **A `phones` payload with a non-string number (e.g. `{"number": 5551234}`)** must be coerced or rejected with a field error, never stored as an int that later breaks `strip_phone`. → Task 1 (`clean_phones` coerces via `str()` and tests it).
2. **PATCHing a job with `{"contact": <same inactive contact>}`** (no real change) must still be refused — the carve-out requires the NEW contact to be active. → Task 8.
3. **Deactivating a contact whose business is already inactive** (can't happen via the API since the contact is already inactive, but can via import or a stale tab) must be a no-op, not an error. → Task 5.
4. **`?status=bogus`** on the list endpoints must fall back to the default (active) rather than 500 or return everything. → Task 6.
5. **A QBO snapshot pulled before this change has no `active` key on its rows**; suggestions must treat a missing key as active. → Task 18.

---

## File Structure

**Backend**
- `apps/contacts/models.py` — `strip_phone`, `clean_phones`, `phones_digits_for`, new fields, `phone()` on both models.
- `apps/contacts/migrations/0002_phones_and_is_active.py` — add fields, fold, drop old columns.
- `apps/contacts/services.py` — `OPEN_*_STATUSES`, blockers, deactivate/reactivate/impact, `assert_active`, `add_note`; `TagService` guards.
- `apps/api/contacts/serializers.py`, `apps/api/contacts/views.py` — `phones`, `is_active`, `phone`, `?status=`, new actions.
- `apps/api/search/views.py`, `apps/search/services.py` — `phone`/`is_active`, `phones_digits` matching.
- `apps/jobs/services.py` — `_assert_job_not_frozen`, `JobService.assert_mutable`, carve-out in `update_job`, create guard.
- `apps/purchasing/services.py` — `_assert_po_not_frozen`, carve-out in `update_po`, create guard.
- `apps/estimates/services.py`, `apps/estimates/change_order_service.py`, `apps/deliverables/services.py`, `apps/invoicing/services.py`, `apps/inventory/services.py` — guard call sites.
- `apps/api/jobs/serializers.py`, `apps/api/purchasing/serializers.py` — `contact_is_active` etc.
- `apps/qbo/services.py` — phone source, `set_active` on customer + new vendor class.
- `apps/qbo/import_services.py` — phone append, inactive pull, suggestion states, commit actions.
- `apps/core/management/commands/validate_data.py` — drop the phone check.
- `nealsdata/converter/build.py` — emit `phones` / `is_active`.

**Frontend**
- New: `components/contacts/PhoneListEditor.svelte`, `components/FrozenPartyBanner.svelte`, `components/ChangeContactModal.svelte`.
- Modified: `ContactForm`, `BusinessForm`, `ContactDetail`, `BusinessDetail`, `ContactList`, `BusinessList`, `CustomerActivity`, `CustomerHeader`, `DuplicateContactNotice`, `DuplicateBusinessNotice`, `ContactFormModal`, `BusinessFormModal`, `EmailCreateJobModal`, `SenderResolutionForm`, `lib/email.js`, `routes/Search.svelte`, `routes/contacts/ContactListPage.svelte`, `routes/contacts/ContactDetailPage.svelte`, `routes/contacts/BusinessDetailPage.svelte`, `components/ContactPicker.svelte`, `components/jobs/JobHeader.svelte`, `components/purchaseorders/PurchaseOrderDetail.svelte`, `components/qboimport/ContactsImportPanel.svelte`, `css/app.css`.

**Tests**
- Backend: `tests/test_contacts_phones.py` (new), `tests/test_contacts_status.py` (new), `tests/test_api_contacts_status.py` (new), `tests/test_api_inactive_party_freeze.py` (new), `tests/test_qbo_status_sync.py` (new), plus edits to every existing test that names an old phone field.
- Vitest: new tests beside the new components; edits to the contacts/jobs/purchaseorders/qboimport tests that name old fields.
- Playwright: `e2e/specs/contacts/status.spec.js`, `e2e/specs/contacts/phones.spec.js`, `e2e/specs/contacts/frozen-job.spec.js`, `e2e/specs/contacts/import-status.spec.js`.

---

# Phase A — Phones and the data model

### Task 1: Model fields, `clean_phones`, `phone()`, migration

**Files:**
- Modify: `apps/contacts/models.py`
- Create: `apps/contacts/migrations/0002_phones_and_is_active.py`
- Modify: `apps/core/management/commands/validate_data.py:178-179`
- Test: `tests/test_contacts_phones.py` (new)

**Interfaces:**
- Produces: `apps.contacts.models.strip_phone(number: str) -> str`; `clean_phones(value) -> list[dict]` (raises `ValidationError({'phones': [...]})`); `phones_digits_for(phones) -> str`; `Contact.phones`, `Contact.phones_digits`, `Contact.is_active`, `Contact.phone()`; same three fields + `phone()` on `Business`.
- Consumed by every later task.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_contacts_phones.py
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import (
    Business, Contact, clean_phones, phones_digits_for, strip_phone,
)


class StripPhoneTest(TestCase):
    def test_strips_spaces_dashes_dots_parens_plus(self):
        self.assertEqual(strip_phone('+1 (555) 123-45.67'), '15551234567')

    def test_keeps_letters_so_extensions_match_as_typed(self):
        self.assertEqual(strip_phone('555-1234 x12'), '5551234x12')

    def test_none_is_empty(self):
        self.assertEqual(strip_phone(None), '')


class CleanPhonesTest(TestCase):
    def test_empty_and_none_become_empty_list(self):
        self.assertEqual(clean_phones(None), [])
        self.assertEqual(clean_phones([]), [])
        self.assertEqual(clean_phones(''), [])

    def test_normalizes_entries_and_drops_unknown_keys(self):
        out = clean_phones([{'number': ' 555-0100 ', 'label': ' cell ', 'x': 1},
                            {'number': '555-0200'}])
        self.assertEqual(out, [{'number': '555-0100', 'label': 'cell'},
                               {'number': '555-0200', 'label': ''}])

    def test_coerces_non_string_number(self):
        self.assertEqual(clean_phones([{'number': 5550100}]),
                         [{'number': '5550100', 'label': ''}])

    def test_rejects_non_list(self):
        with self.assertRaises(ValidationError) as cm:
            clean_phones({'number': '1'})
        self.assertIn('phones', cm.exception.message_dict)

    def test_rejects_entry_without_number(self):
        with self.assertRaises(ValidationError) as cm:
            clean_phones([{'label': 'cell'}])
        self.assertIn('Phone entry 1 needs a number.', cm.exception.message_dict['phones'][0])

    def test_rejects_non_dict_entry(self):
        with self.assertRaises(ValidationError):
            clean_phones(['555-0100'])

    def test_rejects_over_50_chars(self):
        with self.assertRaises(ValidationError):
            clean_phones([{'number': '5' * 51}])

    def test_digits_join(self):
        self.assertEqual(
            phones_digits_for([{'number': '(555) 123-4567', 'label': ''},
                               {'number': '555-9999 x12', 'label': 'work'}]),
            '5551234567 5559999x12')


class ContactPhonesModelTest(TestCase):
    def test_contact_with_no_phones_is_valid(self):
        c = Contact(first_name='A', last_name='B', email='a@b.test')
        c.full_clean()  # no "at least one phone" error any more
        c.save()
        self.assertEqual(c.phones, [])
        self.assertEqual(c.phone(), '')
        self.assertEqual(c.phones_digits, '')
        self.assertTrue(c.is_active)

    def test_save_normalizes_phones_and_maintains_digits(self):
        c = Contact.objects.create(first_name='A', last_name='B', email='a2@b.test',
                                   phones=[{'number': ' (555) 010-0 ', 'label': 'cell'}])
        c.refresh_from_db()
        self.assertEqual(c.phones, [{'number': '(555) 010-0', 'label': 'cell'}])
        self.assertEqual(c.phones_digits, '5550100')
        self.assertEqual(c.phone(), '(555) 010-0')

    def test_first_entry_is_primary(self):
        c = Contact(first_name='A', last_name='B', email='a3@b.test',
                    phones=[{'number': '1', 'label': 'home'}, {'number': '2', 'label': 'cell'}])
        self.assertEqual(c.phone(), '1')

    def test_full_clean_reports_phones_field_error(self):
        c = Contact(first_name='A', last_name='B', email='a4@b.test', phones=[{'label': 'x'}])
        with self.assertRaises(ValidationError) as cm:
            c.full_clean()
        self.assertIn('phones', cm.exception.message_dict)


class BusinessPhonesModelTest(TestCase):
    def test_business_phones_and_flag(self):
        dc = Contact.objects.create(first_name='D', last_name='C', email='dc@b.test')
        b = Business.objects.create(business_name='Acme', default_contact=dc,
                                    phones=[{'number': '555-0100', 'label': 'main'},
                                            {'number': '555-0200', 'label': 'A/P'}])
        b.refresh_from_db()
        self.assertEqual(b.phone(), '555-0100')
        self.assertEqual(b.phones_digits, '5550100 5550200')
        self.assertTrue(b.is_active)

    def test_business_phones_excluded_digits_from_history(self):
        from apps.core.models import CrmHistory
        dc = Contact.objects.create(first_name='D', last_name='C', email='dc2@b.test')
        b = Business.objects.create(business_name='Acme2', default_contact=dc)
        b.phones = [{'number': '555-0100', 'label': ''}]
        b.save()
        entry = CrmHistory.objects.filter(object_type='business', object_id=b.pk,
                                          entry_type='change').order_by('-pk').first()
        self.assertIsNotNone(entry)
        self.assertIn('phones', entry.changes)
        self.assertNotIn('phones_digits', entry.changes)
```

If `CrmHistory`'s change-entry type name differs, check `apps/core/history.py` for the `entry_type` the decorator writes and use that string.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `timeout 600 python manage.py test tests.test_contacts_phones --noinput`
Expected: ImportError on `clean_phones` (module has no such name).

- [ ] **Step 3: Add the helpers and fields to the models**

At the top of `apps/contacts/models.py` (after the imports):

```python
import re

PHONE_STRIP_RE = re.compile(r'[\s\-.()+]')
PHONE_PART_MAX = 50


def strip_phone(number):
    """Spaces, dashes, dots, parens, plus removed — the search key for a
    number. Letters survive so an extension typed as 'x12' matches as
    typed (same rule the contacts list search has always used)."""
    return PHONE_STRIP_RE.sub('', str(number or ''))


def clean_phones(value):
    """Normalize a phones list: [{'number': str, 'label': str}, ...].
    Returns a fresh list; raises a field-keyed ValidationError on shape
    problems so the API renders it under the phones editor."""
    if value in (None, ''):
        return []
    if not isinstance(value, list):
        raise ValidationError({'phones': ['Phones must be a list of {number, label} entries.']})
    out = []
    for i, entry in enumerate(value, start=1):
        if not isinstance(entry, dict):
            raise ValidationError({'phones': [f'Phone entry {i} must be an object with number and label.']})
        number = str(entry.get('number') if entry.get('number') is not None else '').strip()
        label = str(entry.get('label') if entry.get('label') is not None else '').strip()
        if not number:
            raise ValidationError({'phones': [f'Phone entry {i} needs a number.']})
        if len(number) > PHONE_PART_MAX or len(label) > PHONE_PART_MAX:
            raise ValidationError({'phones': [
                f'Phone entry {i}: number and label are limited to {PHONE_PART_MAX} characters.']})
        out.append({'number': number, 'label': label})
    return out


def phones_digits_for(phones):
    return ' '.join(strip_phone(p['number']) for p in phones)
```

Contact: replace the three `*_number` fields with

```python
    phones = models.JSONField(default=list, blank=True)
    phones_digits = models.CharField(max_length=1000, blank=True, default='', editable=False)
    is_active = models.BooleanField(default=True)
```

Change the decorator to `@history(exclude=['phones_digits'])`. In `Contact.clean()` delete the "at least one phone number" block and add, right after the email normalization, `self.phones = clean_phones(self.phones)`. In `Contact.save()`, as the first two lines:

```python
        self.phones = clean_phones(self.phones)
        self.phones_digits = phones_digits_for(self.phones)
```

Replace `Contact.phone()` body with:

```python
    def phone(self):
        """Primary number: the first entry, or ''."""
        return self.phones[0]['number'] if self.phones else ''
```

Business: replace `business_phone` with the same three fields; decorator `@history(exclude=['business_id', 'phones_digits'])`; in `clean()` add `self.phones = clean_phones(self.phones)`; in `save()` add the same two normalization lines as the very first statements (before the `our_reference_code` early return); add

```python
    def phone(self):
        """Primary number: the first entry, or ''."""
        return self.phones[0]['number'] if self.phones else ''
```

`validate_data.py`: delete the two lines that check `work_number/mobile_number/home_number`.

- [ ] **Step 4: Generate then hand-edit the migration**

Run: `python manage.py makemigrations contacts -n phones_and_is_active`
It produces AddField ×6 and RemoveField ×4 in one file. Edit the file so the operations are ordered: the six `AddField`s, then a `RunPython`, then the four `RemoveField`s. Insert this above `class Migration`:

```python
import re

PHONE_STRIP_RE = re.compile(r'[\s\-.()+]')


def _digits(phones):
    return ' '.join(PHONE_STRIP_RE.sub('', p['number']) for p in phones)


def fold_forward(apps, schema_editor):
    Contact = apps.get_model('contacts', 'Contact')
    Business = apps.get_model('contacts', 'Business')
    for c in Contact.objects.all().iterator():
        phones = [{'number': n.strip(), 'label': label}
                  for n, label in ((c.work_number, 'work'),
                                   (c.mobile_number, 'mobile'),
                                   (c.home_number, 'home'))
                  if n and n.strip()]
        c.phones = phones
        c.phones_digits = _digits(phones)
        c.save(update_fields=['phones', 'phones_digits'])
    for b in Business.objects.all().iterator():
        phones = ([{'number': b.business_phone.strip(), 'label': ''}]
                  if b.business_phone and b.business_phone.strip() else [])
        b.phones = phones
        b.phones_digits = _digits(phones)
        b.save(update_fields=['phones', 'phones_digits'])


def fold_backward(apps, schema_editor):
    """Best effort: the first entry per legacy label goes back; extra
    entries are lost (documented in the spec, §3.5)."""
    Contact = apps.get_model('contacts', 'Contact')
    Business = apps.get_model('contacts', 'Business')
    for c in Contact.objects.all().iterator():
        by_label = {}
        for p in c.phones or []:
            by_label.setdefault(p.get('label', ''), p['number'])
        c.work_number = (by_label.get('work') or '')[:20]
        c.mobile_number = (by_label.get('mobile') or '')[:20]
        c.home_number = (by_label.get('home') or '')[:20]
        c.save(update_fields=['work_number', 'mobile_number', 'home_number'])
    for b in Business.objects.all().iterator():
        b.business_phone = (b.phones[0]['number'] if b.phones else '')[:50]
        b.save(update_fields=['business_phone'])
```

and `migrations.RunPython(fold_forward, fold_backward),` between the adds and the removes. Historical models in `RunPython` don't run `save()` overrides, so the explicit `phones_digits` write is required.

- [ ] **Step 5: Run the new tests**

Run: `timeout 600 python manage.py test tests.test_contacts_phones --noinput`
Expected: `OK`. (Other modules will fail until Task 2 — that is expected; do not run the full suite yet.)

- [ ] **Step 6: Commit**

```bash
git add apps/contacts/models.py apps/contacts/migrations/0002_phones_and_is_active.py apps/core/management/commands/validate_data.py tests/test_contacts_phones.py
git commit -m "feat(contacts): phones list, phones_digits, is_active on Contact and Business; fold migration

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Fixture fold and the test-suite sweep

**Files:**
- Modify: `fixtures/large_datasets/nealseed.json`, `fixtures/playwright/seed.json` (scripted), `fixtures/unit_test_data.json`, `fixtures/contacts_base_data.json` (by hand)
- Modify: every file under `tests/` that names `mobile_number`, `work_number`, `home_number`, or `business_phone` (≈150 files)
- Scratch: `<scratchpad>/fold_fixture_phones.py`, `<scratchpad>/sweep_tests.py` — never committed

**Interfaces:**
- Consumes: Task 1's field names.
- Produces: a green backend suite for the phone change (status-related failures cannot exist yet).

- [ ] **Step 1: Write the fixture fold script in the scratchpad**

```python
# <scratchpad>/fold_fixture_phones.py  — run: python -I fold_fixture_phones.py <path> [<path> ...]
import json, re, sys

STRIP = re.compile(r'[\s\-.()+]')

def digits(phones):
    return ' '.join(STRIP.sub('', p['number']) for p in phones)

def fold(path):
    with open(path) as fh:
        rows = json.load(fh)
    touched = 0
    for r in rows:
        f = r['fields']
        if r['model'] == 'contacts.contact':
            phones = [{'number': n.strip(), 'label': lab}
                      for n, lab in ((f.pop('work_number', ''), 'work'),
                                     (f.pop('mobile_number', ''), 'mobile'),
                                     (f.pop('home_number', ''), 'home'))
                      if n and n.strip()]
        elif r['model'] == 'contacts.business':
            bp = f.pop('business_phone', '') or ''
            phones = [{'number': bp.strip(), 'label': ''}] if bp.strip() else []
        else:
            continue
        f['phones'] = phones
        f['phones_digits'] = digits(phones)
        f['is_active'] = True
        touched += 1
    with open(path, 'w') as fh:
        json.dump(rows, fh, indent=2, ensure_ascii=False)
        fh.write('\n')
    print(path, 'rows touched:', touched)

for p in sys.argv[1:]:
    fold(p)
```

Before running, check how each fixture is indented (`head -c 300 <file>`) and match `indent=` so the diff is only the folded rows. Run it on `nealseed.json` and `seed.json`. Edit `unit_test_data.json` and `contacts_base_data.json` by hand to the same shape (4 contacts + 2 businesses each). Review with `git diff --stat` and spot-check a contact and a business row in each file: only `phones`, `phones_digits`, `is_active` added and the old keys gone.

- [ ] **Step 2: Sweep the backend tests**

Write `<scratchpad>/sweep_tests.py` that, for each `tests/*.py` containing an old field name, rewrites keyword arguments inside a single call with a regex and reports the rest:

```python
import pathlib, re, sys

LABEL = {'work_number': 'work', 'mobile_number': 'mobile', 'home_number': 'home'}
KW = re.compile(r"(work_number|mobile_number|home_number)\s*=\s*('[^']*'|\"[^\"]*\")")
BIZ = re.compile(r"business_phone\s*=\s*('[^']*'|\"[^\"]*\")")

def fix_call(text):
    # Merge all phone kwargs found in a run of text (one call) into one phones=[...]
    found = KW.findall(text)
    if not found:
        return text
    entries = [f"{{'number': {val}, 'label': '{LABEL[k]}'}}" for k, val in found if val.strip('\'"')]
    first = True
    def repl(m):
        nonlocal first
        if first:
            first = False
            return f"phones=[{', '.join(entries)}]" if entries else 'phones=[]'
        return '__DROP__'
    text = KW.sub(repl, text)
    text = re.sub(r",\s*__DROP__", '', text)
    text = text.replace('__DROP__', '')
    return text

for path in pathlib.Path('tests').glob('*.py'):
    src = path.read_text()
    if not re.search(r'work_number|mobile_number|home_number|business_phone', src):
        continue
    out = []
    # process call-by-call: split on ')' boundaries conservatively → simplest is per statement
    for stmt in re.split(r'(?<=\))\n', src):
        stmt = fix_call(stmt)
        stmt = BIZ.sub(lambda m: f"phones=[{{'number': {m.group(1)}, 'label': ''}}]" if m.group(1).strip('\'"') else 'phones=[]', stmt)
        out.append(stmt)
    new = '\n'.join(out)
    if new != src:
        path.write_text(new)
    leftovers = [i + 1 for i, line in enumerate(new.splitlines())
                 if re.search(r'work_number|mobile_number|home_number|business_phone', line)]
    if leftovers:
        print(path, 'manual:', leftovers)
```

Run it, then fix every reported leftover by hand. Typical leftovers and their replacements:
- `self.assertEqual(c.mobile_number, "555-123-4567")` → `self.assertEqual(c.phone(), "555-123-4567")` (or assert the `phones` list).
- API payloads `'mobile_number': '555-000-0000'` → `'phones': [{'number': '555-000-0000', 'label': 'mobile'}]`.
- `test_create_contact_no_phone_raises` in `tests/test_contacts_services.py` → delete (no phone is now valid), replace with `test_create_contact_without_phone_ok`.
- `tests/test_neals_builders.py:281-286` "at least one phone" → leave for Task 3 (it changes with the converter).
- `tests/test_contacts_models_with_fixtures.py` lines 17, 21, 101, 107 → `.phone()`.
- `tests/test_qbo_customer_sync.py` setUp → `phones=[...]`; any assertion on `PrimaryPhone.FreeFormNumber` keeps working through `phone()` after Task 4.

- [ ] **Step 3: Run the affected modules**

Run: `timeout 900 python manage.py test tests.test_contacts_models tests.test_contacts_services tests.test_api_contacts tests.test_contact_list_filters tests.test_contacts_models_with_fixtures tests.test_nealseed_fixture tests.test_default_contact_functionality tests.test_contact_deletion tests.test_contact_business_associations --noinput`
Expected: `OK` except tests that assert on search-by-phone (they go green in Task 4) and the QBO import/sync tests (Task 4). Note each remaining failure's module name in the commit body.

- [ ] **Step 4: Commit**

```bash
git add fixtures tests
git commit -m "test(contacts): fold phone fields in fixtures and the test suite to the phones list

One-time field-level transform of nealseed.json and the Playwright seed (RM-authorized for this change only).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Converter emits the new shape

**Files:**
- Modify: `nealsdata/converter/build.py:480-495` (contact emit), `:540-555` (business emit)
- Modify: `tests/test_neals_builders.py:281-286`
- Regenerate (untracked, local only): `nealsdata/datasets/converted.json`

**Interfaces:**
- Consumes: Task 1 field names.
- Produces: converter output loadable by `tests.test_neals_fixture`.

- [ ] **Step 1: Update the builder test**

Replace the "at least one phone" assertion block with:

```python
        # Every contact has an email and a well-formed phones list with at
        # least one entry (the converter synthesizes 555-555-5555 when the
        # export has none), plus the active flag.
        for ct in contacts:
            self.assertTrue(ct['fields']['email'])
            phones = ct['fields']['phones']
            self.assertIsInstance(phones, list)
            self.assertGreaterEqual(len(phones), 1)
            for p in phones:
                self.assertEqual(set(p), {'number', 'label'})
                self.assertTrue(p['number'])
            self.assertTrue(ct['fields']['is_active'])
            self.assertNotIn('work_number', ct['fields'])
        for b in businesses:
            self.assertEqual(b['fields']['phones'], [])
            self.assertTrue(b['fields']['is_active'])
```

- [ ] **Step 2: Run it to see it fail**

Run: `timeout 600 python manage.py test tests.test_neals_builders --noinput`
Expected: KeyError `'phones'`.

- [ ] **Step 3: Change the two emit sites**

In `_emit_contact` replace the three `*_number` keys with:

```python
        'phones': [{'number': n[:50], 'label': lab}
                   for n, lab in ((work, 'work'), (mobile, 'mobile')) if n],
        'phones_digits': '',   # Model.save() recomputes on first save; loaddata rows carry it explicitly below
        'is_active': True,
```

and compute `phones_digits` properly instead of `''`: add at the top of `build.py` `from apps.contacts.models import strip_phone` is NOT allowed (the converter is standalone) — copy the regex: `_PHONE_STRIP = re.compile(r'[\s\-.()+]')` and set `'phones_digits': ' '.join(_PHONE_STRIP.sub('', p['number']) for p in phones)` (build the `phones` list in a local first). In the business emit replace `'business_phone': ''` with `'phones': [], 'phones_digits': '', 'is_active': True`.

- [ ] **Step 4: Regenerate and test**

Run: `python nealsdata/convert_neals_data.py` (writes the untracked `datasets/converted.json`), then
`timeout 900 python manage.py test tests.test_neals_builders tests.test_neals_fixture tests.test_neals_loaders tests.test_neals_parsing --noinput`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add nealsdata/converter/build.py tests/test_neals_builders.py
git commit -m "feat(nealsdata): converter emits phones list and is_active

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: API, search, and QBO phone plumbing

**Files:**
- Modify: `apps/api/contacts/serializers.py`, `apps/api/contacts/views.py:64-94` and `:238-246`
- Modify: `apps/api/search/views.py:15-27`, `apps/search/services.py:132-156` and `:699-728`
- Modify: `apps/qbo/services.py:225-228`, `apps/qbo/import_services.py` (five phone sites + helper)
- Test: `tests/test_api_contacts.py`, `tests/test_contact_list_filters.py`, `tests/test_api_search.py`, `tests/test_qbo_import_commit_contacts.py`, `tests/test_qbo_customer_sync.py`

**Interfaces:**
- Produces: `phones` (writable) + `is_active` (read-only) on `ContactSerializer`/`BusinessSerializer`; `phone` (read-only) + `is_active` on `ContactSummarySerializer`, `BusinessSummarySerializer`, `ContactSearchSerializer`, `BusinessSearchSerializer`; `apps.qbo.import_services._merge_qbo_phone(obj, number) -> bool`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_contact_list_filters.py`:

```python
class PhoneSearchTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.c = Contact.objects.create(
            first_name='Pho', last_name='Ne', email='pho@filter.com',
            phones=[{'number': '(555) 777-1234', 'label': 'cell'},
                    {'number': '555-888-0000', 'label': 'work'}])
        dc = Contact.objects.create(first_name='D', last_name='C', email='dc@filter.com')
        self.b = Business.objects.create(
            business_name='Phoneco', default_contact=dc,
            phones=[{'number': '555.999.1111', 'label': 'A/P'}])

    def test_contact_matches_any_entry_ignoring_punctuation(self):
        for q in ('5557771234', '555-777', '888 0000'):
            ids = [r['contact_id'] for r in self.client.get('/api/contacts/', {'search': q}).data['results']]
            self.assertIn(self.c.pk, ids, q)

    def test_business_matches_stripped(self):
        ids = [r['business_id'] for r in self.client.get('/api/businesses/', {'search': '(555) 999'}).data['results']]
        self.assertIn(self.b.pk, ids)

    def test_text_search_still_works(self):
        ids = [r['contact_id'] for r in self.client.get('/api/contacts/', {'search': 'Pho'}).data['results']]
        self.assertIn(self.c.pk, ids)

    def test_phones_digits_not_exposed(self):
        data = self.client.get(f'/api/contacts/{self.c.pk}/').data
        self.assertNotIn('phones_digits', data)
        self.assertEqual(data['phones'][0]['number'], '(555) 777-1234')
        self.assertTrue(data['is_active'])

    def test_is_active_is_read_only(self):
        r = self.client.patch(f'/api/contacts/{self.c.pk}/', {'is_active': False}, format='json')
        self.assertEqual(r.status_code, 200)
        self.c.refresh_from_db()
        self.assertTrue(self.c.is_active)

    def test_bad_phones_payload_is_a_field_error(self):
        r = self.client.patch(f'/api/contacts/{self.c.pk}/', {'phones': [{'label': 'x'}]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('phones', r.data)
```

Add to `tests/test_api_search.py`:

```python
    def test_global_search_matches_phone_ignoring_punctuation(self):
        from apps.contacts.models import Contact
        c = Contact.objects.create(first_name='Glo', last_name='Bal', email='glo@x.com',
                                   phones=[{'number': '(555) 321-7777', 'label': ''}])
        r = self.client.get('/api/search/', {'q': '555-321'})
        self.assertEqual(r.status_code, 200)
        contacts = r.data['results'].get('contacts', [])
        self.assertIn(c.pk, [x['contact_id'] for x in contacts])
        self.assertEqual(contacts[0]['phone'], '(555) 321-7777')
```

(Check the actual response shape in `apps/api/search/views.py` `_serialize_categories` — `results['contacts']` may be a list or `{'items': [...]}`; adjust the assertion to the real key.)

Add to `tests/test_qbo_import_commit_contacts.py`:

```python
class ImportPhoneMergeTest(TestCase):
    def setUp(self):
        from tests.test_qbo_import_state import store_snapshot
        store_snapshot()

    def test_create_puts_qbo_phone_as_sole_entry(self):
        QBOImportCommitService.commit_contacts(_payload())
        b = Business.objects.get(qbo_customer_id='71')
        self.assertEqual(b.phones, [{'number': '555-1000', 'label': 'qbo'}])
        self.assertEqual(b.default_contact.phones, [{'number': '555-1000', 'label': 'qbo'}])

    def test_update_appends_unknown_number_and_skips_known(self):
        QBOImportCommitService.commit_contacts(_payload())
        b = Business.objects.get(qbo_customer_id='71')
        c = b.default_contact
        c.phones = [{'number': '(555) 100-0', 'label': 'cell'}]   # strips to 5551000 == QBO's
        c.save()
        row = dict(_payload()['customers'][0], action='update', phone='555-1000')
        QBOImportCommitService.commit_contacts({'customers': [row], 'vendors': []})
        c.refresh_from_db()
        self.assertEqual(len(c.phones), 1)                       # known → untouched
        row['phone'] = '555-2000'
        QBOImportCommitService.commit_contacts({'customers': [row], 'vendors': []})
        c.refresh_from_db()
        self.assertEqual(c.phones[-1], {'number': '555-2000', 'label': 'qbo'})
```

In `tests/test_qbo_customer_sync.py` add a test that `_build_customer(business)` sets `PrimaryPhone.FreeFormNumber` to `business.phone()` when phones exist and leaves it unset when empty.

- [ ] **Step 2: Run them to see them fail**

Run: `timeout 900 python manage.py test tests.test_contact_list_filters tests.test_api_search tests.test_qbo_import_commit_contacts tests.test_qbo_customer_sync --noinput`
Expected: FAILED (field errors / unknown field `phones` on serializers, AttributeError `business_phone`).

- [ ] **Step 3: Serializers**

`apps/api/contacts/serializers.py`:

```python
class BusinessSummarySerializer(serializers.ModelSerializer):
    phone = serializers.CharField(read_only=True)
    class Meta:
        model = Business
        fields = ['business_id', 'business_name', 'our_reference_code', 'default_contact', 'phone', 'is_active']


class ContactSummarySerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    class Meta:
        model = Contact
        fields = ['contact_id', 'name', 'email', 'phone', 'is_active']
```

`ContactSerializer.Meta.fields`: replace the three phone names with `'phones', 'is_active'`; `read_only_fields = ['contact_id', 'is_active']`. `BusinessSerializer.Meta.fields`: replace `'business_phone'` with `'phones', 'is_active'`; add `'is_active'` to `read_only_fields`. DRF maps `JSONField` automatically; the model's `full_clean()` (run by the services) produces the `{'phones': [...]}` error the handler renders.

`apps/api/search/views.py`: `ContactSearchSerializer` fields → `['contact_id', 'name', 'business_name', 'email', 'phone', 'city', 'is_active']` with `phone = drf_serializers.CharField(read_only=True)`; `BusinessSearchSerializer` → `['business_id', 'business_name', 'our_reference_code', 'business_address', 'phone', 'is_active']` with the same declared field.

- [ ] **Step 4: List search**

`ContactViewSet.get_queryset` — delete the `strip_phone` annotation helper and the `annotate(...)`; keep `phone_search = re.sub(r'[\s\-.()+]', '', search)` (or import `strip_phone` from the models module and use it) and replace the three `_clean` Qs with `q |= Q(phones_digits__icontains=phone_search)`. Remove the now-unused `Replace`/`Value` imports. `BusinessViewSet.get_queryset` search block becomes:

```python
        search = self.request.query_params.get('search', '').strip()
        if search:
            q = (Q(business_name__icontains=search) |
                 Q(our_reference_code__icontains=search) |
                 Q(business_address__icontains=search))
            phone_search = strip_phone(search)
            if phone_search:
                q |= Q(phones_digits__icontains=phone_search)
            qs = qs.filter(q)
```

`apps/search/services.py`: in `search_businesses`, `search_contacts`, and the two within-stored-results blocks, replace each `*_number__icontains=query` / `business_phone__icontains` term with `Q(phones_digits__icontains=strip_phone(query))` (import `strip_phone` from `apps.contacts.models`; when `strip_phone(query)` is empty skip the term so an all-punctuation query doesn't match everything).

- [ ] **Step 5: QBO**

`apps/qbo/services.py` `_build_customer`: `phone = business.phone()` / `if phone:` … `FreeFormNumber = phone`. In `apps/qbo/import_services.py` add near the top:

```python
def _merge_qbo_phone(obj, number):
    """Append QBO's number labeled 'qbo' unless an entry already strips to
    the same digits. Returns True when the list changed (spec §6.5)."""
    from apps.contacts.models import strip_phone
    number = (number or '').strip()
    if not number:
        return False
    key = strip_phone(number)
    if any(strip_phone(p['number']) == key for p in obj.phones):
        return False
    obj.phones = [*obj.phones, {'number': number, 'label': 'qbo'}]
    return True


def _qbo_phones(number):
    number = (number or '').strip()
    return [{'number': number, 'label': 'qbo'}] if number else []
```

Then: the four `Contact.objects.create(... mobile_number=row.get('phone') or '')` / `Business.objects.create(... business_phone=...)` sites become `phones=_qbo_phones(row.get('phone'))`; the update site `if row.get('phone'): contact.mobile_number = row['phone']` becomes `_merge_qbo_phone(contact, row.get('phone'))`; and in the matched-business branch add `_merge_qbo_phone(business, row.get('phone'))` before `business.save()`. (Assign a new list — never mutate `obj.phones` in place — so the history diff sees the change.)

- [ ] **Step 6: Run the tests**

Run: `timeout 900 python manage.py test tests.test_contact_list_filters tests.test_api_search tests.test_api_contacts tests.test_qbo_import_commit_contacts tests.test_qbo_customer_sync tests.test_search_filters --noinput`
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add apps/api/contacts apps/api/search apps/search apps/qbo tests
git commit -m "feat(contacts): phones through the API and search; QBO import merges phones labeled qbo

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```


---

# Phase B — Status rules and the freeze (backend)

### Task 5: Deactivate / reactivate rules in `ContactService`

**Files:**
- Modify: `apps/contacts/services.py`
- Modify: `apps/api/contacts/views.py` (notes / add-tag / remove-tag / set-default-contact delegate to the service guards)
- Test: `tests/test_contacts_status.py` (new)

**Interfaces:**
- Produces (all on `ContactService`): `deactivate_contact(contact, *, push_to_qbo=True) -> Contact`, `reactivate_contact(contact, *, push_to_qbo=True) -> Contact`, `deactivate_business(business, *, push_to_qbo=True) -> Business`, `reactivate_business(business, *, push_to_qbo=True) -> Business`, `deactivate_business_impact(business) -> dict`, `assert_active(obj)`, `add_note(obj, object_type, text) -> HistoryEntry`. Module constants `OPEN_JOB_STATUSES`, `OPEN_INVOICE_STATUSES`, `OPEN_PO_STATUSES`. `push_to_qbo` is accepted now and ignored until Task 17 wires it.
- `TagService.attach/detach` raise when `obj.is_active` is False.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_contacts_status.py
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Business, Contact
from apps.contacts.services import ContactService, TagService
from apps.invoicing.models import Invoice
from apps.jobs.models import Job
from apps.purchasing.models import PurchaseOrder


def make_business(name='Acme', n_contacts=2):
    dc = Contact.objects.create(first_name='Default', last_name=name, email=f'dc-{name}@x.test')
    b = Business.objects.create(business_name=name, default_contact=dc)
    dc.business = b
    dc.save()
    others = [Contact.objects.create(first_name=f'C{i}', last_name=name, email=f'c{i}-{name}@x.test', business=b)
              for i in range(n_contacts - 1)]
    return b, dc, others


def make_job(contact, status):
    import time
    job = Job.objects.create(job_number=f'J-ST-{time.time():.6f}', contact=contact, status=Job.STATUS_DRAFT)
    walk = {
        Job.STATUS_DRAFT: [], Job.STATUS_SUBMITTED: [Job.STATUS_SUBMITTED],
        Job.STATUS_APPROVED: [Job.STATUS_SUBMITTED, Job.STATUS_APPROVED],
        Job.STATUS_IN_PROGRESS: [Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS],
        Job.STATUS_REJECTED: [Job.STATUS_REJECTED],
        Job.STATUS_CANCELLED: [Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_CANCELLED],
        Job.STATUS_COMPLETED: [Job.STATUS_SUBMITTED, Job.STATUS_APPROVED, Job.STATUS_IN_PROGRESS,
                               Job.STATUS_WORK_COMPLETE, Job.STATUS_COMPLETED],
    }[status]
    for s in walk:
        job.status = s
        job.save()
    job.refresh_from_db()
    return job


class DeactivateContactTest(TestCase):
    def test_individual_with_no_records_deactivates(self):
        c = Contact.objects.create(first_name='Solo', last_name='X', email='solo@x.test')
        ContactService.deactivate_contact(c)
        c.refresh_from_db()
        self.assertFalse(c.is_active)

    def test_default_contact_of_active_business_blocked(self):
        b, dc, _ = make_business('Dflt')
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_contact(dc)
        self.assertIn('default contact for Dflt', str(cm.exception))
        dc.refresh_from_db()
        self.assertTrue(dc.is_active)

    def test_non_default_contact_of_active_business_deactivates(self):
        b, dc, (other,) = make_business('Ok')
        ContactService.deactivate_contact(other)
        other.refresh_from_db()
        self.assertFalse(other.is_active)
        b.refresh_from_db()
        self.assertTrue(b.is_active)

    def test_open_job_blocks_and_names_it(self):
        c = Contact.objects.create(first_name='Busy', last_name='X', email='busy@x.test')
        job = make_job(c, Job.STATUS_IN_PROGRESS)
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_contact(c)
        msg = str(cm.exception)
        self.assertIn('1 open job', msg)
        self.assertIn(job.job_number, msg)

    def test_closed_job_does_not_block(self):
        c = Contact.objects.create(first_name='Done', last_name='X', email='done@x.test')
        make_job(c, Job.STATUS_COMPLETED)
        ContactService.deactivate_contact(c)
        c.refresh_from_db()
        self.assertFalse(c.is_active)

    def test_open_invoice_on_closed_job_blocks(self):
        c = Contact.objects.create(first_name='Inv', last_name='X', email='inv@x.test')
        job = make_job(c, Job.STATUS_COMPLETED)
        Invoice.objects.create(job=job, status=Invoice.STATUS_OPEN)
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_contact(c)
        self.assertIn('1 open invoice', str(cm.exception))

    def test_open_po_as_vendor_contact_blocks(self):
        b, dc, (other,) = make_business('Vend')
        PurchaseOrder.objects.create(po_number='PO-ST-1', business=b, contact=other,
                                     status=PurchaseOrder.STATUS_ISSUED)
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_contact(other)
        self.assertIn('1 open PO', str(cm.exception))

    def test_all_blockers_in_one_sentence(self):
        b, dc, _ = make_business('Multi')
        job = make_job(dc, Job.STATUS_DRAFT)
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_contact(dc)
        msg = str(cm.exception)
        self.assertIn('default contact for Multi', msg)
        self.assertIn('1 open job', msg)
        self.assertTrue(msg.startswith('Cannot deactivate'))

    def test_already_inactive_is_noop(self):
        c = Contact.objects.create(first_name='Twice', last_name='X', email='twice@x.test', is_active=False)
        make_job(c, Job.STATUS_DRAFT)          # would block if evaluated
        ContactService.deactivate_contact(c)   # no error
        c.refresh_from_db()
        self.assertFalse(c.is_active)


class ReactivateContactTest(TestCase):
    def test_reactivate_under_inactive_business_blocked(self):
        b, dc, (other,) = make_business('Dead')
        ContactService.deactivate_business(b)
        other.refresh_from_db()
        with self.assertRaises(ValidationError) as cm:
            ContactService.reactivate_contact(other)
        self.assertIn('business Dead is inactive', str(cm.exception))

    def test_reactivate_individual(self):
        c = Contact.objects.create(first_name='Back', last_name='X', email='back@x.test', is_active=False)
        ContactService.reactivate_contact(c)
        c.refresh_from_db()
        self.assertTrue(c.is_active)


class BusinessStatusTest(TestCase):
    def test_deactivate_cascades_and_reactivate_restores_all(self):
        b, dc, (other,) = make_business('Casc')
        other.is_active = False          # individually inactive beforehand
        other.save()
        ContactService.deactivate_business(b)
        for o in (b, dc, other):
            o.refresh_from_db()
        self.assertFalse(b.is_active); self.assertFalse(dc.is_active); self.assertFalse(other.is_active)
        ContactService.reactivate_business(b)
        for o in (b, dc, other):
            o.refresh_from_db()
        self.assertTrue(b.is_active); self.assertTrue(dc.is_active)
        self.assertTrue(other.is_active)   # symmetric cascade (spec §4.5)

    def test_default_contact_rule_does_not_apply_to_business(self):
        b, dc, _ = make_business('NoDflt')
        ContactService.deactivate_business(b)
        b.refresh_from_db()
        self.assertFalse(b.is_active)

    def test_open_job_on_any_contact_blocks(self):
        b, dc, (other,) = make_business('Blk')
        make_job(other, Job.STATUS_APPROVED)
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_business(b)
        self.assertIn('1 open job', str(cm.exception))

    def test_open_vendor_po_blocks(self):
        b, dc, _ = make_business('VendB')
        PurchaseOrder.objects.create(po_number='PO-ST-2', business=b, status=PurchaseOrder.STATUS_DRAFT)
        with self.assertRaises(ValidationError) as cm:
            ContactService.deactivate_business(b)
        self.assertIn('1 open PO', str(cm.exception))

    def test_impact_payload(self):
        b, dc, (other,) = make_business('Imp')
        make_job(dc, Job.STATUS_DRAFT)
        impact = ContactService.deactivate_business_impact(b)
        self.assertEqual(impact['contact_count'], 2)
        self.assertEqual(sorted(impact['contact_names']), sorted([dc.name, other.name]))
        self.assertEqual(len(impact['blockers']), 1)
        self.assertIn('1 open job', impact['blockers'][0])

    def test_history_records_the_flip(self):
        from apps.core.models import CrmHistory
        b, dc, _ = make_business('Hist')
        ContactService.deactivate_business(b)
        entries = CrmHistory.objects.filter(object_type='business', object_id=b.pk)
        self.assertTrue(any('is_active' in (e.changes or {}) for e in entries))


class InactiveEditRefusalTest(TestCase):
    def setUp(self):
        self.c = Contact.objects.create(first_name='Frozen', last_name='X', email='fz@x.test', is_active=False)
        b, dc, _ = make_business('FrozenCo')
        ContactService.deactivate_business(b)
        self.b = b

    def test_update_contact_refused(self):
        with self.assertRaises(ValidationError) as cm:
            ContactService.update_contact(self.c.pk, first_name='New')
        self.assertIn('is inactive', str(cm.exception))

    def test_update_business_refused(self):
        with self.assertRaises(ValidationError):
            ContactService.update_business(self.b.pk, website='https://x.test')

    def test_set_default_contact_refused(self):
        other = Contact.objects.create(first_name='O', last_name='X', email='o@x.test', business=self.b, is_active=False)
        with self.assertRaises(ValidationError):
            ContactService.set_default_contact(self.b.pk, other.pk)

    def test_tags_refused(self):
        with self.assertRaises(ValidationError):
            TagService.attach(self.c, 'vip')
        with self.assertRaises(ValidationError):
            TagService.detach(self.c, 1)

    def test_note_refused(self):
        with self.assertRaises(ValidationError):
            ContactService.add_note(self.c, 'contact', 'hello')

    def test_delete_still_allowed(self):
        ContactService.delete_contact(self.c.pk)
        self.assertFalse(Contact.objects.filter(pk=self.c.pk).exists())
```

`Invoice.objects.create(job=job, status=...)` — check `apps/invoicing/models.py` for other required fields and pass them; if `Invoice.save()` refuses a bare `open` status, create as draft then set status and save.

- [ ] **Step 2: Run to see them fail**

Run: `timeout 600 python manage.py test tests.test_contacts_status --noinput`
Expected: AttributeError `deactivate_contact`.

- [ ] **Step 3: Implement**

In `apps/contacts/services.py` add after the imports:

```python
from apps.core.history import record_history


def _open_statuses():
    from apps.invoicing.models import Invoice
    from apps.jobs.models import Job
    from apps.purchasing.models import PurchaseOrder
    return (
        (Job.STATUS_DRAFT, Job.STATUS_SUBMITTED, Job.STATUS_APPROVED,
         Job.STATUS_IN_PROGRESS, Job.STATUS_WORK_COMPLETE),
        (Invoice.STATUS_DRAFT, Invoice.STATUS_OPEN, Invoice.STATUS_PARTLY_PAID),
        (PurchaseOrder.STATUS_DRAFT, PurchaseOrder.STATUS_ISSUED,
         PurchaseOrder.STATUS_PARTLY_RECEIVED),
    )


def _numbers(qs, field, limit=5):
    nums = [n or '(draft)' for n in qs.order_by(field).values_list(field, flat=True)[:limit + 1]]
    return ', '.join(nums[:limit]) + (', …' if len(nums) > limit else '')


def _plural(n, noun):
    return f'{n} open {noun}' + ('' if n == 1 else 's')


def _open_record_blockers(contacts):
    """Open jobs / invoices / POs attached to any of `contacts` (an iterable
    or queryset), as human sentences (spec §4.2 blockers 2–4)."""
    from apps.invoicing.models import Invoice
    from apps.jobs.models import Job
    from apps.purchasing.models import PurchaseOrder
    open_jobs, open_invoices, open_pos = _open_statuses()
    blockers = []
    jobs = Job.objects.filter(contact__in=contacts, status__in=open_jobs)
    if (n := jobs.count()):
        blockers.append(f'{_plural(n, "job")} ({_numbers(jobs, "job_number")})')
    invoices = Invoice.objects.filter(job__contact__in=contacts, status__in=open_invoices)
    if (n := invoices.count()):
        blockers.append(f'{_plural(n, "invoice")} ({_numbers(invoices, "invoice_number")})')
    pos = PurchaseOrder.objects.filter(contact__in=contacts, status__in=open_pos)
    if (n := pos.count()):
        blockers.append(f'{_plural(n, "PO")} ({_numbers(pos, "po_number")})')
    return blockers


def _vendor_po_blockers(business):
    from apps.purchasing.models import PurchaseOrder
    _, _, open_pos = _open_statuses()
    pos = PurchaseOrder.objects.filter(business=business, status__in=open_pos)
    n = pos.count()
    return [f'{_plural(n, "vendor PO")} ({_numbers(pos, "po_number")})'] if n else []
```

Then add to `ContactService`:

```python
    # --- Active / inactive (spec §4) ---

    @staticmethod
    def assert_active(obj):
        """Refuse any edit to an inactive record (spec §4.7)."""
        if not obj.is_active:
            raise ValidationError(f'{obj} is inactive. Reactivate it before editing.')

    @staticmethod
    def contact_deactivation_blockers(contact):
        blockers = []
        business = contact.business
        if (business is not None and business.is_active
                and business.default_contact_id == contact.pk):
            blockers.append(f'default contact for {business.business_name} '
                            f'(choose another default first)')
        blockers.extend(_open_record_blockers([contact]))
        return blockers

    @staticmethod
    def deactivate_contact(contact, *, push_to_qbo=True):
        if not contact.is_active:
            return contact
        blockers = ContactService.contact_deactivation_blockers(contact)
        if blockers:
            raise ValidationError(f'Cannot deactivate {contact}: ' + '; '.join(blockers) + '.')
        with transaction.atomic():
            contact.is_active = False
            contact.save()
        return contact

    @staticmethod
    def reactivate_contact(contact, *, push_to_qbo=True):
        if contact.is_active:
            return contact
        business = contact.business
        if business is not None and not business.is_active:
            raise ValidationError(
                f'Cannot reactivate {contact}: business {business.business_name} is inactive. '
                f'Reactivate the business first.')
        with transaction.atomic():
            contact.is_active = True
            contact.save()
        return contact

    @staticmethod
    def business_deactivation_blockers(business):
        return (_open_record_blockers(business.contacts.all())
                + _vendor_po_blockers(business))

    @staticmethod
    def deactivate_business_impact(business):
        contacts = list(business.contacts.all())
        return {
            'contact_count': len(contacts),
            'contact_names': [c.name for c in contacts],
            'blockers': ([] if not business.is_active
                         else ContactService.business_deactivation_blockers(business)),
        }

    @staticmethod
    def deactivate_business(business, *, push_to_qbo=True):
        if not business.is_active:
            return business
        blockers = ContactService.business_deactivation_blockers(business)
        if blockers:
            raise ValidationError(f'Cannot deactivate {business}: ' + '; '.join(blockers) + '.')
        with transaction.atomic():
            business.is_active = False
            business.save()
            for contact in list(business.contacts.all()):
                if contact.is_active:
                    contact.is_active = False
                    contact.save()
        return business

    @staticmethod
    def reactivate_business(business, *, push_to_qbo=True):
        if business.is_active:
            return business
        with transaction.atomic():
            business.is_active = True
            business.save()
            for contact in list(business.contacts.all()):
                if not contact.is_active:
                    contact.is_active = True
                    contact.save()
        return business

    @staticmethod
    def add_note(obj, object_type, text):
        ContactService.assert_active(obj)
        return record_history(entry_type='note', object_type=object_type,
                              object_id=obj.pk, text=text)
```

Guards in existing methods: first line after the lookup in `update_contact` → `ContactService.assert_active(contact)`; in `update_business` → `ContactService.assert_active(business)`; in `set_default_contact` after both lookups → `ContactService.assert_active(business)` and `ContactService.assert_active(contact)`. `TagService.attach/detach` → first line `ContactService.assert_active(obj)`.

In `apps/api/contacts/views.py` both `notes` actions: replace the `record_history(...)` call with `entry = ContactService.add_note(obj, 'contact', text)` / `'business'`. The add-tag/remove-tag actions already call `TagService`, which now guards.

- [ ] **Step 4: Run the tests**

Run: `timeout 600 python manage.py test tests.test_contacts_status tests.test_contacts_services tests.test_api_contacts --noinput`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add apps/contacts/services.py apps/api/contacts/views.py tests/test_contacts_status.py
git commit -m "feat(contacts): deactivate/reactivate rules, cascade, impact, and inactive edit refusal

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Status endpoints and `?status=` list filter

**Files:**
- Modify: `apps/api/contacts/views.py`
- Test: `tests/test_api_contacts_status.py` (new)

**Interfaces:**
- Produces: `POST /api/contacts/{id}/deactivate/`, `/reactivate/`; `POST /api/businesses/{id}/deactivate/`, `/reactivate/`; `GET /api/businesses/{id}/deactivate-impact/`; `?status=active|inactive|all` (default active) on both list endpoints. Retrieve is unfiltered.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api_contacts_status.py
from rest_framework.test import APIClient
from tests.base import BaseTestCase, grant_atoms
from apps.core.models import User
from apps.contacts.models import Business, Contact
from apps.contacts.services import ContactService
from tests.test_contacts_status import make_business, make_job
from apps.jobs.models import Job


class StatusEndpointsTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.user = User.objects.get(username='admin')
        self.client.force_authenticate(user=self.user)

    def test_deactivate_and_reactivate_contact(self):
        c = Contact.objects.create(first_name='Api', last_name='X', email='api@x.test')
        r = self.client.post(f'/api/contacts/{c.pk}/deactivate/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['is_active'])
        r = self.client.post(f'/api/contacts/{c.pk}/reactivate/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['is_active'])

    def test_blockers_render_as_detail_sentence(self):
        c = Contact.objects.create(first_name='Blk', last_name='X', email='blk@x.test')
        make_job(c, Job.STATUS_DRAFT)
        r = self.client.post(f'/api/contacts/{c.pk}/deactivate/')
        self.assertEqual(r.status_code, 400)
        self.assertIn('1 open job', r.data['detail'])

    def test_business_impact_then_deactivate(self):
        b, dc, _ = make_business('ApiCo')
        r = self.client.get(f'/api/businesses/{b.pk}/deactivate-impact/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['contact_count'], 2)
        self.assertEqual(r.data['blockers'], [])
        r = self.client.post(f'/api/businesses/{b.pk}/deactivate/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['is_active'])
        dc.refresh_from_db()
        self.assertFalse(dc.is_active)

    def test_requires_can_manage_jobs(self):
        plain = User.objects.create_user(username='plain', password='x')
        self.client.force_authenticate(user=plain)
        c = Contact.objects.create(first_name='Perm', last_name='X', email='perm@x.test')
        self.assertEqual(self.client.post(f'/api/contacts/{c.pk}/deactivate/').status_code, 403)
        self.assertEqual(self.client.get(f'/api/businesses/{Business.objects.first().pk}/deactivate-impact/').status_code, 403)

    def test_patch_inactive_contact_refused(self):
        c = Contact.objects.create(first_name='Ro', last_name='X', email='ro@x.test', is_active=False)
        r = self.client.patch(f'/api/contacts/{c.pk}/', {'first_name': 'Nope'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('inactive', r.data['detail'])
        r = self.client.post(f'/api/contacts/{c.pk}/notes/', {'text': 'hi'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.client.post(f'/api/contacts/{c.pk}/add-tag/', {'name': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_duplicate_409_carries_is_active(self):
        Contact.objects.create(first_name='Dup', last_name='X', email='dup@x.test', is_active=False)
        r = self.client.post('/api/contacts/', {'first_name': 'A', 'last_name': 'B', 'email': 'dup@x.test'}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertFalse(r.data['existing_contact']['is_active'])


class StatusFilterTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.live = Contact.objects.create(first_name='Live', last_name='X', email='live@x.test')
        self.dead = Contact.objects.create(first_name='Dead', last_name='X', email='dead@x.test', is_active=False)
        b, dc, _ = make_business('DeadCo')
        ContactService.deactivate_business(b)
        self.dead_biz = b

    def _ids(self, url, **params):
        return [r.get('contact_id') or r.get('business_id')
                for r in self.client.get(url, params).data['results']]

    def test_default_is_active_only(self):
        ids = self._ids('/api/contacts/')
        self.assertIn(self.live.pk, ids); self.assertNotIn(self.dead.pk, ids)
        self.assertNotIn(self.dead_biz.pk, self._ids('/api/businesses/'))

    def test_inactive_and_all(self):
        ids = self._ids('/api/contacts/', status='inactive')
        self.assertIn(self.dead.pk, ids); self.assertNotIn(self.live.pk, ids)
        ids = self._ids('/api/contacts/', status='all')
        self.assertIn(self.dead.pk, ids); self.assertIn(self.live.pk, ids)
        self.assertIn(self.dead_biz.pk, self._ids('/api/businesses/', status='all'))

    def test_bogus_status_falls_back_to_active(self):
        ids = self._ids('/api/contacts/', status='bogus')
        self.assertNotIn(self.dead.pk, ids)

    def test_retrieve_is_unfiltered(self):
        self.assertEqual(self.client.get(f'/api/contacts/{self.dead.pk}/').status_code, 200)

    def test_search_param_combines_with_status(self):
        ids = self._ids('/api/contacts/', status='all', search='Dead')
        self.assertIn(self.dead.pk, ids); self.assertNotIn(self.live.pk, ids)
```

- [ ] **Step 2: Run to see them fail**

Run: `timeout 600 python manage.py test tests.test_api_contacts_status --noinput`
Expected: 404s on the new routes; default-filter tests fail (inactive rows listed).

- [ ] **Step 3: Implement**

Add a module-level helper in `apps/api/contacts/views.py`:

```python
def _apply_status_filter(qs, request):
    """?status=active (default) | inactive | all — spec §6.3. Unknown values
    fall back to the default so a typo can't leak inactive rows into a
    chooser."""
    status_param = request.query_params.get('status', 'active')
    if status_param == 'all':
        return qs
    if status_param == 'inactive':
        return qs.filter(is_active=False)
    return qs.filter(is_active=True)
```

In both `get_queryset`s, right after `prefetch_related('tags')` and **only for the list action** (`if self.action == 'list': qs = _apply_status_filter(qs, self.request)`) so retrieve/update/actions resolve inactive records.

Permissions: add `'deactivate_impact'` nowhere special — it falls into the `CanManageJobs` branch of `get_permissions` automatically (anything not in the read list). Actions:

```python
    @action(detail=True, methods=['post'], url_path='deactivate')
    def deactivate(self, request, pk=None):
        contact = ContactService.deactivate_contact(self.get_object())
        return Response(ContactSerializer(contact).data)

    @action(detail=True, methods=['post'], url_path='reactivate')
    def reactivate(self, request, pk=None):
        contact = ContactService.reactivate_contact(self.get_object())
        return Response(ContactSerializer(contact).data)
```

and on `BusinessViewSet` the same pair using `BusinessSerializer`, plus:

```python
    @action(detail=True, methods=['get'], url_path='deactivate-impact')
    def deactivate_impact(self, request, pk=None):
        return Response(ContactService.deactivate_business_impact(self.get_object()))
```

No try/except: the service's `ValidationError` renders via the central handler as `{'detail': ...}` 400.

- [ ] **Step 4: Run the tests**

Run: `timeout 600 python manage.py test tests.test_api_contacts_status tests.test_api_contacts tests.test_contact_list_filters --noinput`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add apps/api/contacts/views.py tests/test_api_contacts_status.py
git commit -m "feat(api): contact/business deactivate, reactivate, deactivate-impact; ?status= list filter

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Creating jobs and POs with inactive parties is refused

**Files:**
- Modify: `apps/jobs/services.py` (`create_job`, `duplicate_job`), `apps/purchasing/services.py` (`create_po`)
- Test: `tests/test_contacts_status.py` (append)

**Interfaces:**
- Produces: `ValidationError({'contact': [...]})` / `{'business': [...]}` from the three create paths. Consumed by the SPA's create forms (field errors) and the email-to-job / email-to-PO flows unchanged.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_contacts_status.py`)

```python
class CreateWithInactivePartyTest(TestCase):
    def test_create_job_with_inactive_contact(self):
        from apps.jobs.services import JobService
        c = Contact.objects.create(first_name='In', last_name='X', email='in@x.test', is_active=False)
        with self.assertRaises(ValidationError) as cm:
            JobService.create_job(name='J', contact=c)
        self.assertIn('contact', cm.exception.message_dict)

    def test_create_job_with_contact_of_inactive_business(self):
        from apps.jobs.services import JobService
        b, dc, _ = make_business('InCo')
        ContactService.deactivate_business(b)
        dc.refresh_from_db()
        with self.assertRaises(ValidationError):
            JobService.create_job(name='J', contact=dc)

    def test_duplicate_into_inactive_contact_refused_but_frozen_source_ok(self):
        from apps.jobs.services import JobService
        src_contact = Contact.objects.create(first_name='Src', last_name='X', email='src@x.test')
        src = make_job(src_contact, Job.STATUS_COMPLETED)
        ContactService.deactivate_contact(src_contact)       # source now frozen
        dead = Contact.objects.create(first_name='Dead', last_name='Y', email='deady@x.test', is_active=False)
        with self.assertRaises(ValidationError):
            JobService.duplicate_job(src, contact=dead, path='estimate')
        live = Contact.objects.create(first_name='Live', last_name='Y', email='livey@x.test')
        new = JobService.duplicate_job(src, contact=live, path='estimate')
        self.assertEqual(new.contact, live)

    def test_create_po_with_inactive_vendor_or_contact(self):
        from apps.purchasing.services import PurchaseOrderService
        b, dc, (other,) = make_business('PoCo')
        ContactService.deactivate_contact(other)
        with self.assertRaises(ValidationError) as cm:
            PurchaseOrderService.create_po(business=b, contact=other)
        self.assertIn('contact', cm.exception.message_dict)
        ContactService.deactivate_business(b)
        with self.assertRaises(ValidationError) as cm:
            PurchaseOrderService.create_po(business=b)
        self.assertIn('business', cm.exception.message_dict)
```

- [ ] **Step 2: Run to see them fail**

Run: `timeout 600 python manage.py test tests.test_contacts_status.CreateWithInactivePartyTest --noinput`
Expected: no ValidationError raised → FAILED.

- [ ] **Step 3: Implement**

In `apps/jobs/services.py`, module level (near `_assert_job_not_on_hold`):

```python
def _assert_party_active(contact, field='contact'):
    """A new job/PO may not point at an inactive contact, nor at a contact
    whose business is inactive (spec §4.8)."""
    if contact is None:
        return
    if not contact.is_active:
        raise ValidationError({field: [f'{contact} is inactive.']})
    business = contact.business
    if business is not None and not business.is_active:
        raise ValidationError({field: [f'{business.business_name} is inactive.']})
```

`create_job`: first line `_assert_party_active(kwargs.get('contact'))`. (`duplicate_job` calls `create_job`, so it is covered; `JobViewSet.perform_create` passes the instance.) In `apps/purchasing/services.py` `create_po`:

```python
        business = kwargs.get('business')
        if business is not None and not business.is_active:
            raise ValidationError({'business': [f'{business.business_name} is inactive.']})
        from apps.jobs.services import _assert_party_active
        _assert_party_active(kwargs.get('contact'))
```

- [ ] **Step 4: Run**

Run: `timeout 600 python manage.py test tests.test_contacts_status tests.test_api_jobs --noinput`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add apps/jobs/services.py apps/purchasing/services.py tests/test_contacts_status.py
git commit -m "feat(jobs,purchasing): refuse new jobs/POs on inactive contacts or businesses

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Job freeze guard — core job, task, timeslip, and material paths

**Files:**
- Modify: `apps/jobs/services.py` (helper, `update_job` carve-out, call sites), `apps/inventory/services.py` (four `_assert_job_not_on_hold` sites), `apps/api/jobs/views.py:241-256` (notes), `apps/api/jobs/serializers.py`
- Test: `tests/test_api_inactive_party_freeze.py` (new)

**Interfaces:**
- Produces: `apps.jobs.services._assert_job_not_frozen(job, action: str)`; `JobService.assert_mutable(job, action='change this job')`; `JobSerializer` read-only fields `contact_is_active: bool`, `contact_business_id: int|None`, `contact_business_name: str|None`, `contact_business_is_active: bool|None`.
- Consumed by Task 9 (document services), Task 13 (banner).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api_inactive_party_freeze.py
"""A job whose contact is inactive is frozen (spec §5): every user-driven
mutation answers 400 with the freeze sentence; the same-business contact
swap is the one exception; Duplicate still works."""
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User
from apps.contacts.models import Contact
from apps.contacts.services import ContactService
from apps.jobs.models import Job, Task, RateScheme
from tests.test_contacts_status import make_business, make_job

FREEZE = 'is inactive'


class JobFreezeTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.biz, self.dc, (self.other,) = make_business('FrzCo')
        self.job = make_job(self.other, Job.STATUS_CANCELLED)   # closed → deactivation allowed
        self.task = Task.objects.create(job=self.job, name='T', status=Task.STATUS_PENDING)
        ContactService.deactivate_contact(self.other)
        self.job.refresh_from_db()

    def _assert_frozen(self, response):
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(FREEZE, response.data.get('detail', ''))

    def test_serializer_flags(self):
        d = self.client.get(f'/api/jobs/{self.job.pk}/').data
        self.assertFalse(d['contact_is_active'])
        self.assertEqual(d['contact_business_name'], 'FrzCo')
        self.assertEqual(d['contact_business_id'], self.biz.pk)
        self.assertTrue(d['contact_business_is_active'])

    def test_field_edit_refused(self):
        self._assert_frozen(self.client.patch(f'/api/jobs/{self.job.pk}/', {'name': 'x'}, format='json'))

    def test_reopen_refused(self):
        self._assert_frozen(self.client.patch(f'/api/jobs/{self.job.pk}/', {'status': Job.STATUS_IN_PROGRESS}, format='json'))

    def test_note_refused(self):
        self._assert_frozen(self.client.post(f'/api/jobs/{self.job.pk}/notes/', {'text': 'n'}, format='json'))

    def test_task_add_edit_delete_refused(self):
        self._assert_frozen(self.client.post(f'/api/jobs/{self.job.pk}/tasks/', {'name': 'New'}, format='json'))
        self._assert_frozen(self.client.patch(f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/', {'name': 'x'}, format='json'))
        self._assert_frozen(self.client.delete(f'/api/jobs/{self.job.pk}/tasks/{self.task.pk}/'))

    def test_delete_job_refused(self):
        self._assert_frozen(self.client.delete(f'/api/jobs/{self.job.pk}/'))

    def test_material_add_refused(self):
        self._assert_frozen(self.client.post(f'/api/jobs/{self.job.pk}/materials/',
                                             {'description': 'm', 'quantity': '1.00'}, format='json'))

    def test_swap_to_same_business_active_contact_unfreezes(self):
        r = self.client.patch(f'/api/jobs/{self.job.pk}/', {'contact': self.dc.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['contact_is_active'])
        # now a normal edit works
        self.assertEqual(self.client.patch(f'/api/jobs/{self.job.pk}/', {'name': 'thawed'}, format='json').status_code, 200)

    def test_swap_plus_other_field_refused(self):
        self._assert_frozen(self.client.patch(f'/api/jobs/{self.job.pk}/', {'contact': self.dc.pk, 'name': 'x'}, format='json'))

    def test_swap_to_same_inactive_contact_refused(self):
        r = self.client.patch(f'/api/jobs/{self.job.pk}/', {'contact': self.other.pk}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_swap_to_other_business_refused(self):
        stranger = Contact.objects.create(first_name='S', last_name='T', email='st@x.test')
        self._assert_frozen(self.client.patch(f'/api/jobs/{self.job.pk}/', {'contact': stranger.pk}, format='json'))

    def test_swap_refused_when_business_inactive(self):
        # Reactivate `other` so we can deactivate the whole business cleanly, then re-check.
        ContactService.reactivate_contact(self.other)
        ContactService.deactivate_business(self.biz)
        self._assert_frozen(self.client.patch(f'/api/jobs/{self.job.pk}/', {'contact': self.dc.pk}, format='json'))

    def test_duplicate_allowed_with_active_contact(self):
        live = Contact.objects.create(first_name='L', last_name='V', email='lv@x.test')
        r = self.client.post(f'/api/jobs/{self.job.pk}/duplicate/', {'contact_id': live.pk, 'path': 'estimate'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)

    def test_system_transition_bypasses(self):
        from apps.jobs.services import JobService
        JobService.update_job(self.job.pk, system_transition=True, status=Job.STATUS_IN_PROGRESS)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.STATUS_IN_PROGRESS)
```

Check the exact URLs for task create/update and job materials in `apps/api/urls.py` / `JobTaskMixin` and adjust (`tests/test_api_on_hold_guards.py` has working examples of each).

- [ ] **Step 2: Run to see them fail**

Run: `timeout 600 python manage.py test tests.test_api_inactive_party_freeze --noinput`
Expected: 200s where 400 expected; KeyError `contact_is_active`.

- [ ] **Step 3: The helper and `update_job`**

In `apps/jobs/services.py` next to `_assert_job_not_on_hold`:

```python
def _assert_job_not_frozen(job, action):
    """Spec §5.1: a job whose contact is inactive accepts no user-driven
    mutation. Mirrors _assert_job_not_on_hold; system transitions never
    call this."""
    contact = job.contact
    if contact.is_active:
        return
    business = contact.business
    hint = (f', or move the job to an active contact at {business.business_name},'
            if business is not None and business.is_active else ',')
    raise ValidationError(
        f"Cannot {action}: this job's contact, {contact.name}, is inactive. "
        f"Reactivate the contact{hint} before making changes."
    )
```

and on `JobService`:

```python
    @staticmethod
    def assert_mutable(job, action='change this job'):
        _assert_job_not_frozen(job, action)
```

In `update_job`, right after `job = Job.objects.get(pk=pk)`:

```python
        if not system_transition:
            new_contact = kwargs.get('contact')
            swap_only = set(kwargs) == {'contact'}
            if new_contact is not None:
                _assert_party_active(new_contact)          # never onto an inactive party
            same_business_swap = (
                swap_only and new_contact is not None
                and job.contact.business_id is not None
                and new_contact.business_id == job.contact.business_id
                and new_contact.business.is_active)
            if not same_business_swap:
                _assert_job_not_frozen(job, 'edit this job')
```

(`update_status` delegates to `update_job`, so the reopen path is covered; `hold_job`/`release_job` get `_assert_job_not_frozen(job, 'hold this job')` / `'release this job'` after their lookups; `assert_job_deletable` gets `_assert_job_not_frozen(job, 'delete this job')` first; `release_loose_materials` gets `'release materials on this job'`.)

- [ ] **Step 4: Task, timeslip, material call sites**

Add `_assert_job_not_frozen(<job>, '<same action string>')` on the line **before** each existing `_assert_job_not_on_hold(...)` call in `apps/jobs/services.py` (`create_from_template`, `create_direct`, `update_task`, `delete_task`, `reorder_tasks`, `assign`, `complete_task`, `block_task`, `unblock_task`, `cancel_task`) and in `apps/inventory/services.py` (the four sites). In `_assert_job_allows_blep` add, before the on_hold check, `_assert_job_not_frozen(job, action)` — that covers `start_work`, `create_historical`, and the historical-blep path. `BlepService.update` and `BlepService.delete`: after the permission checks add `_assert_job_not_frozen(blep.task.job, 'edit this timeslip')` / `'delete this timeslip'`. `TaskLifecycleService.add_actual_qty`, `stop_work`, `cancel_work`: `_assert_job_not_frozen(task.job, ...)` after the task lookup.

Job notes (`apps/api/jobs/views.py` `notes` action): after `obj = self.get_object()` add `JobService.assert_mutable(obj, 'add a note to this job')`.

- [ ] **Step 5: Serializer flags**

In `JobSerializer` add four `SerializerMethodField`s and list them in `Meta.fields`:

```python
    contact_is_active = serializers.SerializerMethodField()
    contact_business_id = serializers.SerializerMethodField()
    contact_business_name = serializers.SerializerMethodField()
    contact_business_is_active = serializers.SerializerMethodField()

    def get_contact_is_active(self, obj):
        return obj.contact.is_active

    def get_contact_business_id(self, obj):
        return obj.contact.business_id

    def get_contact_business_name(self, obj):
        b = obj.contact.business
        return b.business_name if b else None

    def get_contact_business_is_active(self, obj):
        b = obj.contact.business
        return b.is_active if b else None
```

`JobViewSet.queryset` already `select_related('contact')`; extend it to `select_related('contact', 'contact__business')`.

- [ ] **Step 6: Run**

Run: `timeout 900 python manage.py test tests.test_api_inactive_party_freeze tests.test_api_on_hold_guards tests.test_api_jobs tests.test_contacts_status --noinput`
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add apps/jobs/services.py apps/inventory/services.py apps/api/jobs tests/test_api_inactive_party_freeze.py
git commit -m "feat(jobs): freeze jobs whose contact is inactive; same-business contact swap carve-out

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Freeze guard — estimates, change orders, deliverables, shipments, invoices, sends

**Files:**
- Modify: `apps/estimates/services.py`, `apps/estimates/change_order_service.py`, `apps/deliverables/services.py`, `apps/invoicing/services.py`
- Test: `tests/test_api_inactive_party_freeze.py` (append)

**Interfaces:**
- Consumes: `JobService.assert_mutable(job, action)` from Task 8.

- [ ] **Step 1: Append the failing tests**

```python
class DocumentFreezeTest(BaseTestCase):
    """One representative endpoint per document service; the service-level
    guard covers the rest of each service's entry points."""
    def setUp(self):
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.biz, self.dc, (self.other,) = make_business('DocCo')
        self.job = make_job(self.other, Job.STATUS_COMPLETED)
        ContactService.deactivate_contact(self.other)

    def _assert_frozen(self, response):
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(FREEZE, response.data.get('detail', ''))

    def test_estimate_create_refused(self):
        self._assert_frozen(self.client.post('/api/estimates/', {'job': self.job.pk}, format='json'))

    def test_change_order_create_refused(self):
        self._assert_frozen(self.client.post('/api/change-orders/', {'job': self.job.pk}, format='json'))

    def test_deliverable_create_refused(self):
        self._assert_frozen(self.client.post(f'/api/jobs/{self.job.pk}/deliverables/',
                                             {'description': 'd', 'qty_ordered': '1', 'units': 'ea'}, format='json'))

    def test_shipment_create_refused(self):
        self._assert_frozen(self.client.post('/api/shipments/', {'job': self.job.pk}, format='json'))

    def test_invoice_open_refused(self):
        self._assert_frozen(self.client.post(f'/api/jobs/{self.job.pk}/start-invoice-wizard/', {}, format='json'))
```

Confirm each URL + minimal body against the viewsets (`apps/api/estimates/views.py`, `change_orders`, `deliverables`, `invoicing`, and the job `start-invoice-wizard` action) and adjust; the point of each test is only that the guard fires before any other validation.

- [ ] **Step 2: Run to see them fail**

Run: `timeout 600 python manage.py test tests.test_api_inactive_party_freeze.DocumentFreezeTest --noinput`
Expected: not 400 / wrong detail.

- [ ] **Step 3: Add the guard to every user-driven entry point**

Pattern — first statement after the object is resolved, with a short action phrase:

```python
        from apps.jobs.services import JobService
        JobService.assert_mutable(estimate.job, 'edit this estimate')
```

Sites (action phrase in parentheses):
- `EstimateService`: `create_direct` (`'add an estimate to this job'`), `create_for_job` (same), `update_status` (`'change this estimate'`), `update_fields`, `mark_open`, `unexpire`, `revise_estimate`, `request_changes`, `add_line_item`, `add_line_item_from_pli`, `add_line_item_from_service`, `update_line_item`, `reorder_line_items`, `reorder_line_item`, `delete_line_item`, `discard_draft`, `add_adjustment_line` (all `'edit this estimate'`). `EstimateEmailService.send_estimate` (`'send this estimate'`). `EstimateWizardService` mutators (`add_atoms_to_new_line_item`, `remove_atoms_from_line_item`, `restamp_atom`, `send_all_atoms`) — put one guard in the shared base helper they all go through if `BaseWizardService` has one; otherwise each.
- `ChangeOrderService`: `create`, `update_status`, `mark_open`, `seed_new`, `discard_draft`, `update_fields`, `add_line_item_from_service`, `recompute_adjustment_replaces` (`'edit this change order'`); `ChangeOrderEmailService.send_change_order` (`'send this change order'`); `ChangeOrderWizardService` mutators as above.
- `DeliverableService`: `create`, `update`, `delete`, `reorder` (`'edit deliverables on this job'`). `ShipmentService`: `create`, `update`, `delete`, `mark_picked_up`, `add_item`, `update_item`, `remove_item` (`'edit shipments on this job'`) — `create` already resolves `job`; the others resolve via `shipment.job`.
- `InvoiceService`: `add_line_item`, `add_line_item_from_pli`, `add_line_item_from_service`, `update_line_item`, `reorder_line_items`, `reorder_line_item`, `cancel`, `discard_draft`, `delete_line_item`, `copy_from_estimate`, `add_adjustment_line`, `seed_from_agreement`, `restore_agreement_line`, `remove_line` (`'edit this invoice'`); `InvoiceWizardService.open_for_job` (`'start an invoice for this job'`) and its mutators; `InvoiceEmailService.send_invoice` (`'send this invoice'`).

Do **not** guard: `maybe_complete_if_resolved`, QBO payment polling paths, `apps/estimates/signals.py`, estimate expiry, or any function already called with `system_transition=True`.

- [ ] **Step 4: Run the broader modules**

Run: `timeout 1200 python manage.py test tests.test_api_inactive_party_freeze tests.test_api_estimates tests.test_api_change_orders tests.test_api_invoices tests.test_api_deliverables tests.test_api_shipments --noinput`
(Substitute the real module names from `ls tests | grep -i "estimate\|change_order\|invoice\|deliverable\|shipment"`.) Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add apps/estimates apps/deliverables apps/invoicing tests/test_api_inactive_party_freeze.py
git commit -m "feat: freeze guard on estimate, change-order, deliverable, shipment, and invoice services

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: PO freeze guard, carve-out, serializer flags

**Files:**
- Modify: `apps/purchasing/services.py`, `apps/api/purchasing/serializers.py`
- Test: `tests/test_api_inactive_party_freeze.py` (append)

**Interfaces:**
- Produces: `apps.purchasing.services._assert_po_not_frozen(po, action)`; `PurchaseOrderSerializer` read-only `business_is_active: bool|None`, `contact_is_active: bool|None`.

- [ ] **Step 1: Append the failing tests**

```python
class POFreezeTest(BaseTestCase):
    def setUp(self):
        super().setUp()
        from apps.purchasing.models import PurchaseOrder
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        self.biz, self.dc, (self.other,) = make_business('PoFrz')
        self.po = PurchaseOrder.objects.create(po_number='PO-FRZ-1', business=self.biz, contact=self.other,
                                               status=PurchaseOrder.STATUS_RECEIVED_IN_FULL)
        ContactService.deactivate_contact(self.other)

    def _assert_frozen(self, response):
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(FREEZE, response.data.get('detail', ''))

    def test_flags_and_edit_refused(self):
        d = self.client.get(f'/api/purchase-orders/{self.po.pk}/').data
        self.assertFalse(d['contact_is_active']); self.assertTrue(d['business_is_active'])
        self._assert_frozen(self.client.patch(f'/api/purchase-orders/{self.po.pk}/', {'requested_date': '2026-11-01'}, format='json'))
        self._assert_frozen(self.client.post(f'/api/purchase-orders/{self.po.pk}/line-items/',
                                             {'description': 'x', 'qty': '1', 'price': '1.00'}, format='json'))

    def test_swap_contact_same_vendor_ok_then_edit_works(self):
        r = self.client.patch(f'/api/purchase-orders/{self.po.pk}/', {'contact': self.dc.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.client.patch(f'/api/purchase-orders/{self.po.pk}/', {'requested_date': '2026-11-01'}, format='json').status_code, 200)

    def test_inactive_vendor_business_freezes_without_swap(self):
        ContactService.reactivate_contact(self.other)
        ContactService.deactivate_business(self.biz)
        self._assert_frozen(self.client.patch(f'/api/purchase-orders/{self.po.pk}/', {'contact': self.dc.pk}, format='json'))
```

Check the line-item URL in `apps/api/urls.py` (`LineItemMixin` routes) and adjust.

- [ ] **Step 2: Run to see them fail**

Run: `timeout 600 python manage.py test tests.test_api_inactive_party_freeze.POFreezeTest --noinput`
Expected: FAILED.

- [ ] **Step 3: Implement**

In `apps/purchasing/services.py` (module level):

```python
def _assert_po_not_frozen(po, action):
    """Spec §5.2: a PO whose vendor business or vendor contact is inactive
    accepts no user-driven mutation."""
    business = po.business
    if business is not None and not business.is_active:
        raise ValidationError(
            f"Cannot {action}: this PO's vendor, {business.business_name}, is inactive. "
            f"Reactivate the vendor before making changes.")
    contact = po.contact
    if contact is not None and not contact.is_active:
        hint = (f', or move the PO to an active contact at {business.business_name},'
                if business is not None else ',')
        raise ValidationError(
            f"Cannot {action}: this PO's contact, {contact.name}, is inactive. "
            f"Reactivate the contact{hint} before making changes.")
```

`update_po` after the lookup:

```python
        new_contact = kwargs.get('contact')
        if new_contact is not None:
            from apps.jobs.services import _assert_party_active
            _assert_party_active(new_contact)
        same_vendor_swap = (set(kwargs) == {'contact'} and new_contact is not None
                            and po.business_id is not None
                            and new_contact.business_id == po.business_id
                            and po.business.is_active)
        if not same_vendor_swap:
            _assert_po_not_frozen(po, 'edit this purchase order')
```

Add `_assert_po_not_frozen(po, '<action>')` after the PO is resolved in: `update_status` (`'change this purchase order'`), `reconcile`, `cancel_po`, `delete_po`, `add_line_item`, `add_line_item_from_pli`, `change_line_job`, `update_line_item`, `reorder_line_items`, `reorder_line_item`, `delete_line_item` (`'edit this purchase order'` — line-item methods resolve `li.purchase_order`), `PurchaseOrderReceivingService.receive_items`, `receive_all`, `cancel_line_item`, `reverse_receipt` (`'receive against this purchase order'`), `PurchaseOrderEmailService.send_po` (`'send this purchase order'`).

Serializer: add to `PurchaseOrderSerializer`

```python
    business_is_active = serializers.SerializerMethodField()
    contact_is_active = serializers.SerializerMethodField()

    def get_business_is_active(self, obj):
        return obj.business.is_active if obj.business_id else None

    def get_contact_is_active(self, obj):
        return obj.contact.is_active if obj.contact_id else None
```

and list both in `Meta.fields`.

- [ ] **Step 4: Run**

Run: `timeout 900 python manage.py test tests.test_api_inactive_party_freeze tests.test_api_purchase_orders tests.test_purchasing_services --noinput` (use the real purchasing test module names from `ls tests | grep -i purchas`). Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add apps/purchasing/services.py apps/api/purchasing/serializers.py tests/test_api_inactive_party_freeze.py
git commit -m "feat(purchasing): freeze POs on inactive vendor/contact; same-vendor contact swap carve-out

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```


---

# Phase C — SPA

All Vitest runs: `cd frontend && npm run test:run -- <path>` (never watch mode). Run the whole Vitest suite at the end of each task.

### Task 11: `PhoneListEditor` and every phone display

**Files:**
- Create: `frontend/src/components/contacts/PhoneListEditor.svelte`, `frontend/tests/components/contacts/PhoneListEditor.test.js`
- Modify: `components/contacts/ContactForm.svelte`, `BusinessForm.svelte`, `ContactDetail.svelte`, `BusinessDetail.svelte`, `ContactList.svelte`, `BusinessList.svelte`, `CustomerActivity.svelte`, `DuplicateContactNotice.svelte`, `DuplicateBusinessNotice.svelte`, `components/email/SenderResolutionForm.svelte`, `lib/email.js`, `routes/Search.svelte`, `routes/contacts/ContactListPage.svelte` (the `phone:` row field)
- Modify tests: every file under `frontend/tests` that names `mobile_number`, `work_number`, `home_number`, or `business_phone` (`grep -rl` them) — fixtures switch to `phones: [...]` / `phone: '...'`.

**Interfaces:**
- Produces: `<PhoneListEditor bind:phones errors />` — `phones` is the bound list of `{number, label}`; `errors` is the form's field-error bag (renders `<FieldError {errors} field="phones" />`).
- Consumes: API shapes from Task 4 (`phones` on detail/list payloads, `phone` on summary/search payloads).

- [ ] **Step 1: Write the failing component test**

```js
// frontend/tests/components/contacts/PhoneListEditor.test.js
import { describe, it, expect } from 'vitest';
import { render, fireEvent, within } from '@testing-library/svelte';
import Harness from './_PhoneListEditorHarness.svelte';

describe('PhoneListEditor', () => {
  it('renders one row per entry, marks the first as primary, adds and removes rows', async () => {
    const { container, getByRole, queryByText } = render(Harness, {
      props: { phones: [{ number: '555-0100', label: 'cell' }, { number: '555-0200', label: 'work' }] },
    });
    const rows = () => container.querySelectorAll('.phone-row');
    expect(rows()).toHaveLength(2);
    expect(within(rows()[0]).getByText('primary')).toBeInTheDocument();
    expect(within(rows()[1]).queryByText('primary')).toBeNull();
    await fireEvent.click(getByRole('button', { name: 'Add phone' }));
    expect(rows()).toHaveLength(3);
    await fireEvent.click(within(rows()[2]).getByRole('button', { name: 'Remove phone 3' }));
    expect(rows()).toHaveLength(2);
    expect(queryByText('No phone numbers')).toBeNull();
  });

  it('move up promotes a row to primary and the bound list reorders', async () => {
    const { container } = render(Harness, {
      props: { phones: [{ number: '1', label: 'a' }, { number: '2', label: 'b' }] },
    });
    const rows = () => container.querySelectorAll('.phone-row');
    expect(within(rows()[0]).queryByRole('button', { name: /Move phone 1 up/ })).toBeNull();
    await fireEvent.click(within(rows()[1]).getByRole('button', { name: 'Move phone 2 up' }));
    expect(within(rows()[0]).getByDisplayValue('2')).toBeInTheDocument();
    expect(container.querySelector('[data-testid="bound"]').textContent).toBe('2,1');
  });

  it('shows the phones field error under the editor and an empty hint when the list is empty', () => {
    const { getByText } = render(Harness, { props: { phones: [], errors: { phones: ['Phone entry 1 needs a number.'] } } });
    expect(getByText('Phone entry 1 needs a number.')).toBeInTheDocument();
    expect(getByText('No phone numbers')).toBeInTheDocument();
  });
});
```

Harness (`frontend/tests/components/contacts/_PhoneListEditorHarness.svelte`), so the test can observe the bound value:

```svelte
<script>
  import PhoneListEditor from '@/components/contacts/PhoneListEditor.svelte';
  let { phones = [], errors = {} } = $props();
  let list = $state(phones);
</script>
<PhoneListEditor bind:phones={list} {errors} />
<span data-testid="bound">{list.map((p) => p.number).join(',')}</span>
```

- [ ] **Step 2: Run to see it fail**

Run: `cd frontend && npm run test:run -- tests/components/contacts/PhoneListEditor.test.js`
Expected: FAIL (component missing).

- [ ] **Step 3: Write the component**

```svelte
<!-- frontend/src/components/contacts/PhoneListEditor.svelte -->
<script>
  // Ordered phone list editor (contacts refine, 2026-10-11). The first row
  // is the primary number; ▲ promotes a row. Rows are pending form state —
  // the host form's Save commits (no blur-saves).
  import FieldError from '../FieldError.svelte';
  let { phones = $bindable([]), errors = {} } = $props();

  function add() { phones = [...phones, { number: '', label: '' }]; }
  function remove(i) { phones = phones.filter((_, idx) => idx !== i); }
  function moveUp(i) {
    if (i === 0) return;
    const next = [...phones];
    [next[i - 1], next[i]] = [next[i], next[i - 1]];
    phones = next;
  }
</script>

<fieldset class="phones">
  <legend><strong>Phone numbers</strong></legend>
  {#if phones.length === 0}
    <p class="muted">No phone numbers</p>
  {/if}
  {#each phones as entry, i (i)}
    <div class="phone-row">
      <input type="text" placeholder="Number" aria-label={`Phone ${i + 1} number`} bind:value={entry.number}>
      <input type="text" placeholder="Label (cell, work, A/P…)" aria-label={`Phone ${i + 1} label`} bind:value={entry.label}>
      {#if i === 0}<span class="primary">primary</span>{:else}
        <button type="button" class="icon" aria-label={`Move phone ${i + 1} up`} onclick={() => moveUp(i)}>▲</button>
      {/if}
      <button type="button" class="icon" aria-label={`Remove phone ${i + 1}`} onclick={() => remove(i)}>✕</button>
    </div>
  {/each}
  <button type="button" onclick={add}>Add phone</button>
  <FieldError {errors} field="phones" />
</fieldset>

<style>
  .phone-row { display: grid; grid-template-columns: 1fr 1fr auto auto; gap: 6px; align-items: center; margin-bottom: 6px; }
  .primary { font-size: 11px; color: #166534; background: #dcfce7; border-radius: 10px; padding: 2px 8px; }
  .icon { padding: 2px 8px; }
  .muted { color: #64748b; font-size: 13px; margin: 4px 0; }
</style>
```

`bind:value={entry.number}` inside `{#each}` requires `phones` to be a `$state` proxy — it is, through `$bindable`. If Svelte warns about binding to each-block items, switch to `oninput={(e) => update(i, 'number', e.target.value)}` that reassigns a new list.

- [ ] **Step 4: Wire the forms and displays**

- `ContactForm.svelte`: replace the three phone keys in `form` with `phones: contact?.phones ? contact.phones.map((p) => ({ ...p })) : []`; replace the phone `<fieldset>` with `<PhoneListEditor bind:phones={form.phones} {errors} />`. `handleSubmit` sends `phones` as-is (drop rows with blank number: `phones: form.phones.filter((p) => p.number.trim())`).
- `BusinessForm.svelte`: same swap for `business_phone` → `phones`.
- `SenderResolutionForm.svelte`: `contactForm.phones: []` + `<PhoneListEditor bind:phones={state.contactForm.phones} />`; `lib/email.js`: delete the "at least one phone" throw (lines 36-41) and keep `phones` in the payload.
- `ContactDetail.svelte`: replace the three `tel:` rows with `{#each contact.phones || [] as p}<dt>{p.label || 'Phone'}</dt><dd><a href="tel:{p.number}">{p.number}</a></dd>{/each}`; `businessLine` uses `business?.phone`.
- `BusinessDetail.svelte`: same `{#each business.phones ...}` block; the "No contact details" condition uses `!(business.phones?.length)`.
- `ContactList.svelte` `phoneCell` → `{contact.phone || ''}`; `BusinessList.svelte` column → `field: 'phone'`; `CustomerActivity.svelte` `contactPhoneCell` → `{c.phone || '—'}`; `ContactListPage.svelte` row mapping `phone: c.phone || ''` and `phone: b.phone || ''` for businesses.
- `DuplicateContactNotice.svelte` / `DuplicateBusinessNotice.svelte`: show `contact.phones?.[0]?.number` / `business.phones?.[0]?.number`.
- `Search.svelte`: delete the mobile/work/home snippets and columns; one `contactPhoneCell` → `{@html hl(c.phone)}`; `bizPhoneCell` → `{@html hl(b.phone)}`.

Then update the Vitest fixtures that named the old fields (`ContactForm.test.js`, `BusinessForm.test.js`, `ContactDetail.test.js`, `BusinessDetail.test.js`, `ContactList.test.js`, `BusinessList.test.js`, `ContactListPage.test.js`, `ContactDetailPage.test.js`, `CustomerActivity.test.js`, `SenderResolutionForm.test.js`, `routes/Search.test.js`, and any `grep -rl` finds). A form test that typed into `#work_number` now types into `getByLabelText('Phone 1 number')` after clicking **Add phone**, and asserts the submitted payload is `phones: [{ number: '…', label: '…' }]`.

- [ ] **Step 5: Run the whole Vitest suite**

Run: `cd frontend && npm run test:run`
Expected: all green; `grep -rn "mobile_number\|work_number\|home_number\|business_phone" frontend/src frontend/tests` returns nothing.

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat(spa): PhoneListEditor; phones list through forms, details, lists, search, and email flows

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12: Status in the SPA — badge, list toggle, detail actions, duplicate notice

**Files:**
- Modify: `frontend/src/css/app.css` (`.status-inactive`), `components/contacts/CustomerHeader.svelte`, `routes/contacts/ContactListPage.svelte`, `routes/contacts/ContactDetailPage.svelte`, `routes/contacts/BusinessDetailPage.svelte`, `components/contacts/DuplicateContactNotice.svelte`, `components/contacts/ContactFormModal.svelte`, `components/contacts/BusinessFormModal.svelte`, `components/email/EmailCreateJobModal.svelte`, `routes/Search.svelte`, `lib/customerActivity.js` (comment only — Deactivate is no longer a placeholder)
- Tests: `CustomerHeader.test.js`, `ContactListPage.test.js`, `ContactDetailPage.test.js`, `BusinessDetailPage.test.js`, `DuplicateContactNotice.test.js`, `ContactFormModal.test.js`, `routes/Search.test.js`, plus `ContactPicker.test.js`, `BusinessPicker.test.js`, `CustomerPicker.test.js`, `PurchaseOrderForm.test.js` (assert no `status=` in their requests)

**Interfaces:**
- Consumes: Task 6 endpoints and `?status=`; `is_active` on payloads.
- Produces: `CustomerHeader` prop `inactive = false`; `DuplicateContactNotice` prop `onReactivate = null`.

- [ ] **Step 1: Write the failing tests**

`ContactListPage.test.js` — add:

```js
  it('sends status=active by default and switches to inactive / all from the toggle', async () => {
    mockLists({ contacts: [jane], businesses: [acme] });
    const { getByRole } = render(ContactListPage);
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining('status=active')));
    await fireEvent.click(getByRole('button', { name: 'Inactive' }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringMatching(/\/api\/contacts\/\?.*status=inactive/)));
    await fireEvent.click(getByRole('button', { name: 'All statuses' }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringMatching(/\/api\/contacts\/\?.*status=all/)));
  });

  it('badges inactive rows', async () => {
    mockLists({ contacts: [{ ...jane, is_active: false }], businesses: [] });
    const { findByText } = render(ContactListPage);
    expect(await findByText('inactive')).toBeInTheDocument();
  });
```

(The letter strip already has an "All" button — the status one is named "All statuses" so the roles stay unambiguous.)

`ContactDetailPage.test.js` — add:

```js
describe('ContactDetailPage status actions', () => {
  it('active contact: Deactivate posts and reloads; a blocker renders under the actions', async () => {
    wire(mockContact({ is_active: true }));
    api.post.mockRejectedValueOnce({ status: 400, data: { detail: 'Cannot deactivate Jane: 1 open job (JOB-1).' } });
    render(ContactDetailPage, { props: { params: { id: '1' } } });
    await fireEvent.click(await screen.findByRole('button', { name: 'Deactivate' }));
    expect(api.post).toHaveBeenCalledWith('/api/contacts/1/deactivate/', {});
    expect(await screen.findByText('Cannot deactivate Jane: 1 open job (JOB-1).')).toBeInTheDocument();
  });

  it('inactive contact: badge, Reactivate instead of Edit/New Job, no tag editor or note form', async () => {
    wire(mockContact({ is_active: false }));
    api.post.mockResolvedValueOnce({});
    render(ContactDetailPage, { props: { params: { id: '1' } } });
    expect(await screen.findByText('inactive')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'New Job', exact: true })).toBeNull();
    await fireEvent.click(screen.getByRole('button', { name: 'Reactivate' }));
    expect(api.post).toHaveBeenCalledWith('/api/contacts/1/reactivate/', {});
  });
});
```

`BusinessDetailPage.test.js` — add a test that **Deactivate** first GETs `/api/businesses/7/deactivate-impact/`, shows the modal text "This will deactivate Acme and its 2 contacts", and **Continue** POSTs `/api/businesses/7/deactivate/`; and one where the impact has `blockers: ['1 open job (JOB-1)']` → no modal, the blocker text shows under the actions.

`DuplicateContactNotice.test.js` — add: with `contact.is_active === false` and `onReactivate` given, a **Reactivate** button appears and calls it; without `onReactivate`, no button.

`CustomerHeader.test.js` — `inactive: true` renders the `inactive` badge next to the name.

Pickers: in `ContactPicker.test.js`, `BusinessPicker.test.js`, `CustomerPicker.test.js`, `PurchaseOrderForm.test.js` add an assertion that every `/api/contacts/` or `/api/businesses/` request URL does **not** contain `status=`.

- [ ] **Step 2: Run to see them fail**

Run: `cd frontend && npm run test:run -- tests/components/contacts`
Expected: the new tests fail.

- [ ] **Step 3: Implement**

`app.css` (after `.status-cancelled`): `.status-inactive { background: #e5e7eb; color: #4b5563; }`.

`CustomerHeader.svelte`: prop `inactive = false`; after `<h2 class="ch-name" …>` add `{#if inactive}<span class="status-badge status-inactive">inactive</span>{/if}`.

`ContactListPage.svelte`: `let statusFilter = $state('active');` → in `loadAll` `params.set('status', statusFilter)`; effect dependencies add `void statusFilter;`; the row mapping carries `is_active: c.is_active` / `b.is_active`; under the type-filter div:

```svelte
<div class="status-filter" role="group" aria-label="Status">
  {#each [['active', 'Active'], ['inactive', 'Inactive'], ['all', 'All statuses']] as [value, label]}
    <button type="button" class:active={statusFilter === value}
      onclick={() => { statusFilter = value; page = 1; }}>{label}</button>
  {/each}
</div>
```

and the `nameCell` snippet appends `{#if item.is_active === false}<span class="status-badge status-inactive">inactive</span>{/if}`.

`ContactDetailPage.svelte`: state `let actionError = $state('')`; functions:

```js
  async function deactivate() {
    actionError = '';
    try { await api.post(`/api/contacts/${params.id}/deactivate/`, {}); await loadContact(); }
    catch (e) { const t = triageError(e); if (t.overlay) showError(t.overlay); else actionError = t.message; }
  }
  async function reactivate() {
    actionError = '';
    try { await api.post(`/api/contacts/${params.id}/reactivate/`, {}); await loadContact(); }
    catch (e) { const t = triageError(e); if (t.overlay) showError(t.overlay); else actionError = t.message; }
  }
```

Header: pass `inactive={!contact.is_active}`; actions snippet becomes

```svelte
      {#if $canManageJobs}
        {#if contact.is_active}
          <button type="button" class="banner-btn" onclick={() => { newJobOpen = true; }}>New Job</button>
          <button type="button" class="edit-link header-action" onclick={() => { editOpen = true; }}>Edit</button>
          <button type="button" class="edit-link header-action" onclick={deactivate}>Deactivate</button>
        {:else}
          <button type="button" class="edit-link header-action" onclick={reactivate}>Reactivate</button>
        {/if}
        {#if canDelete}
          <button type="button" class="edit-link header-action danger" onclick={requestDelete}>Delete…</button>
        {/if}
        <FormMessage error={actionError} />
      {/if}
```

`ContactDetail` receives `readonly={!contact.is_active}` → it passes `readonly` to `TagEditor` (`readonly={!$canManageJobs || readonly}`) and `onAddNote={contact.is_active ? handleAddNote : null}` (CustomerActivity already hides the note form when `onAddNote` is null — verify, else add the guard).

`BusinessDetailPage.svelte`: same shape, plus the impact modal:

```js
  let deactivateImpact = $state(null);
  let deactivating = $state(false);
  async function requestDeactivate() {
    actionError = '';
    try {
      const impact = await api.get(`/api/businesses/${params.id}/deactivate-impact/`);
      if (impact.blockers.length) { actionError = `Cannot deactivate ${business.business_name}: ${impact.blockers.join('; ')}.`; return; }
      deactivateImpact = impact;
    } catch (e) { const t = triageError(e); if (t.overlay) showError(t.overlay); else actionError = t.message; }
  }
  async function confirmDeactivate() {
    deactivating = true;
    try { await api.post(`/api/businesses/${params.id}/deactivate/`, {}); deactivateImpact = null; await loadBusiness(); }
    catch (e) { const t = triageError(e); if (t.overlay) showError(t.overlay); else actionError = t.message; deactivateImpact = null; }
    finally { deactivating = false; }
  }
```

```svelte
  <Modal open={deactivateImpact != null} onSave={confirmDeactivate} onCancel={() => { deactivateImpact = null; }}
    busy={deactivating} maxWidth="480px" label="Deactivate business">
    <h3>Deactivate {business.business_name}?</h3>
    <p>This will deactivate <strong>{business.business_name}</strong> and its {deactivateImpact?.contact_count} contact(s)
      ({deactivateImpact?.contact_names.join(', ')}). They will be hidden from choosers and any records on them frozen until reactivated. Continue?</p>
    <div class="modal-actions">
      <button type="button" onclick={() => { deactivateImpact = null; }} disabled={deactivating}>Cancel</button>
      <button type="button" onclick={confirmDeactivate} disabled={deactivating}>{deactivating ? 'Deactivating…' : 'Continue'}</button>
    </div>
  </Modal>
```

Inactive business page hides New Job, Edit, Set-as-default buttons (pass `readonly={!business.is_active}` into `BusinessDetail` → it disables the per-row actions and tag editor and passes `onAddNote` null).

`DuplicateContactNotice.svelte`: prop `onReactivate = null`; after the View button: `{#if contact?.is_active === false && onReactivate}<button type="button" onclick={onReactivate}>Reactivate</button>{/if}`, and the body shows the `inactive` badge next to the name. `ContactFormModal.svelte`, `BusinessFormModal.svelte`, `EmailCreateJobModal.svelte`: pass `onReactivate={reactivateExisting}` where

```js
  async function reactivateExisting() {
    const id = duplicateContact.contact_id;
    try { await api.post(`/api/contacts/${id}/reactivate/`, {}); onClose(); push(`/contacts/${id}`); }
    catch (e) { showError(errorMessage(e, 'Could not reactivate the contact.')); }
  }
```

`Search.svelte`: `contactNameCell` / `bizNameCell` append the inactive badge when `is_active === false`.

- [ ] **Step 4: Run the suite**

Run: `cd frontend && npm run test:run`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(spa): inactive badge, status toggle on the contacts list, deactivate/reactivate actions, business confirm modal, reactivate from duplicate notice

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: Frozen banner and contact swap on jobs and POs

**Files:**
- Create: `frontend/src/components/FrozenPartyBanner.svelte`, `frontend/src/components/ChangeContactModal.svelte`, tests `frontend/tests/components/FrozenPartyBanner.test.js`, `frontend/tests/components/ChangeContactModal.test.js`
- Modify: `components/ContactPicker.svelte` (`businessId` prop), `components/jobs/JobHeader.svelte`, `components/purchaseorders/PurchaseOrderDetail.svelte`, `routes/purchaseorders/PurchaseOrderDetailPage.svelte` (reload after swap)
- Tests: `ContactPicker.test.js`, `jobs/JobHeader.test.js`, `purchaseorders/PurchaseOrderDetail.test.js`

**Interfaces:**
- Produces: `<FrozenPartyBanner kind="job"|"po" partyName partyHref businessName businessActive onChangeContact />`; `<ChangeContactModal open patchUrl businessId onSaved onClose />` (PATCHes `{ contact: <id> }` only); `ContactPicker` prop `businessId = null` → appends `&business=<id>` to the search URL.
- Consumes: Task 8/10 serializer flags.

- [ ] **Step 1: Write the failing tests**

```js
// frontend/tests/components/FrozenPartyBanner.test.js
import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import FrozenPartyBanner from '@/components/FrozenPartyBanner.svelte';

describe('FrozenPartyBanner', () => {
  it('names the inactive contact with a link and offers the swap when the business is active', async () => {
    const onChangeContact = vi.fn();
    const { getByRole, getByText } = render(FrozenPartyBanner, { props: {
      kind: 'job', partyName: 'Jane Doe', partyHref: '#/contacts/3', businessName: 'Acme', businessActive: true, onChangeContact,
    } });
    expect(getByText(/Frozen:/)).toBeInTheDocument();
    expect(getByRole('link', { name: 'Jane Doe' })).toHaveAttribute('href', '#/contacts/3');
    await fireEvent.click(getByRole('button', { name: 'Change contact…' }));
    expect(onChangeContact).toHaveBeenCalled();
  });

  it('omits the swap when the business is inactive or absent', () => {
    const { queryByRole, getByText } = render(FrozenPartyBanner, { props: {
      kind: 'po', partyName: 'Acme', partyHref: '#/businesses/7', businessName: null, businessActive: false,
    } });
    expect(queryByRole('button', { name: 'Change contact…' })).toBeNull();
    expect(getByText(/Reactivate/)).toBeInTheDocument();
  });
});
```

```js
// frontend/tests/components/ChangeContactModal.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, screen } from '@testing-library/svelte';
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() }, errorMessage: (e, f) => e?.data?.detail || f }));
import { api } from '@/lib/api.js';
import ChangeContactModal from '@/components/ChangeContactModal.svelte';

beforeEach(() => { api.get.mockReset(); api.patch.mockReset(); api.patch.mockResolvedValue({}); });

describe('ChangeContactModal', () => {
  it('scopes the picker to the business and PATCHes only the contact', async () => {
    api.get.mockResolvedValue({ results: [{ contact_id: 9, name: 'Sam Roe', business: { business_name: 'Acme' } }] });
    const onSaved = vi.fn();
    render(ChangeContactModal, { props: { open: true, patchUrl: '/api/jobs/5/', businessId: 7, onSaved } });
    await fireEvent.input(screen.getByPlaceholderText(/contact/i), { target: { value: 'sam' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/contacts/?search=sam&page_size=25&business=7');
    await fireEvent.mouseDown(await screen.findByRole('button', { name: /Sam Roe/ }));
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/jobs/5/', { contact: 9 });
    expect(onSaved).toHaveBeenCalled();
  });

  it('renders a server refusal under the buttons', async () => {
    api.get.mockResolvedValue({ results: [{ contact_id: 9, name: 'Sam Roe', business: null }] });
    api.patch.mockRejectedValueOnce({ status: 400, data: { detail: 'Cannot edit this job: …' } });
    render(ChangeContactModal, { props: { open: true, patchUrl: '/api/jobs/5/', businessId: 7 } });
    await fireEvent.input(screen.getByPlaceholderText(/contact/i), { target: { value: 'sam' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await screen.findByRole('button', { name: /Sam Roe/ }));
    await fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Cannot edit this job: …')).toBeInTheDocument();
  });
});
```

`JobHeader.test.js` — add: with `job = { …, status: 'completed', contact_is_active: false, contact_business_name: 'Acme', contact_business_is_active: true, contact: 3 }` the banner renders with "Change contact…"; clicking it opens the dialog labelled "Change contact"; `onStatusChange` is called after a save. `PurchaseOrderDetail.test.js` — add: `po = { …, contact_is_active: false, business_is_active: true }` renders the banner; `business_is_active: false` renders it without the swap. `ContactPicker.test.js` — add: `businessId: 7` appends `&business=7`.

- [ ] **Step 2: Run to see them fail**

Run: `cd frontend && npm run test:run -- tests/components/FrozenPartyBanner.test.js tests/components/ChangeContactModal.test.js tests/components/jobs/JobHeader.test.js`
Expected: FAIL.

- [ ] **Step 3: Implement**

`ContactPicker.svelte`: add `businessId = null` to the props; `search` builds `` `/api/contacts/?search=${encodeURIComponent(q)}&page_size=${PICKER_PAGE_SIZE}${businessId != null ? `&business=${businessId}` : ''}` ``.

```svelte
<!-- frontend/src/components/FrozenPartyBanner.svelte -->
<script>
  // Shown on a job/PO whose contact (or vendor) is inactive — the record is
  // frozen server-side (spec §5); this is the UI's whole treatment plus the
  // one escape hatch, the same-business contact swap.
  let { kind = 'job', partyName, partyHref, businessName = null, businessActive = false, onChangeContact = null } = $props();
  const noun = $derived(kind === 'po' ? 'purchase order' : 'job');
</script>

<div class="frozen-banner" role="status">
  <strong>Frozen:</strong>
  <span><a href={partyHref}>{partyName}</a> is inactive.</span>
  {#if businessActive && businessName && onChangeContact}
    <span>Reactivate them, or move this {noun} to another contact at {businessName}.</span>
    <button type="button" class="edit-link" onclick={onChangeContact}>Change contact…</button>
  {:else}
    <span>Reactivate them before making changes to this {noun}.</span>
  {/if}
</div>

<style>
  .frozen-banner { background: #e0e7ff; border: 1px solid #a5b4fc; color: #3730a3; border-radius: 8px;
    padding: 8px 12px; font-size: 13px; margin: 8px 0 4px; display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline; }
  .frozen-banner button { margin-left: auto; }
</style>
```

```svelte
<!-- frontend/src/components/ChangeContactModal.svelte -->
<script>
  import Modal from './Modal.svelte';
  import ContactPicker from './ContactPicker.svelte';
  import FormMessage from './FormMessage.svelte';
  import { api } from '../lib/api.js';
  import { triageError } from '../lib/errorTriage.js';
  import { showError } from '../stores/messages.js';
  let { open = false, patchUrl, businessId = null, onSaved = () => {}, onClose = () => {} } = $props();
  let contact = $state(null);
  let formError = $state('');
  let saving = $state(false);
  $effect(() => { if (open) { contact = null; formError = ''; } });
  async function save(e) {
    e?.preventDefault?.();
    if (contact == null) { formError = 'Pick a contact.'; return; }
    saving = true; formError = '';
    try { await api.patch(patchUrl, { contact }); onSaved(); onClose(); }
    catch (err) { const t = triageError(err); if (t.overlay) showError(t.overlay); else formError = t.message; }
    finally { saving = false; }
  }
</script>

<Modal {open} onCancel={onClose} maxWidth="520px" label="Change contact">
  <h3 class="modal-title">Change contact</h3>
  <form onsubmit={save}>
    <p><label><strong>New contact</strong></label><br><ContactPicker bind:value={contact} {businessId} /></p>
    <p>
      <button type="submit" disabled={saving}>Save</button>
      <button type="button" onclick={onClose}>Cancel</button>
    </p>
    <FormMessage error={formError} />
  </form>
</Modal>
```

`JobHeader.svelte`: state `let swapOpen = $state(false)`; after the `.customer-line` paragraph:

```svelte
    {#if job.contact_is_active === false}
      <FrozenPartyBanner kind="job" partyName={contact?.name ?? job.contact_name} partyHref={`#/contacts/${job.contact}`}
        businessName={job.contact_business_name} businessActive={!!job.contact_business_is_active}
        onChangeContact={canManageJobs ? () => { swapOpen = true; } : null} />
    {/if}
```

and near the other modals `<ChangeContactModal open={swapOpen} patchUrl={`/api/jobs/${job.job_id}/`} businessId={job.contact_business_id ?? null} onSaved={() => { if (onStatusChange) onStatusChange(); }} onClose={() => { swapOpen = false; }} />` (`contact` is null on several job sub-pages, so the business id comes from the job payload's `contact_business_id`, Task 8). Also badge the customer line: after the contact link `{#if job.contact_is_active === false}<span class="status-badge status-inactive">inactive</span>{/if}`.

`PurchaseOrderDetail.svelte`: under the status line, when `po.business_is_active === false` → banner (`kind="po"`, partyName `po.business_name`, href `#/businesses/{po.business}`, `businessActive={false}`); else when `po.contact_is_active === false` → banner with partyName `po.contact_name`, href `#/contacts/{po.contact}`, `businessName={po.business_name}`, `businessActive={true}`, `onChangeContact={canManageFinancials ? () => { swapOpen = true; } : null}`; mount `<ChangeContactModal open={swapOpen} patchUrl={`/api/purchase-orders/${po.po_id}/`} businessId={po.business} onSaved={onReload} onClose=… />` — add an `onReload = () => {}` prop and have `PurchaseOrderDetailPage` pass its loader.

- [ ] **Step 4: Run the suite**

Run: `cd frontend && npm run test:run`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat(spa): frozen banner on jobs/POs with same-business contact swap; ContactPicker business scope

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 14: Playwright specs

**Files:**
- Create: `e2e/specs/contacts/status.spec.js`, `e2e/specs/contacts/phones.spec.js`, `e2e/specs/contacts/frozen-job.spec.js`
- Modify: `e2e/specs/contacts/business-detail.spec.js` and `contact-detail.spec.js` (the "Deactivate placeholder is disabled" steps become "Deactivate is enabled").

**Interfaces:** consumes the shipped SPA + API. Uses `apiAs(personas.finjobs)` for setup, `e2e-<stamp>` names for created rows, shape-based lookups (never hardcoded pks).

- [ ] **Step 1: Fix the two existing specs** — replace `toBeDisabled()` on the Deactivate button with `toBeEnabled()` and drop the "placeholder" wording in the step titles.

- [ ] **Step 2: `phones.spec.js`**

```js
// Phone list editor round trip (contacts refine, 2026-10-11 —
// docs/plans/2026-10-11-contacts-refine-design.md §7.1).
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';
import { apiAs } from '../../fixtures/api.js';

test.use({ storageState: personas.finjobs.storageState });

test('add two numbers, reorder, save; the detail shows the new primary first', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const stamp = `e2e-${Date.now().toString(36)}`;
  let contact;
  try {
    contact = await api.post('/api/contacts/', { first_name: stamp, last_name: 'Phones', email: `${stamp}@example.invalid` });
  } finally { await api.dispose(); }

  await page.goto(`/#/contacts/${contact.contact_id}`);
  await page.getByRole('button', { name: 'Edit' }).click();
  const dialog = page.getByRole('dialog', { name: 'Edit contact' });
  await test.step('Add phone twice, fill number + label', async () => {
    await dialog.getByRole('button', { name: 'Add phone' }).click();
    await dialog.getByLabel('Phone 1 number').fill('555-0100');
    await dialog.getByLabel('Phone 1 label').fill('cell');
    await dialog.getByRole('button', { name: 'Add phone' }).click();
    await dialog.getByLabel('Phone 2 number').fill('555-0200');
    await dialog.getByLabel('Phone 2 label').fill('A/P');
  });
  await test.step('Move phone 2 up → it becomes primary; Save', async () => {
    await dialog.getByRole('button', { name: 'Move phone 2 up' }).click();
    await expect(dialog.getByLabel('Phone 1 number')).toHaveValue('555-0200');
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
  });
  await test.step('Detail lists A/P first; the list page shows the primary', async () => {
    const panel = page.locator('.identity .panel').first();
    const numbers = await panel.locator('dd a[href^="tel:"]').allTextContents();
    expect(numbers).toEqual(['555-0200', '555-0100']);
    await page.goto('/#/contacts');
    await page.getByPlaceholder(/Search all contacts/).fill('555 0200');
    await expect(page.getByRole('link', { name: `${stamp} Phones` })).toBeVisible();
  });
});
```

- [ ] **Step 3: `status.spec.js`**

```js
// Deactivate / reactivate contacts and businesses (spec §4, §7.3–7.4).
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';
import { apiAs } from '../../fixtures/api.js';

test.use({ storageState: personas.finjobs.storageState });

async function freshBusiness(api, stamp, contacts = 2) {
  const first = await api.post('/api/contacts/', { first_name: `${stamp}-A`, last_name: 'Status', email: `${stamp}-a@example.invalid` });
  const biz = await api.post('/api/businesses/', { business_name: `${stamp} Status Co`, default_contact_id: first.contact_id });
  await api.patch(`/api/contacts/${first.contact_id}/`, { business_id: biz.business_id });
  const others = [];
  for (let i = 1; i < contacts; i++) {
    others.push(await api.post('/api/contacts/', { first_name: `${stamp}-${i}`, last_name: 'Status', email: `${stamp}-${i}@example.invalid`, business_id: biz.business_id }));
  }
  return { biz, first, others };
}

test('contact with an open job is blocked; a free contact deactivates, vanishes from the default list, shows under Inactive and in search', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const stamp = `e2e-${Date.now().toString(36)}`;
  let biz, first, others, job;
  try {
    ({ biz, first, others } = await freshBusiness(api, stamp));
    job = await api.post('/api/jobs/', { name: `${stamp} job`, contact: others[0].contact_id });
  } finally { await api.dispose(); }

  await page.goto(`/#/contacts/${others[0].contact_id}`);
  await test.step('Deactivate → blocker sentence names the open job', async () => {
    await page.getByRole('button', { name: 'Deactivate' }).click();
    await expect(page.getByText(new RegExp(`1 open job \\(${job.job_number}\\)`))).toBeVisible();
  });
  await test.step('Cancel the job via the API, then Deactivate succeeds and the badge appears', async () => {
    const api2 = await apiAs(personas.finjobs);
    try { await api2.patch(`/api/jobs/${job.job_id}/`, { status: 'rejected' }); } finally { await api2.dispose(); }
    await page.getByRole('button', { name: 'Deactivate' }).click();
    await expect(page.locator('.customer-header').getByText('inactive')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Reactivate' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Edit' })).toHaveCount(0);
  });
  await test.step('Default list hides it; Inactive shows it; global search shows it with the badge', async () => {
    await page.goto('/#/contacts');
    await page.getByPlaceholder(/Search all contacts/).fill(`${stamp}-1`);
    await expect(page.getByText('No results found.')).toBeVisible();
    await page.getByRole('button', { name: 'Inactive' }).click();
    await expect(page.getByRole('link', { name: `${stamp}-1 Status` })).toBeVisible();
    await page.goto(`/#/search?q=${encodeURIComponent(`${stamp}-1`)}`);
    await expect(page.getByRole('link', { name: `${stamp}-1 Status` })).toBeVisible();
    await expect(page.getByText('inactive').first()).toBeVisible();
  });
});

test('business deactivation confirms with the contact count, cascades, and reactivation brings everyone back', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const stamp = `e2e-${Date.now().toString(36)}`;
  let biz;
  try { ({ biz } = await freshBusiness(api, stamp, 3)); } finally { await api.dispose(); }

  await page.goto(`/#/businesses/${biz.business_id}`);
  await page.getByRole('button', { name: 'Deactivate' }).click();
  const dialog = page.getByRole('dialog', { name: 'Deactivate business' });
  await expect(dialog.getByText(/its 3 contact/)).toBeVisible();
  await dialog.getByRole('button', { name: 'Continue' }).click();
  await expect(page.locator('.customer-header').getByText('inactive')).toBeVisible();
  const contacts = page.locator('[data-section="contacts"]');
  await expect(contacts.getByText('inactive')).toHaveCount(3);
  await page.getByRole('button', { name: 'Reactivate' }).click();
  await expect(page.locator('.customer-header').getByText('inactive')).toHaveCount(0);
  await expect(contacts.getByText('inactive')).toHaveCount(0);
});
```

If the search route's query-param form differs, open `/#/search` and type into its box instead. The Contacts table badge on `BusinessDetail` rows must be added in Task 12 if it is not (the `CustomerActivity` contact rows show `inactive` when `c.is_active === false`).

- [ ] **Step 4: `frozen-job.spec.js`**

```js
// A closed job on an inactive contact is frozen (spec §5): banner, refused
// reopen, swap to a same-business contact unfreezes it.
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';
import { apiAs } from '../../fixtures/api.js';

test.use({ storageState: personas.finjobs.storageState });

test('frozen banner, refused reopen, contact swap unfreezes', async ({ page }) => {
  const api = await apiAs(personas.finjobs);
  const stamp = `e2e-${Date.now().toString(36)}`;
  let biz, a, b, job;
  try {
    a = await api.post('/api/contacts/', { first_name: `${stamp}-A`, last_name: 'Frz', email: `${stamp}-a@example.invalid` });
    biz = await api.post('/api/businesses/', { business_name: `${stamp} Frz Co`, default_contact_id: a.contact_id });
    await api.patch(`/api/contacts/${a.contact_id}/`, { business_id: biz.business_id });
    b = await api.post('/api/contacts/', { first_name: `${stamp}-B`, last_name: 'Frz', email: `${stamp}-b@example.invalid`, business_id: biz.business_id });
    job = await api.post('/api/jobs/', { name: `${stamp} frozen`, contact: b.contact_id });
    await api.patch(`/api/jobs/${job.job_id}/`, { status: 'rejected' });        // closed
    await api.post(`/api/contacts/${b.contact_id}/deactivate/`, {});
  } finally { await api.dispose(); }

  await page.goto(`/#/jobs/${job.job_id}`);
  await test.step('Banner names the inactive contact and offers Change contact…', async () => {
    await expect(page.getByText(/Frozen:/)).toBeVisible();
    await expect(page.getByRole('link', { name: `${stamp}-B Frz` })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Change contact…' })).toBeVisible();
  });
  await test.step('Reopen is refused with the freeze sentence', async () => {
    const api2 = await apiAs(personas.finjobs);
    try {
      const resp = await api2.patchRaw(`/api/jobs/${job.job_id}/`, { status: 'submitted' });
      expect(resp.status()).toBe(400);
      expect((await resp.json()).detail).toContain('is inactive');
    } finally { await api2.dispose(); }
  });
  await test.step('Change contact… to A (same business) → banner gone; reopen now works', async () => {
    await page.getByRole('button', { name: 'Change contact…' }).click();
    const dialog = page.getByRole('dialog', { name: 'Change contact' });
    await dialog.getByPlaceholder(/contact/i).fill(`${stamp}-A`);
    await dialog.getByRole('button', { name: new RegExp(`${stamp}-A Frz`) }).click();
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText(/Frozen:/)).toHaveCount(0);
    const api3 = await apiAs(personas.finjobs);
    try { expect((await api3.patchRaw(`/api/jobs/${job.job_id}/`, { status: 'submitted' })).status()).toBe(200); }
    finally { await api3.dispose(); }
  });
});
```

(`SearchPicker` rows are buttons activated on `mousedown` in Vitest; in Playwright a `.click()` sends mousedown too.)

- [ ] **Step 5: Run the contacts e2e directory**

Run: `cd e2e && timeout 1200 npx playwright test specs/contacts` (the run rebuilds `minibini_e2e` from migrations + the folded seed — this is also the proof the seed fold loads).
Expected: all pass. If a spec skips with a seed gap, say which and why in the commit body.

- [ ] **Step 6: Commit**

```bash
git add e2e/specs/contacts
git commit -m "test(e2e): phones editor, deactivate/reactivate, business cascade, frozen job swap

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 15: Design docs for Phases A–C

**Files:**
- Modify: `docs/designs/contacts-and-businesses.md` (Fields table, `clean()`, new "Active / inactive status" section after "Business", `get_queryset` filters table, Endpoints table, Search integration, QBO touchpoints, Frontend: list page, detail pages, forms, `PhoneListEditor`, `ContactPicker` `businessId`)
- Modify: `docs/designs/jobs-and-tasks.md` §3 (Job): a "Frozen jobs (inactive contact)" subsection — guard, call sites, carve-out, bypass, serializer flags; §9 (UI: Job Detail): the banner + `ChangeContactModal`
- Modify: `docs/designs/materials-inventory-and-purchasing.md` §9/§10 (PO freeze + carve-out), §15 (banner)
- Modify: `docs/designs/data-constraints.md` §1: Contact/Business field rows (`phones`, `phones_digits`, `is_active`), the ok-to-deactivate conditions, the frozen-record invariant; §2: deactivate/reactivate side effects (cascade)
- Modify: `docs/designs/quickbooks-integration.md` "Setup-time data import": the phone append rule
- Modify: `docs/designs/architecture-and-conventions.md` only if a mixin catalog line changes (it should not)

- [ ] **Step 1:** Write each section from the shipped code (not from the spec) — field names, endpoint paths, error sentences verbatim.
- [ ] **Step 2:** `grep -n "mobile_number\|work_number\|home_number\|business_phone" docs/designs/*.md` → zero hits except historical notes explicitly marked as such.
- [ ] **Step 3: Commit**

```bash
git add docs/designs
git commit -m "docs: phones list, active/inactive status, freeze guard across the design docs

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```


---

# Phase D — QBO status sync (last; separately shippable)

Phases A–C ship without this. Nothing here changes a Phase A–C contract except the `push_to_qbo` keyword that Task 5 already accepts.

**Ordering refinement to spec §6.6:** the QBO write runs **after the local blockers pass and before the local flip**, outside the `transaction.atomic()` block. Reason: `save_and_log` writes the failed `QBOSyncLog` row on error, and a rollback would erase it. The observable contract is unchanged — a QBO refusal leaves the local record untouched and the error carries QBO's message — and the spec's decisions log gets a one-line note (Task 19).

### Task 16: Sandbox verification (RM-driven, records findings)

**Files:**
- Modify: `docs/designs/quickbooks-integration.md` — new "Customer/Vendor Active flag — sandbox findings" subsection under "Customer sync".

This task is a spike, not code. The implementer prepares the probe; RM runs it against the QBO **sandbox** company (`QBO_ENVIRONMENT=sandbox` in `.env`, never production) from the dev stack, because the dev DB and a live OAuth token are needed.

- [ ] **Step 1: Prepare the probe script** in the scratchpad (read-only against konbini; writes only to the QBO sandbox):

```python
# <scratchpad>/qbo_active_probe.py — run with: python manage.py shell < qbo_active_probe.py
# READ-ONLY for the konbini DB. Writes go to the QBO sandbox only.
from quickbooks.objects.customer import Customer
from quickbooks.objects.vendor import Vendor
from apps.qbo.services import QBOService
client = QBOService.get_client(); assert client, 'connect the sandbox first (Settings → QuickBooks)'

c = Customer(); c.DisplayName = 'konbini probe customer'; c.save(qb=client)
print('created', c.Id, c.DisplayName, c.Active)
c = Customer.get(c.Id, qb=client); c.Active = False; c.save(qb=client)
c = Customer.get(c.Id, qb=client); print('after deactivate:', c.DisplayName, c.Active)
c.Active = True; c.save(qb=client)
c = Customer.get(c.Id, qb=client); print('after reactivate:', c.DisplayName, c.Active)
print('visible to default filter?', bool(Customer.filter(DisplayName='konbini probe customer', qb=client)))
print('visible to Active=False filter?', bool(Customer.filter(Active=False, DisplayName='konbini probe customer (deleted)', qb=client)))
v = Vendor(); v.DisplayName = 'konbini probe vendor'; v.save(qb=client)
v = Vendor.get(v.Id, qb=client); v.Active = False; v.save(qb=client)
print('vendor after deactivate:', Vendor.get(v.Id, qb=client).DisplayName)
```

Then, by hand in the sandbox UI: create an invoice for "konbini probe customer" (leave it unpaid) and a bill for "konbini probe vendor" (unpaid), and re-run only the deactivate lines for each. Record whether QBO refuses (and the exact error text) or accepts.

- [ ] **Step 2: Record the findings** in the QBO doc subsection, answering exactly: (a) does inactivation append " (deleted)" to DisplayName and does reactivation strip it; (b) does the API refuse to inactivate a Customer with a balance / a Vendor with open bills, and with what message; (c) does `_adopt_id_by_name` need an `Active=False` fallback query (it does if (a) is "yes, and reactivation strips it" — a push whose name collides with an inactive record should be able to adopt-and-reactivate; decide and record).

- [ ] **Step 3: Commit**

```bash
git add docs/designs/quickbooks-integration.md
git commit -m "docs(qbo): sandbox findings on the Customer/Vendor Active flag

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 17: Push status to QBO on deactivate / reactivate

**Files:**
- Modify: `apps/qbo/services.py` (`QBOCustomerSyncService.set_active`, new `QBOVendorSyncService.set_active`), `apps/contacts/services.py` (`_push_status_to_qbo` + wiring)
- Test: `tests/test_qbo_status_sync.py` (new)

**Interfaces:**
- Produces: `QBOCustomerSyncService.set_active(obj, active: bool) -> str` (obj is a Business or a Contact carrying `qbo_customer_id`); `QBOVendorSyncService.set_active(business, active) -> str`; both log via `save_and_log(action='deactivate'|'reactivate')`. `ContactService._push_status_to_qbo(obj, active)`.
- Consumes: Task 5's `push_to_qbo` keyword.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_qbo_status_sync.py
from unittest.mock import MagicMock, patch
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Business, Contact
from apps.contacts.services import ContactService
from apps.qbo.models import QBOConnection, QBOSyncLog
from tests.test_contacts_status import make_business


def connect():
    QBOConnection.objects.create(realm_id='r1', access_token='a', refresh_token='r', is_active=True)


class PushStatusTest(TestCase):
    def setUp(self):
        connect()
        self.biz, self.dc, _ = make_business('QCo')
        self.biz.qbo_customer_id = '71'
        self.biz.qbo_vendor_id = '81'
        self.biz.save()

    def _fake_entity(self):
        e = MagicMock(); e.Id = '71'; e.Active = True
        return e

    @patch('apps.qbo.services.QBOService.get_client', return_value=MagicMock())
    def test_business_deactivate_pushes_customer_and_vendor(self, _client):
        cust, vend = self._fake_entity(), self._fake_entity()
        with patch('quickbooks.objects.customer.Customer.get', return_value=cust), \
             patch('quickbooks.objects.vendor.Vendor.get', return_value=vend):
            ContactService.deactivate_business(self.biz)
        self.assertFalse(cust.Active); cust.save.assert_called_once()
        self.assertFalse(vend.Active); vend.save.assert_called_once()
        self.biz.refresh_from_db(); self.assertFalse(self.biz.is_active)
        self.assertEqual(QBOSyncLog.objects.filter(action='deactivate', status='success').count(), 2)
        # cascade-flipped contacts never push
        self.assertFalse(QBOSyncLog.objects.filter(entity_type='contact_customer').exists())

    @patch('apps.qbo.services.QBOService.get_client', return_value=MagicMock())
    def test_qbo_refusal_rolls_back_local_flip_and_logs_failure(self, _client):
        cust = self._fake_entity(); cust.save.side_effect = Exception('Customer has an open balance')
        with patch('quickbooks.objects.customer.Customer.get', return_value=cust):
            with self.assertRaises(ValidationError) as cm:
                ContactService.deactivate_business(self.biz)
        self.assertIn('QuickBooks refused to deactivate QCo', str(cm.exception))
        self.assertIn('open balance', str(cm.exception))
        self.biz.refresh_from_db(); self.assertTrue(self.biz.is_active)
        self.dc.refresh_from_db(); self.assertTrue(self.dc.is_active)
        self.assertTrue(QBOSyncLog.objects.filter(action='deactivate', status='failed').exists())

    def test_no_connection_skips_push(self):
        QBOConnection.objects.update(is_active=False)
        with patch('apps.qbo.services.QBOService.get_client') as gc:
            ContactService.deactivate_business(self.biz)
        gc.assert_not_called()
        self.biz.refresh_from_db(); self.assertFalse(self.biz.is_active)

    @patch('apps.qbo.services.QBOService.get_client', return_value=MagicMock())
    def test_no_qbo_id_skips_push(self, client):
        b2, _, _ = make_business('NoId')
        with patch('quickbooks.objects.customer.Customer.get') as get:
            ContactService.deactivate_business(b2)
        get.assert_not_called()

    @patch('apps.qbo.services.QBOService.get_client', return_value=MagicMock())
    def test_individual_contact_pushes_as_customer(self, _client):
        c = Contact.objects.create(first_name='Solo', last_name='Q', email='soloq@x.test', qbo_customer_id='99')
        cust = self._fake_entity()
        with patch('quickbooks.objects.customer.Customer.get', return_value=cust):
            ContactService.deactivate_contact(c)
            ContactService.reactivate_contact(c)
        self.assertEqual(QBOSyncLog.objects.filter(entity_type='contact_customer').count(), 2)
        self.assertTrue(QBOSyncLog.objects.filter(action='reactivate').exists())

    @patch('apps.qbo.services.QBOService.get_client', return_value=MagicMock())
    def test_push_to_qbo_false_skips(self, _client):
        with patch('quickbooks.objects.customer.Customer.get') as get:
            ContactService.deactivate_business(self.biz, push_to_qbo=False)
        get.assert_not_called()
```

`QBOConnection` may require more fields (`access_token_expires_at`, …) — copy the `setUp` of `tests/test_qbo_connection.py`.

- [ ] **Step 2: Run to see them fail**

Run: `timeout 600 python manage.py test tests.test_qbo_status_sync --noinput`
Expected: pushes never happen → assertions fail.

- [ ] **Step 3: Implement the sync methods**

In `apps/qbo/services.py`, on `QBOCustomerSyncService`:

```python
    @staticmethod
    def set_active(obj, active):
        """Flip the QBO Customer's Active flag for a Business (qbo_customer_id)
        or an individual Contact. Logged as action deactivate/reactivate.
        Raises on any QBO error (the caller decides what that means)."""
        from quickbooks.objects.customer import Customer
        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')
        customer = Customer.get(obj.qbo_customer_id, qb=client)
        customer.Active = bool(active)
        is_business = hasattr(obj, 'business_name')
        return QBOService.save_and_log(
            customer, client,
            entity_type='customer' if is_business else 'contact_customer',
            qbo_entity_type='Customer', entity_id=obj.pk,
            action='reactivate' if active else 'deactivate')


class QBOVendorSyncService:
    """Narrow vendor sync: only the Active flag (the bill-era push_vendor
    was retired 2026-07-23; vendor IDs come from the setup-time import)."""

    @staticmethod
    def set_active(business, active):
        from quickbooks.objects.vendor import Vendor
        client = QBOService.get_client()
        if not client:
            raise ValueError('No active QBO connection')
        vendor = Vendor.get(business.qbo_vendor_id, qb=client)
        vendor.Active = bool(active)
        return QBOService.save_and_log(
            vendor, client, entity_type='vendor', qbo_entity_type='Vendor',
            entity_id=business.pk, action='reactivate' if active else 'deactivate')
```

(`python-quickbooks` `save()` performs an update when `Id` is set and uses the `SyncToken` fetched by `get`.)

- [ ] **Step 4: Wire into `ContactService`**

Module-level in `apps/contacts/services.py`:

```python
def _push_status_to_qbo(obj, active):
    """Spec §6.6 failure policy: no QBO id or no connection → nothing to
    push. Otherwise QBO must accept; its error becomes the user's error and
    the caller never reaches the local flip."""
    from apps.qbo.services import (QBOCustomerSyncService, QBOService,
                                   QBOVendorSyncService)
    has_customer = bool(getattr(obj, 'qbo_customer_id', None))
    has_vendor = bool(getattr(obj, 'qbo_vendor_id', None))
    if not (has_customer or has_vendor):
        return
    if QBOService.get_active_connection() is None:
        return
    verb = 'reactivate' if active else 'deactivate'
    try:
        if has_customer:
            QBOCustomerSyncService.set_active(obj, active)
        if has_vendor:
            QBOVendorSyncService.set_active(obj, active)
    except Exception as e:  # QBO/network/token — surfaced verbatim
        raise ValidationError(f'QuickBooks refused to {verb} {obj}: {e}')
```

In `deactivate_contact`, `reactivate_contact`, `deactivate_business`, `reactivate_business`: after the blocker check and **before** `with transaction.atomic():` add `if push_to_qbo: _push_status_to_qbo(<obj>, False|True)`. Cascaded contacts are flipped inside the transaction without any push.

- [ ] **Step 5: Run**

Run: `timeout 900 python manage.py test tests.test_qbo_status_sync tests.test_contacts_status tests.test_qbo_customer_sync --noinput`
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add apps/qbo/services.py apps/contacts/services.py tests/test_qbo_status_sync.py
git commit -m "feat(qbo): push customer/vendor Active flag on deactivate/reactivate; QBO refusal blocks the flip

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 18: Pull status on import — snapshot, suggestions, commit, panel

**Files:**
- Modify: `apps/qbo/import_services.py` (`QBOSnapshotService.pull`, `QBOSuggestionService._contacts`, `_commit_contacts`), `frontend/src/components/qboimport/ContactsImportPanel.svelte`, `fixtures/playwright/seed.json` (the `qbo_import_snapshot` Configuration row + one business's `qbo_customer_id`)
- Tests: `tests/test_qbo_import_pull.py`, `tests/test_qbo_import_suggestions.py`, `tests/test_qbo_import_commit_contacts.py`, `frontend/tests/components/qboimport/Wrappers.test.js`, `e2e/specs/contacts/import-status.spec.js` (new)

**Interfaces:**
- Snapshot rows gain `'active': bool` (customers and vendors). Suggestion row states gain `'qbo_inactive'` and `'qbo_active'`; commit payload rows accept `action: 'deactivate' | 'reactivate'`; the commit response counts gain `deactivated` / `reactivated` per kind, and refusals land in the existing `skipped` list as `{name, reason}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_qbo_import_pull.py` — extend `_run_pull` so `Customer.filter` is called twice (Active=True then Active=False) and assert each stored customer/vendor row carries `active` (True for the first page, False for the second).

`tests/test_qbo_import_suggestions.py` — add:

```python
class ContactStatusSuggestionTest(TestCase):
    def setUp(self):
        from tests.test_qbo_import_state import SNAPSHOT
        snap = json.loads(json.dumps(SNAPSHOT))
        snap['customers'][0]['active'] = False                        # Acme inactive in QBO
        snap['customers'].append({'qbo_id': '72', 'display_name': 'Ghost', 'company_name': 'Ghost',
                                  'given_name': '', 'family_name': '', 'email': '', 'phone': '',
                                  'term_qbo_id': '', 'active': False})   # unmatched → dropped
        Configuration.objects.update_or_create(key=QBOSnapshotService.KEY, defaults={'value': json.dumps(snap)})
        dc = Contact.objects.create(first_name='Jo', last_name='Acme', email='jo@acme.com')
        self.biz = Business.objects.create(business_name='Acme Corp', default_contact=dc, qbo_customer_id='71')

    def test_qbo_inactive_vs_local_active(self):
        rows = QBOSuggestionService.suggestions('contacts')['rows']
        by_id = {r['qbo_id']: r for r in rows}
        self.assertEqual(by_id['71']['state'], 'qbo_inactive')
        self.assertNotIn('72', by_id)

    def test_qbo_active_vs_local_inactive(self):
        ContactService.deactivate_business(self.biz, push_to_qbo=False)
        snap = QBOSnapshotService.load(); snap['customers'][0]['active'] = True
        Configuration.objects.update_or_create(key=QBOSnapshotService.KEY, defaults={'value': json.dumps(snap)})
        rows = QBOSuggestionService.suggestions('contacts')['rows']
        self.assertEqual({r['qbo_id']: r['state'] for r in rows}['71'], 'qbo_active')

    def test_missing_active_key_means_active(self):
        snap = QBOSnapshotService.load(); snap['customers'][0].pop('active')
        Configuration.objects.update_or_create(key=QBOSnapshotService.KEY, defaults={'value': json.dumps(snap)})
        rows = QBOSuggestionService.suggestions('contacts')['rows']
        self.assertIn({r['qbo_id']: r['state'] for r in rows}['71'], ('imported', 'changed'))
```

`tests/test_qbo_import_commit_contacts.py` — add:

```python
class CommitStatusTest(TestCase):
    def setUp(self):
        from tests.test_qbo_import_state import store_snapshot
        store_snapshot()
        dc = Contact.objects.create(first_name='Jo', last_name='Acme', email='jo@acme.com')
        self.biz = Business.objects.create(business_name='Acme Corp', default_contact=dc, qbo_customer_id='71')
        dc.business = self.biz; dc.save()

    def _row(self, action):
        return dict(_payload()['customers'][0], action=action)

    def test_deactivate_row_flips_locally_without_push(self):
        with patch('apps.contacts.services._push_status_to_qbo') as push:
            out = QBOImportCommitService.commit_contacts({'customers': [self._row('deactivate')], 'vendors': []})
        push.assert_not_called()
        self.assertEqual(out['customers']['deactivated'], 1)
        self.biz.refresh_from_db(); self.assertFalse(self.biz.is_active)

    def test_deactivate_row_with_blocker_is_skipped_with_reason(self):
        from tests.test_contacts_status import make_job
        from apps.jobs.models import Job
        make_job(self.biz.default_contact, Job.STATUS_DRAFT)
        out = QBOImportCommitService.commit_contacts({'customers': [self._row('deactivate')], 'vendors': []})
        self.assertEqual(out['customers']['deactivated'], 0)
        self.assertIn('1 open job', out['customers']['skipped'][0]['reason'])
        self.biz.refresh_from_db(); self.assertTrue(self.biz.is_active)

    def test_reactivate_row_cascades(self):
        ContactService.deactivate_business(self.biz, push_to_qbo=False)
        out = QBOImportCommitService.commit_contacts({'customers': [self._row('reactivate')], 'vendors': []})
        self.assertEqual(out['customers']['reactivated'], 1)
        self.biz.refresh_from_db(); self.assertTrue(self.biz.is_active)
        self.assertTrue(self.biz.default_contact.is_active)
```

`Wrappers.test.js` — add: a `qbo_inactive` row renders the action word "deactivate" and is **unchecked** by default; a `qbo_active` row renders "reactivate" and is checked; the commit payload carries `action: 'deactivate'` / `'reactivate'`.

- [ ] **Step 2: Run to see them fail**

Run: `timeout 900 python manage.py test tests.test_qbo_import_pull tests.test_qbo_import_suggestions tests.test_qbo_import_commit_contacts --noinput` and `cd frontend && npm run test:run -- tests/components/qboimport`
Expected: FAIL.

- [ ] **Step 3: Pull**

In `QBOSnapshotService.pull`, replace the customer loop with:

```python
        for active in (True, False):
            for c in _all(Customer, client, Active=active):
                customers.append({... existing keys ..., 'active': active})
```

and the same for vendors.

- [ ] **Step 4: Suggestions**

In `_contacts`, for a **matched** customer row, before computing `changed`:

```python
                qbo_active = c.get('active', True)
                local = business if business is not None else contact
                if not qbo_active and local.is_active:
                    rows.append({'kind': 'customer', 'state': 'qbo_inactive', **c}); continue
                if qbo_active and not local.is_active:
                    rows.append({'kind': 'customer', 'state': 'qbo_active', **c}); continue
```

For an **unmatched** row with `c.get('active', True) is False` → `continue` (never imported). Same two blocks for vendors with `existing` as the local. `QBOImportSummary.diff_summary` should count inactive unmatched rows as neither new nor imported — subtract them from `total` so the pull summary stays honest.

- [ ] **Step 5: Commit actions**

At the top of the customers loop in `_commit_contacts` (and mirrored in the vendors loop), before the `create`/else branches:

```python
            if row['action'] in ('deactivate', 'reactivate'):
                business = Business.objects.filter(qbo_customer_id=row['qbo_id']).first()
                target = business or Contact.objects.filter(qbo_customer_id=row['qbo_id']).first()
                if target is None:
                    skip('customers', row, 'not found in konbini — pull again'); continue
                fn = {
                    ('deactivate', True): ContactService.deactivate_business,
                    ('reactivate', True): ContactService.reactivate_business,
                    ('deactivate', False): ContactService.deactivate_contact,
                    ('reactivate', False): ContactService.reactivate_contact,
                }[(row['action'], business is not None)]
                try:
                    with transaction.atomic():      # per-row savepoint — a refusal must not abort the batch
                        fn(target, push_to_qbo=False)
                except ValidationError as e:
                    skip('customers', row, e.messages[0]); continue
                counts['customers'][row['action'] + 'd'] += 1
                continue
```

Initialize `counts[...]['deactivated'] = 0` / `['reactivated'] = 0` for both kinds. Vendors resolve `Business.objects.filter(qbo_vendor_id=...)` and always use the business functions. Import `ContactService` from `apps.contacts.services` inside the function.

- [ ] **Step 6: Panel**

`ContactsImportPanel.svelte`: `withAction` becomes

```js
    const ACTION = { changed: 'update', qbo_inactive: 'deactivate', qbo_active: 'reactivate' };
    const withAction = (r) => ({ ...r, action: ACTION[r.state] || 'create' });
```

the Action cells render `{ACTION[row.state] || 'create'}`; pass `defaultChecked={(r) => r.state !== 'qbo_inactive'}` to `<SuggestionPanel>`; the warnings summary line generalizes to "couldn't be applied". Add a `<small>` under a `qbo_inactive` row: "inactive in QuickBooks — deactivating here checks for open jobs, invoices, and POs first".

- [ ] **Step 7: E2E seed + spec**

In `fixtures/playwright/seed.json`: (a) in the `core.configuration` row `qbo_import_snapshot`, add `"active": true` to every customer/vendor row and append one customer `{"qbo_id": "e2e-inactive-1", "display_name": "Dormant Customer E2E", "company_name": "Dormant Customer E2E", "given_name": "", "family_name": "", "email": "", "phone": "", "term_qbo_id": "", "active": false}`; (b) set `qbo_customer_id: "e2e-inactive-1"` on one seed business that has no open jobs/invoices/POs (find one by shape with a small scratch script; record its name in the spec). Flag this seed edit explicitly in the commit body — it goes beyond the phone fold.

`e2e/specs/contacts/import-status.spec.js`: load `/#/contacts`, expect the panel row "Dormant Customer E2E" with action "deactivate" and its checkbox unchecked; check it, Apply selected; expect the business page (by its name) to show the `inactive` badge; then Reactivate from its page.

- [ ] **Step 8: Run everything in this task**

Run: `timeout 900 python manage.py test tests.test_qbo_import_pull tests.test_qbo_import_suggestions tests.test_qbo_import_commit_contacts tests.test_qbo_import_state --noinput`; `cd frontend && npm run test:run`; `cd e2e && timeout 900 npx playwright test specs/contacts/import-status.spec.js specs/contacts/import-skip-report.spec.js`
Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add apps/qbo/import_services.py frontend fixtures/playwright/seed.json tests e2e/specs/contacts/import-status.spec.js
git commit -m "feat(qbo): import pulls inactive customers/vendors; qbo_inactive/qbo_active suggestions commit through the status services

Seed edit beyond the phone fold: one business gets a qbo_customer_id and the snapshot gains an inactive customer row for the e2e flow.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 19: QBO docs, hand-testing checklist, spec decisions note

**Files:**
- Modify: `docs/designs/quickbooks-integration.md` ("Customer sync" gains the Active push; "Vendor sync — retired" becomes "Vendor sync — Active flag only"; "Setup-time data import" gains the inactive pull, the two states, the per-row refusal; "API endpoints" unchanged; the failure policy and the push-before-flip ordering)
- Modify: `docs/designs/contacts-and-businesses.md` status section — "business contacts have no QBO status" note
- Modify: `docs/ui-flows/QuickBooks-Sync.md` — append the hand-testing checklist below as a new "§ Customer/Vendor status sync (sandbox hand test)" section
- Modify: `docs/plans/2026-10-11-contacts-refine-design.md` §10 — one line: "Push runs after blockers and before the local flip (outside the transaction) so a failed push's sync-log row survives."

- [ ] **Step 1:** Write the doc sections from the shipped code.
- [ ] **Step 2:** Paste the checklist (next section of this plan) into `docs/ui-flows/QuickBooks-Sync.md`, converting the table rows to that doc's `[ ]` checkbox convention.
- [ ] **Step 3: Commit**

```bash
git add docs
git commit -m "docs(qbo): status sync, failure policy, and the sandbox hand-test checklist

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 20: Final verification

- [ ] **Step 1:** `grep -rn "mobile_number\|work_number\|home_number\|business_phone" apps frontend/src frontend/tests tests e2e nealsdata docs/designs` → only the migration file and explicitly historical doc notes.
- [ ] **Step 2:** Full backend suite, fresh DB, foreground: `timeout 3600 python manage.py test --noinput 2>&1 | tee <scratchpad>/full-suite.log`; then `grep -E "^(OK|FAILED|Ran )" <scratchpad>/full-suite.log` — the gate is the `OK` line and the `Ran N tests` count, never the pipe's exit code.
- [ ] **Step 3:** `cd frontend && npm run test:run` → green; `npm run build` → no errors.
- [ ] **Step 4:** `cd e2e && timeout 2400 npx playwright test` → green (or named seed-gap skips only).
- [ ] **Step 5:** Report to RM: commit list, the three suite summary lines, any skipped e2e with reason, and that the branch is ready for browser review. Do not merge, push, or open a PR.

---

## QBO status sync — hand-testing plan (sandbox)

Run after Task 18 lands, against the **sandbox** company only. Preconditions: dev stack up (`runserver` + `npm run dev`), `.env` has `QBO_ENVIRONMENT=sandbox`, Settings → QuickBooks shows Connected, and a pull has been done from the Contacts page so the snapshot exists. Log in as a user with `can_manage_jobs` **and** `can_manage_config`. Keep the QBO sandbox UI open in a second tab (Sales → Customers, Expenses → Vendors, with "Include inactive" enabled in the gear menu). "Sync log" means Django admin → QBO → QBO sync logs.

| # | Setup | Action | Expected in konbini | Expected in QBO | Record |
|---|---|---|---|---|---|
| 1 | Business **B1** created in konbini, invoice sent once so it has `qbo_customer_id`; no vendor id; no open records | Business page → Deactivate → Continue | Badge `inactive`; its contacts inactive; history shows the flip; sync log row `customer / deactivate / success` | Customer inactive (name suffix per Task 16 finding) | ☐ |
| 2 | (after 1) | Reactivate | Badge gone; contacts back; sync log `customer / reactivate / success` | Customer active; name restored? (record) | ☐ |
| 3 | Business **B2** imported as both customer and vendor (same-name merge) | Deactivate → Continue | Two sync log rows: `customer` and `vendor`, both success | Customer **and** Vendor inactive | ☐ |
| 4 | (after 3) | Reactivate | Two `reactivate / success` rows | Both active | ☐ |
| 5 | Individual contact **C1** (no business) pushed as customer | Deactivate | Sync log `contact_customer / deactivate / success` | Customer inactive | ☐ |
| 6 | Business **B3** with 3 contacts and a customer id | Deactivate → Continue | 1 sync log row only (the business); no rows for the 3 contacts | One Customer inactive | ☐ |
| 7 | Business **B4** never pushed (no QBO ids) | Deactivate / Reactivate | Flips; **no** sync log rows | nothing | ☐ |
| 8 | Settings → QuickBooks → Disconnect; B1 active | Deactivate B1 | Flips locally; no sync log row; no error | unchanged (still active) | ☐ |
| 9 | (after 8) Reconnect; Contacts → Pull | Panel | B1 row appears as **reactivate** (QBO active, local inactive) — this is the documented disconnected-push gap; Apply → B1 active again, no push row | unchanged | ☐ |
| 10 | In QBO sandbox create an unpaid invoice for B1's customer (Task 16 finding (b) says whether QBO refuses) | Deactivate B1 | If QBO refuses: red message "QuickBooks refused to deactivate B1: …", B1 **stays active**, sync log `deactivate / failed` with the QBO text. If QBO accepts: as #1 | per finding | ☐ |
| 11 | Unpaid bill in QBO for B2's vendor | Deactivate B2 | Per finding (b) for vendors; if refused, the customer push that ran first must **not** have left QBO half-flipped — check the Customer is still active (if it isn't, file it: push order needs an all-or-nothing pre-check) | per finding | ☐ |
| 12 | Let the access token expire (or set `access_token_expires_at` in the past via admin) | Deactivate B3 | Token refresh happens silently; success | inactive | ☐ |
| 13 | In QBO: make B3's customer inactive by hand; konbini: Contacts → Pull | Panel | B3 row state **deactivate**, unchecked by default, with the hint text | — | ☐ |
| 14 | (after 13) B3 has an open job | Check row → Apply | Row stays; warning "1 contact couldn't be applied: B3: Cannot deactivate B3: 1 open job (…)"; B3 active; **no** sync log row | — | ☐ |
| 15 | (after 14) close the job | Apply again | B3 inactive + contacts inactive; no sync log row (QBO already agrees) | — | ☐ |
| 16 | In QBO: make B3's customer active again; Pull | Panel → Apply the **reactivate** row | B3 + all contacts active; no push row | — | ☐ |
| 17 | In QBO: create a brand-new customer and immediately make it inactive; Pull | Panel | It does **not** appear (unmatched inactive rows are dropped); pull summary counts exclude it | — | ☐ |
| 18 | B2 (both roles): in QBO inactivate only the Vendor; Pull | Panel | One **deactivate** row (vendor kind); the customer row reads imported. Apply → B2 inactive locally; next Pull shows the customer row as **reactivate** (QBO customer still active) — record whether that round-trip is acceptable or needs a both-roles rule | — | ☐ |
| 19 | A konbini business **B5** whose name equals an **inactive** QBO customer; send B5's first invoice | Invoice send | Per Task 16 finding (c): either adopts (and the sync log shows which id) or errors with the duplicate-name text; no 500 | — | ☐ |
| 20 | Any of the above | Settings → QuickBooks sync failures panel | Status-push failures do **not** appear there (money pushes only) and the panel does not error with status rows in the log | — | ☐ |
| 21 | B1 inactive | Job detail of a closed job on B1's contact; PO detail on B1 as vendor | Frozen banner; Change contact… offered only if B1 itself is active (here: not) | — | ☐ |
| 22 | Regression | Send an invoice for an active business pushed earlier | Unchanged behavior; phone on the QBO customer equals the business's **first** phone entry | PrimaryPhone matches | ☐ |

Record every "per finding" cell and anything surprising in `docs/designs/quickbooks-integration.md` under the sandbox-findings subsection, then delete the probe customer/vendor in the sandbox (or leave them inactive, named "konbini probe …").

