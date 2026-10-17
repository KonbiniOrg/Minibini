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

- [ ] **Company details save as a group.** Fill Company name / Address /
  Phone / Email, click **Save company details** → `saved` flashes; values
  persist across a reload. They are shared by all three documents.
- [ ] **Bad logo is rejected under the file input.** Choosing a non-image (or
  a non-PNG/JPEG, or a file over 1 MB) and clicking **Upload logo** shows the
  reason under the input; no logo is stored.
- [ ] **Logo upload shows the logo.** A PNG/JPEG uploads on **Upload logo**
  and appears as the current logo; it persists across a reload.
- [ ] **Remove logo.** **Remove logo** (no confirm — re-uploading undoes it)
  returns the block to "No logo uploaded."
- [ ] **Rich text in the company fields, text blocks and footers.** Each box
  has a toolbar — **B**, *I*, U, S (also Ctrl/Cmd+B/I/U), subscript /
  superscript, Text size (Small / Normal / Large / Extra large), Font
  (Default / Sans serif / Serif / Monospace), text colour, highlight,
  alignment (left / center / right / justify), lists, Clear formatting,
  Undo / Redo — applying to the selection. No link or HTML tools.
  Company name, Phone and Email stay one line (Enter does nothing, no list
  buttons); Address, text blocks and the page footer take several lines and
  also have **Bulleted list** / **Numbered list** buttons (typing `- ` or
  `1. ` at a line start begins one; Tab / Shift-Tab nest and un-nest an
  item). Pasting from Word / email keeps bold, italic, underline and lists
  and drops other formatting. Formatting persists across a save + reload
  and shows in the live preview.
- [ ] **Image library.** The Images box lists uploaded images (thumbnail +
  name + Remove, no confirm). **Add an image** uploads a PNG / JPEG ≤ 1 MB;
  a bad file shows its reason under the input. Removing an image takes it
  off every document that placed it.
- [ ] **One tab per document, each drawn as its page.** Document layouts
  has Estimate / Change Order / Purchase Order tabs. Each shows an A4 page
  with the document's blocks as they print — the company details (live,
  including unsaved edits), text, and a sample title / details / line
  items. Blank company fields, a missing logo and empty text show grey
  placeholders that don't print. A tab with unsaved changes is marked `*`.
- [ ] **Drag to arrange.** Dragging a block (or a palette entry from the
  Blocks list beside the page) shows a blue indicator: a line between
  blocks stacks it there; a bar at a column's left / right edge puts it
  beside, adding a column (up to three, split evenly); a line between rows
  (or at a row's top / bottom edge) makes a new row. Releasing drops it.
  A column or row left empty disappears. Nothing can go into the
  line-item row; the line items themselves move only as a whole row.
  Clicking a palette entry adds it as a new row at the end.
- [ ] **Select to edit.** Clicking a block outlines it and shows a toolbar:
  block alignment (L / C / R), spacer options, image choice / Upload… /
  size, column gap, ↑ ↓ ← → moves, × remove (also
  Delete / Backspace; the line items can't be removed).
- [ ] **One click to type, any text.** One click on a Text block, a company
  field (name / address / phone / email) or the title opens it for
  editing with the caret where you clicked — typing goes straight in.
  A company field is the shared value: the Company details form follows,
  and every document shows the change. The title's text replaces the
  document's name (blank = Estimate / Change Order / Purchase Order). The
  page footer in the bottom margin works the same way. Escape or clicking empty page
  deselects. Company blocks say they're edited under Company details.
- [ ] **Dividers go on borders.** **Divider** in the Blocks list is not a
  block: dragging it onto the page shows the line where it would land —
  between two stacked blocks, under a row (across the page), or on the
  boundary between two columns (a vertical line the row's full height) —
  and dropping it draws the line there. No indicator at the top of the
  page or a page edge. Clicking Divider instead lines the bottom of the
  last row. Clicking a line selects it (Line tools with ×, or Delete);
  dragging it moves it to another border. A line under a block moves
  with the block.
- [ ] **Spacers: gap or indent.** A selected Spacer switches between
  **Gap** (vertical space) and **Indent** (pushes its whole column in from
  the Left / Right by Small / Medium / Large — shown as a small "Indent"
  marker). Print view shows the same.
- [ ] **Column gap.** Selecting any block in a row with columns offers
  **Column gap** Small / Medium / Large; the page re-spaces the columns.
- [ ] **Column widths snap.** A two-column row has a small grip above its
  column boundary; dragging it (or ← / → when focused) snaps between
  ⅓ + ⅔, ½ + ½ and ⅔ + ⅓.
- [ ] **Reset to default / Copy layout from….** Reset loads the built-in
  layout; Copy loads another document's current layout. Both are unsaved
  drafts — the documents stay independent; changing one after a copy
  leaves the other alone.
- [ ] **Save is at the top.** **Save <document>** sits in the bar at the top
  of Document layouts, which stays in view while the page scrolls. It
  stores that document's layout and page footer — and the company
  details, when they were edited (on the page or above) → `saved` shows
  for a few seconds; everything persists across a reload; the other
  documents' layouts are untouched. Any later edit shows "unsaved
  changes" again. A layout the server
  rejects shows its reasons under the button.
- [ ] **Print view.** **Print view** swaps the page for the real PDF of a
  sample document, rendered with the unsaved edits after a short pause;
  **Edit page** goes back. Switching tabs renders that document. Clicking
  the pages opens the full-size PDF in a new tab. Nothing is saved.
- [ ] **Config-gated.** A user without `can_manage_config` gets 403 from the
  logo, layout, canvas and preview endpoints.
- [ ] **Sent documents carry the layout (not e2e-driven — needs SMTP + PDF
  text extraction).** Covered at the backend level by
  `tests.test_pdf_branding` and `tests.test_pdf_layout`.

## Coverage matrix

| Category state | Delete button | Confirm accept | Confirm cancel |
|---|---|---|---|
| Unreferenced | shown | 200, row removed | no-op |
| Referenced (any kind) | hidden | n/a (button absent) | n/a |
