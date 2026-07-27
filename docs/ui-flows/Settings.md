# Settings — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of the Settings page's
Accounting Categories manager, focused on the delete guard added in Task 17
(2026-07-26): unreferenced categories (mistakes/typos) can be hard-deleted;
referenced ones retire via the existing Active checkbox instead. Other
Settings tabs (Setup, Pricing, Schedule, Email, Business) are not covered
here yet — see the gap list in `README.md`.

## Personas

- **Config** (`configtime` — `can_manage_config`). Full CRUD on accounting
  categories, including delete.

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

## Coverage matrix

| Category state | Delete button | Confirm accept | Confirm cancel |
|---|---|---|---|
| Unreferenced | shown | 200, row removed | no-op |
| Referenced (any kind) | hidden | n/a (button absent) | n/a |
