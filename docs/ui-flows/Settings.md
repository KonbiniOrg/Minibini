# Settings — UI flow

**Purpose:** A from-the-user's-perspective walkthrough of the Settings page's
Accounting Categories manager, focused on the delete guard added in Task 17
(2026-07-26): unreferenced categories (mistakes/typos) can be hard-deleted;
referenced ones retire via the existing Active checkbox instead. Other
Settings tabs (Setup, Pricing, Schedule, Email, Business) are not covered
here yet — see the gap list in `README.md`. §2 covers the Documents tab
(document-PDF branding, 2026-10-02).

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

## 2. Documents — PDF branding

Entry: Settings → Documents tab. Persona: **Config**. Applies to the
estimate, change order, and purchase order PDFs (invoices use QBO's PDF).

- [ ] **Letterhead saves as a group.** Fill Company name / Address / Phone /
  Email, pick a Logo position (Left / Center / Right), click **Save
  letterhead** → `saved` flashes; values persist across a reload.
- [ ] **Bad logo is rejected under the file input.** Choosing a non-image (or
  a non-PNG/JPEG, or a file over 1 MB) and clicking **Upload logo** shows the
  reason under the input; no logo is stored.
- [ ] **Logo upload shows the logo.** A PNG/JPEG uploads on **Upload logo**
  and appears as the current logo; it persists across a reload.
- [ ] **Remove logo.** **Remove logo** (no confirm — re-uploading undoes it)
  returns the block to "No logo uploaded."
- [ ] **Per-document text saves as a group.** Each of Estimate / Change Order
  / Purchase Order has four boxes (Below the header, Above the line items,
  Below the totals, Page footer) and its own **Save … text** button; a save
  on one document leaves the others untouched.
- [ ] **Preview opens a sample PDF.** **Preview … PDF** opens
  `/api/settings/pdf-preview/?document=<kind>` in a new tab — a sample
  document showing the *saved* letterhead and text.
- [ ] **Config-gated.** A user without `can_manage_config` gets 403 from the
  logo and preview endpoints.
- [ ] **Sent documents carry the branding (not e2e-driven — needs SMTP + PDF
  text extraction).** Covered at the backend level by
  `tests.test_pdf_branding`.

## Coverage matrix

| Category state | Delete button | Confirm accept | Confirm cancel |
|---|---|---|---|
| Unreferenced | shown | 200, row removed | no-op |
| Referenced (any kind) | hidden | n/a (button absent) | n/a |
