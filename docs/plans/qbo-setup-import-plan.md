# Gradual Setup + QBO Data Import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Seeded defaults, per-tenant email settings, derived per-area gating, and the QBO snapshot import with four distributed suggestion panels — per `docs/plans/qbo-setup-import-spec.md` (the spec governs on any conflict).

**Architecture:** Phase A (Tasks 1–6) is the setup foundation: data-migration defaults, DB-backed email config, `/api/setup/status` gates + greyed sidebar. Phase B (Tasks 7–16) is the import: snapshot pull service, per-kind diff/suggestion services reading the snapshot, per-kind commit services, and the shared suggestion-panel component embedded in four surfaces. Each phase ships working software.

**Tech Stack:** Django 5.2 + DRF, python-quickbooks (mocked at `QBOService`), Svelte 5, Vitest, Playwright.

## Global Constraints

- Branch `feature/qbo`; commit per task; never merge/push/PR.
- Never write the dev DB (no `migrate`/`shell`/`loaddata`); `makemigrations` OK; tests use `--noinput`, one runner at a time, never judge by piped exit codes; fresh DB (no `--keepdb`) after migration changes.
- Error contract: services raise `ValidationError` shapes per CLAUDE.md; frontend errors via `triageError`.
- Status constants, no `QuerySet.update()` where `save()` has side effects, line-item rules — per CLAUDE.md.
- New Configuration keys documented in `data-constraints.md` §1.1 in the same task that introduces them.
- E2E: fresh-tenant flows are impractical against the fully-seeded e2e DB; per-task Vitest is mandatory, e2e per the dedicated Task 16 (exemptions noted there).

## File Structure (new files)

- `apps/core/migrations/00XX_seed_setup_defaults.py` — data migration (Task 1)
- `apps/api/setup/__init__.py`, `apps/api/setup/views.py` — setup-status endpoint (Task 3)
- `apps/core/setup_gates.py` — gate predicates (Task 3)
- `apps/qbo/import_services.py` — snapshot pull + diff/suggestion + commit services (Tasks 7–11)
- `apps/api/qbo_import/__init__.py`, `apps/api/qbo_import/views.py` — pull/suggestions/commit/dismiss endpoints (Tasks 8–11)
- `frontend/src/components/settings/EmailAccountSettings.svelte` (Task 2)
- `frontend/src/stores/setupStatus.js`, `frontend/src/components/SetupCallout.svelte` (Task 4)
- `frontend/src/components/qboimport/SuggestionPanel.svelte` + per-kind wrappers (Tasks 12–15)
- Tests: `tests/test_setup_defaults_migration.py`, `tests/test_email_settings_db.py`, `tests/test_setup_status.py`, `tests/test_qbo_import_pull.py`, `tests/test_qbo_import_suggestions.py`, `tests/test_qbo_import_commit_*.py`, plus Vitest specs mirroring each component.

---

## PHASE A — Setup foundation

### Task 1: Seeded defaults data migration (+ units 500 fix)

**Files:** Create migration in `apps/core/migrations/`; Modify `apps/api/templates_config/views.py:~280`; Test `tests/test_setup_defaults_migration.py`, extend `tests/test_api_templates_config.py`.

**Interfaces — Produces:** on any migrated DB: AppState rows `job_counter`/`po_counter` (`'0'`), Configuration rows `job_number_sequence` (`'JOB-{year}-{counter:04d}'`), `po_number_sequence` (`'PO-{year}-{counter:04d}'`), `units_list` (JSON of `apps.core.units.DEFAULT_UNITS`). Idempotent (get_or_create; never overwrites existing values).

- [ ] **Step 1:** Failing tests: (a) migration test using `django.test.TestCase` asserting the four rows exist on a fresh test DB (the migration runs during test-DB build, so plain assertions suffice); (b) idempotency: calling the migration's forward function again changes nothing (import it directly and run with existing rows altered — values preserved); (c) units endpoint: with the `units_list` row deleted, `GET /api/settings/units/` returns 200 with `DEFAULT_UNITS`, not 500.
- [ ] **Step 2:** Run → FAIL (rows absent; endpoint 500s).
- [ ] **Step 3:** Write the data migration (`RunPython` with `get_or_create` on `AppState`/`Configuration` via `apps.get_model`; reverse = noop) and guard the units view: `try: … except Configuration.DoesNotExist: return Response({'units': DEFAULT_UNITS, …})` matching the endpoint's existing response shape (read it first).
- [ ] **Step 4:** Run both test modules fresh (no `--keepdb`) → OK. Also `python manage.py makemigrations --check --dry-run` → no new changes.
- [ ] **Step 5:** Update `data-constraints.md` §1.1 (seeded-by-migration note) and commit.

