# Permission Atom Test Coverage Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exhaustively test every permission atom against every API endpoint it gates — both allowed and denied — without relying on groups.

**Architecture:** Each test user gets exactly one atom via direct assignment (no groups). Every API endpoint is tested against the atom it requires and against atoms that should NOT grant access. Future atoms (`can_manage_time`, `can_approve_expenses`) get placeholder test classes ready to fill in when endpoints exist.

**Tech Stack:** Django TestCase, DRF APIClient, existing fixture data

**Scope:** API endpoints only. HTML views are legacy and will be replaced by the Svelte SPA — no new test investment there.

**Depends on:** `docs/plans/2026-03-24-permission-atom-redesign.md` — the atom changes must be implemented before these tests can run.

---

## Design Principles

1. **Test atoms, not groups.** Groups are data that may change. Atoms are baked into code.
2. **One atom per test user.** Each user holds exactly one permission atom via `user_permissions.add()`. No group membership.
3. **Test both directions.** For each endpoint: a user with the correct atom succeeds, AND a user with a different atom is denied (403).
4. **Permission check only.** We only care whether the response is 403 or not-403. Validation errors (400), not-found (404), and success (200/201) all count as "permission passed." This keeps tests decoupled from business logic.
5. **Cover custom actions.** Status transitions, sub-resource CRUD, and one-off actions (link-email, generate-estimate, etc.) all need coverage.

## Relationship to Existing Tests

**Keep:** `tests/test_permissions.py` — atom existence, factory, group mappings (updated to match new atoms/groups).

**Replace:** `tests/test_api_permissions.py` — the existing file tests a worker user from a fixture group. The new file tests atoms directly and covers far more endpoints. Delete the old file once the new one is green.

## File Structure

```
tests/
├── test_permissions.py              # KEEP — atom existence, factory, group mappings (updated)
├── test_api_permissions.py          # DELETE after new file is green
└── test_atom_api_permissions.py     # NEW — atom-level API endpoint tests
```

## Test User Setup (shared base class)

```python
from rest_framework.test import APIClient

class AtomPermissionTestBase(BaseTestCase):
    """
    Base class that creates one test user per permission atom.
    Each user has ONLY that atom — no group membership.

    NOTE: Django caches permissions on User instances. Users created in
    setUp() and not modified afterward are safe. If any test adds or
    removes permissions mid-test, re-fetch the user from the database
    to clear the cache: user = User.objects.get(pk=user.pk)
    """

    def setUp(self):
        super().setUp()
        self.client = APIClient()

        # Create fresh users with exactly one atom each (no groups)
        self.users = {}
        atoms = [
            'can_view_financials', 'can_manage_jobs',
            'can_manage_financials', 'can_manage_time',
            'can_approve_expenses', 'can_manage_config',
        ]
        for atom in atoms:
            user = User.objects.create_user(
                username=f'user_{atom}',
                password='testpass',
            )
            perm = Permission.objects.get(
                codename=atom, content_type__app_label='core'
            )
            user.user_permissions.add(perm)
            self.users[atom] = user

        # A user with NO permissions at all (authenticated but bare)
        self.bare_user = User.objects.create_user(
            username='bare_user', password='testpass'
        )
```

Helper methods:

```python
def assert_allowed(self, user, method, url, data=None):
    """Assert the request is NOT blocked by permissions (not 403)."""
    self.client.force_authenticate(user=user)
    response = getattr(self.client, method)(url, data, format='json')
    self.assertNotEqual(response.status_code, 403,
        f"{user.username} should be allowed {method.upper()} {url}")
    return response

def assert_denied(self, user, method, url, data=None):
    """Assert the request IS blocked by permissions (403)."""
    self.client.force_authenticate(user=user)
    response = getattr(self.client, method)(url, data, format='json')
    self.assertEqual(response.status_code, 403,
        f"{user.username} should be denied {method.upper()} {url}")
    return response

def assert_requires_auth(self, method, url, data=None):
    """Assert unauthenticated request returns 401 or 403."""
    self.client.force_authenticate(user=None)
    response = getattr(self.client, method)(url, data, format='json')
    self.assertIn(response.status_code, [401, 403])
```

