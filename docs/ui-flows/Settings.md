# Settings — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of the Settings page's
Accounting Categories manager, focused on the delete guard added in Task 17
(2026-07-26): unreferenced categories (mistakes/typos) can be hard-deleted;
referenced ones retire via the existing Active checkbox instead — plus the
**QBO Log** tab (2026-10-17), a read-only view of every push Minibini has
sent to QuickBooks. Other Settings tabs (Setup, Pricing, Schedule, Email,
Business) are not covered here yet — see the gap list in `README.md`.

## Personas

- **Config** (`configtime` — `can_manage_config`). Full CRUD on accounting
  categories, including delete.
- **Financials** (`finjobs` — `can_manage_financials`). Cannot reach the
  Settings page from the sidebar, but may read the sync-log API (§2).
- **Worker** (`worker` — no atoms). Refused the sync-log API (§2 guard).

## 1. Accounting Categories — delete guard

Entry: Settings → Accounting tab (`#/settings`, default tab).

- [ ] **Unreferenced category shows Delete.** A category with no materials,
  services, rate schemes, or line-item references (including as an
  adjustment target) shows a **Delete** button next to **Edit** in its row.
- [ ] **Referenced category has no Delete.** A category referenced anywhere
  (e.g. the seeded "Service" category, used by rate schemes/estimate/invoice
  lines) shows only **Edit** — no Delete button, whether or not the row is
  currently being edited.
- [ ] **Confirm names the category.** Clicking Delete opens a browser confirm
  reading `Delete category "{name}"? This cannot be undone.`
- [ ] **Cancel is a no-op.** Dismissing the confirm makes no API call; the row
  is unchanged.
- [ ] **Accept deletes.** Accepting calls `DELETE
  /api/accounting-categories/{id}/`, shows `Deleted "{name}"`, and the row
  disappears from the list.
- [ ] **Race guard (not e2e-driven — needs a second concurrent actor).** If the
  category becomes referenced between page load and the delete click (another
  tab/user), the DELETE 409s and the row's error line reads the "in use"
  message — the server checks `is_referenced()` too, mirroring the freeze
  guard; button visibility alone isn't the enforcement. Covered at the
  backend level by `tests.test_config_service_crud`.

## 2. QBO Log — read-only sync history

Entry: Settings → **QBO Log** tab (`#/settings`). Backed by `GET
/api/qbo/sync-log/` (paginated, 25/page, `can_manage_financials` **or**
`can_manage_config`). The seed carries three `qbo.qbosynclog` rows: a
cron-style customer reactivate (no user), a superuser invoice create, and a
failed expense create (`QuickBooks is not connected.`) by the financials user.
"Previously synced, now disconnected" is a reachable state, so these rows
need no live QBO.

- [ ] **Tab shows one row per log entry.** Each seeded row renders as
  `{entity_type} #{entity_id}` with its action, a status pill (`success` /
  `failed`), and — in full density — the QBO entity + id and who triggered it
  (`—` for cron rows). Lite density hides the QBO and By columns.
- [ ] **Newest first.** The most recent `synced_at` is the top row.
- [ ] **Failed row carries its error text.** The `failed` pill is red and the
  Error column shows the stored `error_message`.
- [ ] **Status filter.** Choosing **Failed** refetches with `status=failed`
  and leaves only failed rows; **All** restores everything. Changing a filter
  resets to page 1.
- [ ] **Entity filter.** Choosing an entity type refetches with
  `entity_type=…`. Historical types (vendor, bill, bill payment) stay
  selectable so old rows remain traceable.
- [ ] **Pager (not e2e-driven — seed has 3 rows).** Past 25 rows the shared
  Pager appears with Previous/Next and an `N–M of total` label.
- [ ] **Guard: no atom → 403.** A worker with no atoms gets 403 from the
  sync-log API. A financials-only user is allowed (same reader set as the
  Accounting tab's sync-failures panel plus config admins).
- [ ] **Read-only.** There are no retry/edit/delete controls here; retries
  live in the Accounting tab's **QBO Sync Failures** panel.

## Coverage matrix

| Category state | Delete button | Confirm accept | Confirm cancel |
|---|---|---|---|
| Unreferenced | shown | 200, row removed | no-op |
| Referenced (any kind) | hidden | n/a (button absent) | n/a |

| Sync-log reader | API | Tab reachable |
|---|---|---|
| Config (`configtime`) | 200 | yes (sidebar → Settings) |
| Financials only (`finjobs`) | 200 | no sidebar link (Settings is config-gated) |
| Worker (no atoms) | 403 | no |