### Task 2: DB-backed email settings + Settings → Email credentials UI

**Files:** Modify `apps/core/services.py` (`EmailService` IMAP config read, `OutboundEmailService`/SMTP send path — find the `send_mail`/`EmailMessage` construction and connection), `apps/api/templates_config/views.py` (settings PATCH already generic — no change needed; verify), Create `apps/core/email_account.py` (config resolution helper), `frontend/src/components/settings/EmailAccountSettings.svelte`; Modify `frontend/src/routes/SettingsPage.svelte` (email tab: credentials component above `EmailTemplates`); new endpoint `POST /api/settings/email-verify/` in `apps/api/templates_config/views.py`. Tests: `tests/test_email_settings_db.py`, Vitest `frontend/tests/components/settings/EmailAccountSettings.test.js`.

**Interfaces — Produces:** `apps/core/email_account.py`:
```python
def email_account():
    """{'imap_server','address','password','smtp_host','smtp_port'} — each key
    Configuration-first (email_imap_server, email_address, email_password,
    email_smtp_host, email_smtp_port), env-settings fallback, '' when neither."""
def email_configured() -> bool:  # imap_server AND address AND password present
```
`EmailService.is_configured`/fetch paths and the SMTP send construct their connection from `email_account()` (SMTP via `django.core.mail.get_connection(host=…, port=…, username=…, password=…)` when DB-configured, default backend otherwise). Verify endpoint returns `{'imap': {'ok': bool, 'error': str}, 'smtp': {'ok': bool, 'error': str}}` (IMAP: login/logout; SMTP: connection open/close; both wrapped, never 500).

- [ ] **Step 1:** Failing tests: `email_account()` DB-first/env-fallback matrix (set Configuration rows vs `override_settings`); `email_configured()` truth table; `EmailService.is_configured` honors DB rows; verify endpoint mocked at `imaplib.IMAP4_SSL`/`smtplib` (or the `get_connection` boundary) returns the shape for ok and failure.
- [ ] **Step 2:** FAIL. **Step 3:** Implement helper + rewire the two read points + endpoint. **Step 4:** Run + `tests/test_outbound_email.py` regression → OK.
- [ ] **Step 5:** Vitest: form renders 5 fields from `/api/settings/`, saves via PATCH, verify button renders both results. Svelte component follows `GeneralSettings.svelte` patterns (`api.get('/api/settings/')`, `save(payload, label)`), password field `type="password"`, never echoes saved password (endpoint returns key-presence, not value — mask handling: display placeholder `********` when set; PATCH only when user typed). Run `npm --prefix frontend run test:run` → OK. Docs (`data-constraints.md` keys; `invoicing-and-expenses.md`/`architecture-and-conventions.md` email sections) + commit.

### Task 3: Gate predicates + `GET /api/setup/status`

**Files:** Create `apps/core/setup_gates.py`, `apps/api/setup/views.py`; Modify `apps/api/urls.py` (`path('setup/status/', …)`); Test `tests/test_setup_status.py`.

**Interfaces — Produces:**
```python
# apps/core/setup_gates.py
def gate_status() -> dict:
    # {'areas': {'email': {'available': bool, 'message': str}, 'catalog': …,
    #   'jobs': …, 'estimates': …, 'invoices': …, 'purchasing': …},
    #  'last_pull_at': str|None}
```
Predicates exactly per spec Part 3 table (email ← `email_configured()`; catalog ← `AccountingCategory.objects.exists() and RateScheme.objects.exists()`; jobs ← `Contact.objects.exists()`; estimates & invoices ← jobs; purchasing ← `Business.objects.exists()`). Messages verbatim from spec style ("Add your email service configuration on Settings → Email", "Create at least one accounting category and rate scheme in Settings", "Add a contact (or import your QBO customers) first", "Add a vendor business first"). `last_pull_at` from the snapshot key (None until Task 8 exists — read `qbo_import_snapshot` JSON if present). Endpoint: `IsAuthenticated`, returns `gate_status()`.