**`subTest` caveat:** When looping over URLs with `self.subTest()`, an unexpected exception (as opposed to an assertion failure) will abort the entire test method. If this becomes an issue, wrap the body in `try/except` within each subTest block. In practice, permission checks either return a status code or raise `PermissionDenied` (which DRF catches), so this is unlikely.

---

## Endpoint-to-Atom Map

This is the authoritative reference the tests are written against. If a test fails, either the code or this map needs updating.

### Endpoints requiring only `IsAuthenticated` (any logged-in user)

| Endpoint | Method |
|----------|--------|
| `/api/jobs/` | GET |
| `/api/jobs/{id}/` | GET |
| `/api/jobs/{id}/history/` | GET |
| `/api/estimates/` | GET |
| `/api/estimates/{id}/` | GET |
| `/api/estimates/{id}/line-items/` | GET |
| `/api/est-worksheets/` | GET |
| `/api/est-worksheets/{id}/` | GET |
| `/api/est-worksheets/{id}/tasks/` | GET |
| `/api/est-worksheets/{id}/bundles/` | GET |
| `/api/work-orders/` | GET |
| `/api/work-orders/{id}/` | GET |
| `/api/work-orders/{id}/tasks/` | GET |
| `/api/work-orders/{id}/bundles/` | GET |
| `/api/work-orders/{id}/tasks/{tid}/bleps/` | GET |
| `/api/contacts/` | GET |
| `/api/contacts/{id}/` | GET |
| `/api/contacts/{id}/history/` | GET |
| `/api/businesses/` | GET |
| `/api/businesses/{id}/` | GET |
| `/api/businesses/{id}/history/` | GET |
| `/api/payment-terms/` | GET |
| `/api/payment-terms/{id}/` | GET |
| `/api/work-order-templates/` | GET |
| `/api/work-order-templates/{id}/` | GET |
| `/api/task-templates/` | GET |
| `/api/task-templates/{id}/` | GET |
| `/api/line-item-types/` | GET |
| `/api/line-item-types/{id}/` | GET |
| `/api/emails/` | GET |
| `/api/emails/{id}/` | GET |
| `/api/search/?q=...` | GET |
| `/api/price-list-items/` | GET |
| `/api/price-list-items/{id}/` | GET |

### Endpoints gated by `can_view_financials` (read)

| Endpoint | Method |
|----------|--------|
| `/api/invoices/` | GET |
| `/api/invoices/{id}/` | GET |
| `/api/invoices/{id}/line-items/` | GET |
| `/api/purchase-orders/` | GET |
| `/api/purchase-orders/{id}/` | GET |
| `/api/purchase-orders/{id}/line-items/` | GET |
| `/api/bills/` | GET |
| `/api/bills/{id}/` | GET |
| `/api/bills/{id}/line-items/` | GET |

### Endpoints gated by `can_manage_jobs` (write)

