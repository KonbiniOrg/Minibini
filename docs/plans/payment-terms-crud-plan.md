# PaymentTerms CRUD — implementation plan

**Goal:** a small payment-terms manager on Settings → Business, replacing
the read-only-plus-import status quo. Resolves the LATER entry
"PaymentTerms has no management UI" (2026-07-23).

**Decisions (RM, 2026-07-23):**
- Lives on the **Settings → Business tab** (not Contacts, not Accounting —
  "it's not really accounting or pricing, and Business isn't full anyway").
- Writes gated by `can_manage_config` (the Settings surface's atom).
  Reads stay `IsAuthenticated` (BusinessForm's assignment select).
- **QBO-mirrored rows (`qbo_id` set) stay editable**, shown with a QBO
  badge; the next contacts pull flags local edits "changed" and the import
  panel arbitrates. Deleting a mirrored term is allowed — it re-appears as
  "new" after the next pull (self-healing).
- Deleting a term clears it from businesses (`Business.terms` is
  SET_NULL) → **two-phase confirm delete** with an impact count.
- **Terms get their own QBO import panel** on the same Settings → Business
  surface (RM: the grey terms table inside the Contacts panel was
  confusing). New import area `terms` with its own pull button and its
  own sticky dismissal flag; the Contacts panel drops its terms section
  entirely. Same shared `SuggestionPanel.svelte` shell as every other
  area — a thin wrapper only.

## Task 1 — backend (TDD): promote the viewset

Files: `apps/api/contacts/views.py` (PaymentTermsViewSet),
`apps/api/contacts/serializers.py` (PaymentTermsSerializer),
`tests/test_payment_terms_crud.py` (new).

- `PaymentTermsViewSet`: `ReadOnlyModelViewSet` → `ConfirmDeleteMixin +
  ModelViewSet` (follow ContactViewSet's shape). `get_permissions()`:
  list/retrieve `IsAuthenticated`, else `IsAuthenticated + CanManageConfig`.
  Stable ordering (`name`). DELETE returns 200 + JSON body per contract;
  first DELETE returns impact (`used by N businesses — their terms will
  be cleared`), second with `?confirm=true` executes.
- Serializer: `name` required + case-insensitively unique
  (`{'name': ['…']}` contract 400s — the model itself stays permissive
  for QBO-import merges); `days` optional; expose `qbo_id` (read-only)
  and an annotated `business_count`.
- Tests: create (name required, dupe name rejected, days optional),
  update, both delete phases incl. SET_NULL effect on a business,
  permission matrix (read open / write 403 without config atom).
- **Do not run the suite while another Django test run is alive.**

## Task 2 — frontend manager + Vitest

Files: `frontend/src/components/settings/PaymentTermsManager.svelte`
(new), embedded at the bottom of
`frontend/src/components/settings/BusinessSettings.svelte`;
`frontend/tests/components/settings/PaymentTermsManager.test.js` (new).

- A flat list only — no individual term view page. Table: Name | Days |
  QBO badge | In use (business_count) | Edit/Delete.
- Create and edit happen in a **modal** (`Modal.svelte`, the app's general
  edit pattern — RM 2026-07-23) with explicit Save/Cancel (never
  blur-commit).
- Delete: first DELETE fetches impact → `confirm()` with the count
  (irreversible → confirmation appropriate) → `?confirm=true`.
- Errors via `triageError`: `FieldError` under the name/days inputs,
  `FormMessage` for the rest (RateSchemeManager is the exemplar).
- Vitest: renders rows + badge, add validates empty name, dupe-name 400
  renders under the input, two-phase delete posts confirm.

## Task 3 — terms import area split (TDD)

Files: `apps/qbo/import_services.py`, `apps/api/qbo_import/views.py`,
`frontend/src/components/qboimport/TermsImportPanel.svelte` (new),
`frontend/src/components/qboimport/ContactsImportPanel.svelte` (remove
terms section), tests in `tests/test_qbo_import_*` + a Vitest file.

- Backend: add `terms` to `QBOImportState.AREAS`;
  `AREA_PERMS['terms'] = 'core.can_manage_config'` (its Settings home).
  `_terms(snapshot)` suggestion rows split out of `_contacts` (which
  stops emitting `kind == 'term'` rows); `POST
  /api/qbo/import/commit/terms/` extracts the terms portion of
  `commit_contacts` (which keeps accepting a `terms` list for
  API-compat but the SPA no longer sends one); `_auto_dismiss('terms')`
  after the terms commit.
- **Customer→term wiring dependency:** customers resolve `term_qbo_id`
  against existing PaymentTerms rows. With terms in their own panel,
  the Contacts panel gains an amber dependency note ("customers with
  payment terms: import terms on Settings → Business first — otherwise
  they're created without terms") shown when snapshot customers
  reference term ids with no matching konbini row.
- Frontend: `TermsImportPanel` wrapper (columns: Name | Days | state),
  embedded on Settings → Business with its own
  `QboPullButton area="terms"` + `{#key pullEpoch}` remount, above the
  manager; committing refreshes the manager list.
- Tests: area registration/permission, `_terms` rows + states (new /
  imported via `qbo_id`, changed on days/name drift), terms commit +
  auto-dismiss, contacts rows no longer include terms, the dependency
  note logic; Vitest for the wrapper and the ContactsImportPanel
  section removal.

## Task 4 — e2e

File: `e2e/specs/settings/payment-terms.spec.js` (new). Config-atom
persona: create "Net 45"/45 on Settings → Business, see it listed, rename
it, verify it appears in a business form's terms select, delete it
(accept the confirm), verify gone.

## Task 5 — docs

- `docs/designs/contacts-and-businesses.md`: PaymentTerms section gains
  the manager (surface, permissions, delete semantics, QBO-badge policy).
- `docs/designs/quickbooks-integration.md`: import area list gains
  `terms` (six areas); contacts commit note updated.
- `docs/designs/users-and-permissions.md`: endpoint table rows.
- `docs/designs/LATER.md`: remove the resolved entry.
- Delete this plan file when shipped.