- [ ] **Step 1:** Failing tests: truth table per gate (empty DB → all unavailable except always-on; create one Contact → jobs+estimates+invoices flip; etc.), message text asserted, endpoint auth + shape.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** OK. **Step 5:** Docs (`users-and-permissions.md` endpoint row; `architecture-and-conventions.md` gating pattern section) + commit.

### Task 4: Sidebar gating + floating callouts + Home Help setup checklist

**Files:** Create `frontend/src/stores/setupStatus.js` (fetch-once store with `refresh()`, called on App mount and after panel commits), `frontend/src/components/SetupCallout.svelte`; Modify `frontend/src/components/Sidebar.svelte`, `frontend/src/App.svelte` (route guard: greyed area routes redirect to `/`), `frontend/src/components/home/HelpPanel.svelte` (setup checklist section shown while any gate unmet). Vitest: `frontend/tests/components/Sidebar.test.js` (extend), `SetupCallout.test.js`, `HelpPanel` spec extension.

**Interfaces — Consumes:** `/api/setup/status/` shape from Task 3. **Produces:** `setupStatus` store `{areas, last_pull_at, refresh()}`; Sidebar entries for gated areas render `<span class="nav-disabled">` (greyed, non-navigating) when unavailable, wrapped so hover shows `SetupCallout` — an absolutely-positioned box with a CSS-triangle pointer aimed at the entry, containing the gate message. Available areas render exactly as today (no callout markup at all).

- [ ] **Step 1:** Failing Vitest: with mocked store (email unavailable), the Email entry is a disabled span with callout text on hover; with all available, markup identical to today's; route guard redirects `/email` → `/` when gated; HelpPanel shows checklist lines for unmet gates and none when all met.
- [ ] **Step 2:** FAIL. **Step 3:** Implement (follow `viewMode.js` store idiom; callout CSS per component-scoped style). **Step 4:** `npm --prefix frontend run test:run` → OK. **Step 5:** Docs (`architecture-and-conventions.md` sidebar section) + commit.

### Task 5: PaymentTerms gets real fields