| Endpoint | Method |
|----------|--------|
| `/api/jobs/` | POST |
| `/api/jobs/{id}/` | PUT, PATCH, DELETE |
| `/api/jobs/{id}/notes/` | POST |
| `/api/jobs/{id}/complete/` | POST |
| `/api/jobs/{id}/cancel/` | POST |
| `/api/jobs/{id}/reopen/` | POST |
| `/api/contacts/` | POST |
| `/api/contacts/{id}/` | PUT, PATCH, DELETE |
| `/api/contacts/{id}/notes/` | POST |
| `/api/businesses/` | POST |
| `/api/businesses/{id}/` | PUT, PATCH, DELETE |
| `/api/businesses/{id}/set-default-contact/` | POST |
| `/api/businesses/{id}/notes/` | POST |
| `/api/estimates/` | POST |
| `/api/estimates/{id}/` | PUT, PATCH, DELETE |
| `/api/estimates/{id}/line-items/` | POST |
| `/api/estimates/{id}/line-items/{lid}/` | PATCH, DELETE |
| `/api/estimates/{id}/line-items/reorder/` | POST |
| `/api/estimates/{id}/mark-open/` | POST |
| `/api/estimates/{id}/revise/` | POST |
| `/api/est-worksheets/` | POST |
| `/api/est-worksheets/{id}/` | PUT, PATCH, DELETE |
| `/api/est-worksheets/{id}/tasks/` | POST |
| `/api/est-worksheets/{id}/tasks/{tid}/` | PATCH, DELETE |
| `/api/est-worksheets/{id}/bundles/` | POST |
| `/api/est-worksheets/{id}/bundles/{bid}/` | PATCH, DELETE |
| `/api/est-worksheets/{id}/bundles/{bid}/add-tasks/` | POST |
| `/api/est-worksheets/{id}/bundles/{bid}/remove-tasks/` | POST |
| `/api/est-worksheets/{id}/generate-estimate/` | POST |
| `/api/est-worksheets/{id}/revise/` | POST |
| `/api/work-orders/` | POST |
| `/api/work-orders/{id}/` | PUT, PATCH, DELETE |
| `/api/work-orders/{id}/tasks/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/` | PATCH, DELETE |
| `/api/work-orders/{id}/bundles/` | POST |
| `/api/work-orders/{id}/bundles/{bid}/` | PATCH, DELETE |
| `/api/work-orders/{id}/bundles/{bid}/add-tasks/` | POST |
| `/api/work-orders/{id}/bundles/{bid}/remove-tasks/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/start/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/complete/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/block/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/unblock/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/cancel/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/start-work/` | POST |
| `/api/work-orders/{id}/tasks/{tid}/stop-work/` | POST |
| `/api/work-orders/{id}/complete/` | POST |
| `/api/work-orders/{id}/block/` | POST |
| `/api/work-orders/{id}/reopen/` | POST |
| `/api/emails/{id}/link-to-job/` | POST |
| `/api/emails/{id}/unlink-from-job/` | POST |
| `/api/emails/{id}/create-job/` | POST |

### Endpoints gated by `can_manage_financials` (write)

| Endpoint | Method |
|----------|--------|
| `/api/invoices/` | POST |
| `/api/invoices/{id}/` | PUT, PATCH, DELETE |
| `/api/invoices/{id}/line-items/` | POST |
| `/api/invoices/{id}/line-items/{lid}/` | PATCH, DELETE |
| `/api/invoices/{id}/line-items/reorder/` | POST |
| `/api/invoices/{id}/cancel/` | POST |
| `/api/purchase-orders/` | POST |
| `/api/purchase-orders/{id}/` | PUT, PATCH, DELETE |
| `/api/purchase-orders/{id}/line-items/` | POST |
| `/api/purchase-orders/{id}/line-items/{lid}/` | PATCH, DELETE |
| `/api/purchase-orders/{id}/line-items/reorder/` | POST |
| `/api/purchase-orders/{id}/issue/` | POST |
| `/api/purchase-orders/{id}/cancel/` | POST |
| `/api/bills/` | POST |
| `/api/bills/{id}/` | PUT, PATCH, DELETE |
| `/api/bills/{id}/line-items/` | POST |
| `/api/bills/{id}/line-items/{lid}/` | PATCH, DELETE |
| `/api/bills/{id}/line-items/reorder/` | POST |
| `/api/bills/{id}/cancel/` | POST |
| `/api/price-list-items/` | POST |
| `/api/price-list-items/{id}/` | PUT, PATCH, DELETE |

### Endpoints gated by `can_manage_config` (write)

| Endpoint | Method |
|----------|--------|
| `/api/settings/` | GET, PATCH |
| `/api/work-order-templates/` | POST |
| `/api/work-order-templates/{id}/` | PUT, PATCH, DELETE |
| `/api/task-templates/` | POST |
| `/api/task-templates/{id}/` | PUT, PATCH, DELETE |
| `/api/line-item-types/` | POST |
| `/api/line-item-types/{id}/` | PUT, PATCH, DELETE |

### Endpoints gated by `can_manage_time` (future — no endpoints yet)

_Reserved. Tests will be added as time-tracking endpoints are implemented._

Candidates: `/api/shifts/`, `/api/time-tracking/`, blep CRUD (if separated from task lifecycle)

### Endpoints gated by `can_approve_expenses` (future — no endpoints yet)

_Reserved. Tests will be added as expense endpoints are implemented._

Candidates: `/api/expenses/`, expense approval actions

---

## Task 1: Create shared base class and helpers

**Files:**
- Create: `tests/test_atom_api_permissions.py`

- [ ] **Step 1: Write the base class for API tests**

Write `AtomPermissionTestBase` in `tests/test_atom_api_permissions.py` as described in the "Test User Setup" section above. Include `assert_allowed`, `assert_denied`, `assert_requires_auth` helpers on the base class. Use `APIClient` from DRF.

- [ ] **Step 2: Run to verify base class loads**

Run: `python manage.py test tests.test_atom_api_permissions -v2`
Expected: 0 tests found (no test methods yet), no import errors.

- [ ] **Step 3: Commit**

```bash
git add tests/test_atom_api_permissions.py
git commit -m "test: add base class for atom-level permission tests"
```

---

## Task 2: `IsAuthenticated`-only endpoints

**Files:**
- Modify: `tests/test_atom_api_permissions.py`

- [ ] **Step 1: Write test class `TestAuthenticatedOnlyAPI`**

Test that `bare_user` (no atoms) CAN access all endpoints in the "Endpoints requiring only IsAuthenticated" table. Test that unauthenticated requests are denied.

This ensures these endpoints don't accidentally pick up a permission requirement. This is the largest table — use `self.subTest()` loops for list endpoints and detail/sub-resource endpoints separately.

- [ ] **Step 2: Run tests**

Run: `python manage.py test tests.test_atom_api_permissions.TestAuthenticatedOnlyAPI -v2`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_atom_api_permissions.py
git commit -m "test: authenticated-only API endpoints"
```

---

## Task 3: `can_view_financials` — API read access

**Files:**
- Modify: `tests/test_atom_api_permissions.py`

- [ ] **Step 1: Write test class `TestCanViewFinancialsAPI`**

Test that `user_can_view_financials` is ALLOWED to GET every endpoint in the "Endpoints gated by `can_view_financials`" table. Test that `bare_user` (no permissions) is DENIED on those same endpoints. Test that `user_can_manage_jobs` (wrong atom) is also DENIED.

Test that unauthenticated requests are denied.

```python
class TestCanViewFinancialsAPI(AtomPermissionTestBase):
    """can_view_financials grants read access to financial documents."""

    READ_URLS = [
        '/api/invoices/', '/api/purchase-orders/',
        '/api/bills/',
    ]

    def test_can_view_financials_allows_read(self):
        user = self.users['can_view_financials']
        for url in self.READ_URLS:
            with self.subTest(url=url):
                self.assert_allowed(user, 'get', url)

    def test_bare_user_denied_read(self):
        for url in self.READ_URLS:
            with self.subTest(url=url):
                self.assert_denied(self.bare_user, 'get', url)

    def test_wrong_atom_denied(self):
        user = self.users['can_manage_jobs']
        for url in self.READ_URLS:
            with self.subTest(url=url):
                self.assert_denied(user, 'get', url)
```

Also test detail and sub-resource URLs using fixture IDs.

- [ ] **Step 2: Run tests**

Run: `python manage.py test tests.test_atom_api_permissions.TestCanViewFinancialsAPI -v2`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_atom_api_permissions.py
git commit -m "test: can_view_financials API read access"
```

---

## Task 4: `can_manage_jobs` — API write access

**Files:**
- Modify: `tests/test_atom_api_permissions.py`

- [ ] **Step 1: Write test class `TestCanManageJobsAPI`**

Test that `user_can_manage_jobs` can POST/PUT/PATCH/DELETE on every endpoint in the "Endpoints gated by `can_manage_jobs`" table. Test that `bare_user` is DENIED. Test that `user_can_manage_financials` (wrong atom) is also DENIED.

Organize write URLs as a list of `(method, url, data)` tuples:

```python
WRITE_ENDPOINTS = [
    ('post', '/api/jobs/', {'customer': 1}),
    ('post', '/api/contacts/', {'first_name': 'T', 'last_name': 'U'}),
    ('post', '/api/businesses/', {'business_name': 'T'}),
    # ... status transitions, sub-resources, etc.
]
```