(Prerequisite for Phase B's terms import; independently useful.)

**Files:** Modify `apps/contacts/models.py` (`PaymentTerms`: add `name = CharField(100, blank True default '')`, `days = PositiveIntegerField(null=True, blank=True)`, `qbo_id = CharField(50, blank, default '')`, `__str__` returns name or pk), migration; `apps/api/contacts/serializers.py` keeps `fields='__all__'` (verify it now emits the new fields). Test: extend `tests/test_contact_business_associations.py` or the payment-terms API test module (find it: `grep -rln payment-terms tests/`).

- [ ] Steps: failing test (create term with name/days, serializer round-trip) → implement + `makemigrations contacts` → fresh-DB module runs → also fix `frontend/src/components/contacts/BusinessForm.svelte:97`, which renders `{term.term_id}` as the option label (bare pk today) — becomes `{term.name || term.term_id}` (+ Vitest) → docs (`contacts-and-businesses.md`, `data-constraints.md` §1.4) → commit.
- NOTE (recorded in LATER.md): PaymentTerms gets no management CRUD UI in this batch — the import creates rows and BusinessForm assigns them; a terms manager is follow-up work.

### Task 6: Phase A verification

- [ ] Full backend suite fresh, output to file, read the summary line → OK (only pre-existing `test_api_schedule` date-sensitivity may fail — verify against `main` before accepting any other failure). Full Vitest → OK. Commit any stragglers.

---

## PHASE B — QBO snapshot import

### Task 7: Snapshot fetch service

**Files:** Create `apps/qbo/import_services.py` (`QBOSnapshotService`); Test `tests/test_qbo_import_pull.py`.

**Interfaces — Produces:**
```python
class QBOSnapshotService:
    KEY = 'qbo_import_snapshot'
    @staticmethod
    def pull(client) -> dict   # fetches, stores Configuration[KEY], returns snapshot
    @staticmethod
    def load() -> dict | None  # parsed snapshot or None
```
Snapshot shape (versioned: `{'version': 1, 'fetched_at': iso, …}`):
`items`: [{qbo_id, name, type ('Service'|'NonInventory'|'Inventory'), unit_price, description, income_account_id, income_account_name, expense_account_id (two-sided else ''), purchase_cost, taxable (bool from SalesTaxCodeRef/Taxable heuristic — accept both raw-JSON capitalizations per the QBO gotcha doc note)}];
`income_accounts`/`expense_accounts`: [{qbo_id, name, type}];
`customers`: [{qbo_id, display_name, company_name, given_name, family_name, email, phone, term_qbo_id}];
`vendors`: [{qbo_id, display_name, company_name, email, phone}];
`terms`: [{qbo_id, name, due_days}].
Fetch via SDK `.filter(Active=True, qb=client)` per entity with pagination (`start_position`/`max_results=1000` loop — check the SDK's `.filter` kwargs; fall back to `.query` if needed). `fetched_at` = `timezone.now().isoformat()`.

- [ ] **Step 1:** Failing tests: mock SDK classes at import sites (pattern of `tests/test_qbo_accounts.py`); pull stores the blob (round-trips via `load()`), maps every field incl. the two-sided expense fields and Inventory-type inclusion; pagination loop exercised (two pages); `load()` None when absent.
- [ ] **Steps 2–4:** FAIL → implement → OK. **Step 5:** commit.

### Task 8: Pull/dismiss endpoints + diff summary

**Files:** Create `apps/api/qbo_import/views.py` + urls (`qbo/import/pull/`, `qbo/import/dismiss/`); Modify `apps/core/setup_gates.py` (`last_pull_at` now real); `apps/qbo/import_services.py` gains:
```python
class QBOImportState:
    DISMISS_KEY = 'qbo_import_dismissed'
    AREAS = ('categories', 'schemes', 'catalog', 'contacts')
    @staticmethod
    def dismissed() -> dict            # {area: True}
    @staticmethod
    def dismiss(area) / undismiss(area)
class QBOImportSummary:
    @staticmethod
    def diff_summary() -> dict  # counts per kind: total / already_imported / new
```
`POST /api/qbo/import/pull` body `{'area': <one of AREAS>}`: requires area-appropriate permission (`can_manage_config` for categories/schemes, `can_manage_financials` for catalog, `can_manage_jobs` for contacts — mirror each surface's own write permission), 400 `{'detail': 'No active QBO connection.'}` without connection; on success: runs `pull`, `undismiss(area)`, returns `{'fetched_at', 'summary': diff_summary()}`. `POST /api/qbo/import/dismiss` `{'area'}` sets the flag. Already-imported matching per kind by `qbo_id`-family fields (categories: `AccountingCategory.qbo_item_id in cluster item ids`; schemes/catalog: `qbo_id`; customers: `qbo_customer_id`; vendors `qbo_vendor_id`; terms `qbo_id`).

- [ ] TDD steps as usual (mock `QBOSnapshotService.pull`); tests cover permission per area, no-connection 400, undismiss-on-pull locality (dismiss `contacts`, pull from `catalog` → contacts stays dismissed), summary counts. Commit.

### Task 9: Suggestion services (diff computation per kind)

**Files:** `apps/qbo/import_services.py` gains `QBOSuggestionService`; endpoints `GET /api/qbo/import/suggestions/<area>/` in `apps/api/qbo_import/views.py`; Test `tests/test_qbo_import_suggestions.py`.

**Interfaces — Produces:** for each area, `suggestions(area) -> {'dismissed': bool, 'fetched_at': str|None, 'rows': […]}` — **short-circuit**: if `QBOImportState.dismissed()[area]` or no snapshot → `{'dismissed': …, 'rows': []}` with no snapshot parse beyond the one Configuration read (structure the code so `load()` is not called when dismissed).
- `categories` rows: clusters of sellable items by `income_account_id` + itemless income accounts; `{income_account: {id,name}, member_count, suggested: {name, code (auto-slug, unique vs existing), taxable (majority)}, fallback_item_options: [{qbo_id,name}], fallback_item_default, expense_account_default (majority ExpenseAccountRef of two-sided members, else ''), state: 'new'|'imported'}` (imported = an existing kAC's `qbo_item_id` is one of the cluster's item ids).
- `schemes` rows: one per snapshot Service item: `{qbo_item_id, name, rate (unit_price), algorithm_default: 'entered_qty', unit_default: 'ea', category: resolved kAC pk|None (via the fallback-Item→income-account chain from the spec), price_group (unit_price as string, for UI grouping), state: 'new'|'imported'}` (imported = a ServiceItem with that `qbo_id` exists).
- `catalog` rows: NonInventory+Inventory items → inventory rows `{qbo_id, code_suggestion (uniquified vs InventoryItem.code), description, selling_price, purchase_price, category: pk|None, state: 'new'|'imported'|'changed'}` (`changed` = imported and snapshot price/description differ); Service items → service rows `{qbo_id, name, scheme: pk|None (ServiceItem-less schemes matched by… the scheme created for this item in Task 10 records the item's qbo_id on the ServiceItem, so service rows are 'imported' when a ServiceItem with qbo_id exists; 'changed' when its scheme's current effective rate ≠ snapshot unit_price), state}.
- `contacts` rows: three sub-lists (customers/vendors/terms) with `{…fields, state: 'new'|'imported'|'changed'}` (changed = matched record's mirrored fields differ; customers match `qbo_customer_id` on Business or Contact; a same-display-name Customer+Vendor pair marked `merge_hint: True`).

- [ ] TDD: fixture snapshot dict (write once at top of test module, reuse) + DB arrangements per state; assert row shapes, short-circuit behavior (patch `QBOSnapshotService.load` and assert not called when dismissed), category-chain resolution incl. the unresolvable→None cases. Commit.

### Task 10: Commit services — categories & schemes

**Files:** `apps/qbo/import_services.py` gains `QBOImportCommitService.commit_categories(rows)` / `commit_schemes(rows)`; endpoints `POST /api/qbo/import/commit/categories/` & `/schemes/`; Test `tests/test_qbo_import_commit_categories.py`, `tests/test_qbo_import_commit_schemes.py`.

**Interfaces:** request rows are the user-confirmed subset: categories `[{name, code, taxable, qbo_item_id ('' allowed for itemless), qbo_expense_account_id ('' allowed)}]` → creates `AccountingCategory` rows (transaction.atomic; duplicate code → field ValidationError). Schemes `[{name, rate, algorithm, unit_label, accounting_category (pk), qbo_item_id, collapse_group: str|None}]` → creates one `RateScheme` per row EXCEPT rows sharing a non-null `collapse_group`, which create ONE scheme (first row's name/rate/etc.) — and creates NOTHING else (ServiceItems are Task 11); returns `{scheme_pk_by_qbo_item_id}` mapping used by the UI to hand off to the catalog panel. **A scheme row's `qbo_item_id` is recorded nowhere yet** — the mapping return is transient; ServiceItem creation (Task 11) carries the `qbo_id`. Auto-dismiss: when a commit leaves the area's diff empty, set the dismissal flag (call `QBOSuggestionService.suggestions(area)` post-commit; if `rows == []`, `QBOImportState.dismiss(area)`).

- [ ] TDD per service: creation, atomicity on invalid row, collapse-group behavior, auto-dismiss-on-empty, permission (`can_manage_config`). Commit.

### Task 11: Commit services — catalog & contacts

**Files:** `QBOImportCommitService.commit_catalog(rows)` / `commit_contacts(payload)`; endpoints; Tests `tests/test_qbo_import_commit_catalog.py`, `tests/test_qbo_import_commit_contacts.py`.

**Interfaces:** catalog inventory rows `[{qbo_id, code, description, selling_price, purchase_price, units ('none'), accounting_category (pk, required), action: 'create'|'update'}]` — create sets `qbo_id`; update = field overwrite on the `qbo_id`-matched InventoryItem. Service rows `[{qbo_id, name, description, rate_scheme (pk), action}]` — create → `ServiceItem(template_name=name, description=…, rate_scheme=…, qbo_id=qbo_id)`; **update with a price change** → `RateScheme` supersession via the existing supersede service (find it: `grep -n "supersede" apps/jobs/services.py apps/api/rate_schemes/`) creating the successor and repointing the ServiceItem — read the estimates-and-prices.md supersession section first and follow it exactly. Contacts payload `{customers: […], vendors: […], terms: […]}` — terms first (`PaymentTerms(name, days, qbo_id)`), then customers (CompanyName→`Business`+default `Contact`, else bare `Contact`; set `qbo_customer_id`, `Business.terms` by term qbo_id), then vendors (`Business` + `qbo_vendor_id`; same-name existing Business (case-insensitive `business_name` match) gets `qbo_vendor_id` set instead of a duplicate row — the merge). Updates overwrite mirrored fields only. All atomic per kind; permissions per Task 8's area map; auto-dismiss as Task 10.

- [ ] TDD: the matrix above, incl. supersession path (assert old scheme `replaced_by` set, ServiceItem repointed), merge behavior, `Business.terms` wiring. Commit.

### Task 12: Shared `SuggestionPanel.svelte`

**Files:** Create `frontend/src/components/qboimport/SuggestionPanel.svelte` + `frontend/src/lib/qboImport.js` (API wrappers: `pull(area)`, `suggestions(area)`, `commit(area, rows)`, `dismiss(area)`); Vitest `frontend/tests/components/qboimport/SuggestionPanel.test.js`.

**Interfaces — Produces:** props `{area, title, columns (render snippets per kind), onCommitted}`; behavior: on mount `suggestions(area)`; renders nothing when `dismissed` or `rows` empty; header shows fetched_at + Pull button (always callable) + Dismiss button; row checkboxes (checked default per state: `new`→kind default passed by wrapper, `imported`→checked+disabled, `changed`→checked, action label "update"); commit button posts checked rows then `onCommitted()` (wrappers refresh their own lists + `setupStatus.refresh()`). Error handling via `triageError` → `FormMessage` in-panel.

- [ ] TDD Vitest: render states (dismissed/empty/new/imported/changed), checkbox semantics, commit posts only checked, pull button calls `pull(area)` and re-fetches. Commit.

### Task 13: Categories + schemes panels (Settings)

**Files:** Modify `frontend/src/components/settings/AccountingCategories.svelte` (embed panel; columns: name/code inputs, taxable checkbox, member count, fallback-item select, expense-account select) and `frontend/src/components/RateSchemeManager.svelte` (embed; price-grouped rows, per-group algorithm/unit selects, collapse-group checkbox naming a shared scheme). Extend both components' Vitest specs.

- [ ] TDD: wrappers pass correct columns; category commit payload shape matches Task 10; scheme collapse UI produces `collapse_group` values; after commit the underlying lists refresh. Run Vitest → OK. Commit.

### Task 14: Catalog + contacts panels

**Files:** Modify `frontend/src/routes/catalog/CatalogServiceItemsPage.svelte` / the inventory tab page (embed catalog panel — two sections, service rows show resolved scheme, inventory rows show category select pre-filled per Task 9 resolution, blank-required otherwise; client-side filter box + select all/none) and the Contacts & Businesses page (embed contacts panel: three sub-tables customers/vendors/terms, merge_hint badge). Vitest for both.

- [ ] TDD as Task 13. Commit.

### Task 15: Wire `last_pull_at` + summary display + docs

**Files:** Panel header already shows fetched_at (Task 12); add the pull-summary line rendering (`summary` from pull response) in `SuggestionPanel`; Settings → Accounting QBO section gains the canonical Pull button + timestamp (Modify `frontend/src/components/settings/` QBO section component — find it: `grep -rln "qbo/status" frontend/src`). Update all affected design docs per spec's follow-on list + CLAUDE.md Configuration pointer. Vitest for the QBO-section button.

- [ ] Implement + Vitest → OK. Commit.

### Task 16: Final verification

- [ ] Full backend suite fresh → read summary → OK (schedule-module caveat as Task 6). Full Vitest → OK. E2E: run full suite (existing specs must stay green — the seeded DB gates all pass, sidebar renders normally); add `e2e/specs/setup-status.spec.js` asserting `GET /api/setup/status/` shape via API and that no sidebar entry is greyed on the seeded DB; note the exemption for fresh-tenant + pull flows (no QBO connection in e2e; covered by backend fixtures + Vitest + a manual dev-sandbox pull). Grep sweep: no `setup_complete` references (flagless), spec cross-check. Commit; report for RM review — no merge/push.

## Self-review notes

- Spec coverage: Part 1→T1, Part 2→T2, Part 3→T3/T4, PaymentTerms prerequisite→T5, Part 4→T7/T8, Part 5 rows/states/short-circuit→T9, commits incl. supersession & merge→T10/T11, panels→T12–14, summary/timestamp/docs→T15, testing section→per-task + T6/T16.
- Known judgment calls deferred to implementation, intentionally: SDK pagination kwargs (verify against installed python-quickbooks), the QBO taxable-field heuristic (dump a real item in the dev sandbox via `probe_invoice_link`-style inspection if unclear), exact settings-component filenames (grep as noted).