For sub-resource writes (tasks, bundles, line items), use fixture IDs.

- [ ] **Step 2: Test wrong-atom denial**

Verify that `user_can_manage_financials`, `user_can_view_financials`, and `user_can_manage_config` are all denied on `can_manage_jobs`-gated endpoints. Pick a representative sample (POST /api/jobs/, POST /api/contacts/) rather than exhaustive cross-product.

- [ ] **Step 3: Run tests**

Run: `python manage.py test tests.test_atom_api_permissions.TestCanManageJobsAPI -v2`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_atom_api_permissions.py
git commit -m "test: can_manage_jobs API write access"
```

---

## Task 5: `can_manage_financials` — API write access

**Files:**
- Modify: `tests/test_atom_api_permissions.py`

- [ ] **Step 1: Write test class `TestCanManageFinancialsAPI`**

Test that `user_can_manage_financials` is ALLOWED to write on invoices, invoice line items, POs, PO line items, bills, bill line items, and price list items. Test that `user_can_manage_jobs` (wrong atom) is DENIED. Test that `user_can_view_financials` (read-only atom) is DENIED.

Note: `can_manage_financials` does NOT grant `can_view_financials`, so for "allowed" tests on write endpoints, the user only needs the write atom — the permission check for POST/PUT/PATCH/DELETE uses `can_manage_financials`, not `can_view_financials`.

- [ ] **Step 2: Run tests**

Run: `python manage.py test tests.test_atom_api_permissions.TestCanManageFinancialsAPI -v2`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_atom_api_permissions.py
git commit -m "test: can_manage_financials API write access"
```

---

## Task 6: `can_manage_config` — API write access

**Files:**
- Modify: `tests/test_atom_api_permissions.py`

- [ ] **Step 1: Write test class `TestCanManageConfigAPI`**

Test settings GET/PATCH, template CRUD (work order templates, task templates), and line item type CRUD.

Note: `can_manage_config` gates even the GET on `/api/settings/` — this is different from templates and line item types where GET is `IsAuthenticated` only.

Test that `user_can_manage_jobs` is denied on all config endpoints.

- [ ] **Step 2: Run tests**

Run: `python manage.py test tests.test_atom_api_permissions.TestCanManageConfigAPI -v2`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_atom_api_permissions.py
git commit -m "test: can_manage_config API write access"
```

---

## Task 7: Future atoms — placeholder test classes

**Files:**
- Modify: `tests/test_atom_api_permissions.py`

- [ ] **Step 1: Add placeholder classes**

```python
class TestCanManageTimeAPI(AtomPermissionTestBase):
    """can_manage_time — no endpoints yet.

    When time-tracking endpoints are added (shifts, bleps CRUD,
    time-tracking reports), add tests here:
    - user_can_manage_time is ALLOWED
    - user_can_manage_jobs is DENIED
    - bare_user (all authenticated) can track their OWN time (implicit)
    """
    pass


class TestCanApproveExpensesAPI(AtomPermissionTestBase):
    """can_approve_expenses — no endpoints yet.

    When expense endpoints are added, add tests here:
    - user_can_approve_expenses is ALLOWED to approve/reject
    - user_can_manage_jobs is DENIED
    - any authenticated user can SUBMIT expenses (implicit)
    """
    pass
```

- [ ] **Step 2: Commit**

```bash
git add tests/test_atom_api_permissions.py
git commit -m "test: add placeholder classes for future permission atoms"
```

---

## Task 8: Delete old permission tests

**Files:**
- Delete: `tests/test_api_permissions.py`

- [ ] **Step 1: Run full test suite to confirm everything passes**

Run: `python manage.py test -v2`
Expected: All tests pass including the new atom tests.

- [ ] **Step 2: Delete old file**

```bash
git rm tests/test_api_permissions.py
```

- [ ] **Step 3: Run full test suite again**

Run: `python manage.py test -v2`
Expected: All tests still pass.

- [ ] **Step 4: Commit**

```bash
git commit -m "test: remove old group-based API permission tests"
```
