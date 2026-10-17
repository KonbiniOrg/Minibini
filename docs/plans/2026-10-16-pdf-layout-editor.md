# PDF layout editor — design + plan (v1)

Status: v1 built 2026-10-16 (see architecture-and-conventions.md §7.15). Changed from the plan while building: full-width rows flow (split across pages) and only column rows are kept-together tables; "Reset to default" is an unsaved draft (GET returns the default), so there is no DELETE endpoint; the migration stores nothing when no branding is set.

## Goal

Let a config user arrange each document PDF (estimate, change order, purchase
order) themselves — top to bottom *and* side by side — in Settings → Documents,
with the existing WeasyPrint preview showing the real result as they edit.

## Decisions

- **Rows of columns, not free positioning.** A layout is a list of rows; each
  row has a column preset; each cell holds a vertical stack of blocks.
  Absolute x/y placement is out: it fights WeasyPrint's flow layout once the
  line table grows across pages.
- **Fully independent layout per document kind.** Estimate, change order and
  PO each have their own layout; editing one never touches another. A
  "Copy layout from…" action seeds one from another, unlinked afterwards.
- **Shared company data, per-document placement.** Logo image, company name,
  address, phone, email stay single shared values (today's keys). Layouts
  place them with shared blocks; anything document-specific (e.g. a
  purchasing phone on POs only) goes in a free text block.
- **v1 = layout + blocks only.** The line table (and its total rows) is one
  fixed block. Column choice/labels/widths, separable totals, fonts, colours
  and margins are follow-ups.
- **Users never write HTML.** Text blocks are the existing rich-text subset,
  sanitized on save and on render (`apps/core/rich_text.py`), as today.

## Layout schema

Stored as canonical JSON in Configuration key `<kind>_pdf_layout`
(`estimate_pdf_layout`, `change_order_pdf_layout`, `po_pdf_layout`).

```json
{
  "version": 1,
  "rows": [
    {"columns": "1/2-1/2",
     "cells": [
       [{"type": "logo", "align": "left"}],
       [{"type": "company_name", "align": "right"},
        {"type": "company_address", "align": "right"}]
     ]},
    {"columns": "full", "cells": [[{"type": "title", "align": "left"}]]},
    {"columns": "full", "cells": [[{"type": "line_items"}]]},
    {"columns": "full", "cells": [[{"type": "text", "align": "left", "html": "<p>Terms…</p>"}]]}
  ]
}
```

Column presets: `full`, `1/2-1/2`, `1/3-2/3`, `2/3-1/3`, `1/3-1/3-1/3`.

### Block catalog

| Type | Kinds | Settings | Renders |
|---|---|---|---|
| `logo` | all | align | shared `pdf_logo` (nothing if unset) |
| `company_name` / `company_address` / `company_phone` / `company_email` | all | align | the shared `pdf_company_*` rich text |
| `text` | all | align, html | rich text with `{placeholder}` substitution |
| `divider` | all | — | horizontal rule |
| `spacer` | all | size (`small`/`medium`/`large`) | vertical gap |
| `title` | all | align | "Estimate" / "Change Order" / "Purchase Order" + number |
| `details` | all | align | today's `header-info` block for that kind (customer/vendor, attn, job, dates) |
| `line_items` | all | — | today's table(s) incl. total rows; for CO also the intro line and deliverables table |

### Validation (`validate_layout(kind, data)` → normalized layout or `ValidationError`)

- `version == 1`; `rows` a non-empty list, ≤ 40 rows; ≤ 20 blocks per cell.
- Each row's `columns` is a known preset and `len(cells)` matches it.
- Every block `type` is in the catalog; unknown keys on a block are rejected;
  `align` ∈ left/center/right (default left); spacer `size` from its list.
- `line_items` appears **exactly once**, alone, in a `full` row (the table
  must stay in normal flow so it paginates).
- `title` and `details` at most once each.
- `text.html` passes `sanitize_rich_text`; length-capped.

## Backend

- **New module `apps/core/pdf_layout.py`**: block catalog, presets,
  `default_layout(kind)`, `validate_layout(kind, data)`, `get_layout(kind)`
  (stored row, else default), and `resolve_layout(kind, layout, values)` →
  render-ready rows (rich text rendered with placeholder values, each block
  carrying its template name).
- **`pdf_branding_context`** gains the resolved layout; the four-slot `text`
  dict and `logo_position` go away. `page_footer` stays a per-document
  setting (`<kind>_pdf_text_page_footer`) — it lives in the `@page` margin
  box, not the body flow.
- **Templates**: each document template keeps its `<head>`/styles and its
  page-footer include; the body becomes `{% include 'pdf/_layout.html' %}`.
  `_layout.html` renders each multi-column row as a fixed-width
  `<table class="layout-row">` with a `<colgroup>` (WeasyPrint's most
  reliable layout path) and `break-inside: avoid`; the `line_items` row
  renders as a plain full-width div so its table splits across pages.
  Shared block partials in `templates/pdf/blocks/`; kind-specific ones
  (`title`, `details`, `line_items`) beside each document template, carved
  out of the current markup unchanged.
- **API**:
  - `GET/PUT /api/settings/pdf-layout/<kind>/` (`CanManageConfig`) — GET
    returns the effective layout (stored or default) plus the block catalog
    for that kind; PUT validates, normalizes and stores, returns it.
  - `DELETE` on the same URL resets to default (200 + message).
  - `POST /api/settings/pdf-preview/` accepts an optional draft `layout`
    alongside `values`; validated the same way, never stored. The
    `letterhead` preview kind is retired.
- **Data migration**: for each kind, build a stored layout equivalent to
  today's output — letterhead row from `pdf_logo_position` (left →
  `1/2-1/2` logo | company blocks right-aligned; right → mirrored; center →
  `full` row, centered), then title, the old `below_header` text (if any),
  details, `above_lines` text, line items, `below_totals` text. Then delete
  `pdf_logo_position` and the three body-slot keys per kind. Reverse
  migration restores the slot keys from the first text block in each
  position where possible (best effort, documented).

## Frontend (`DocumentPdfSettings.svelte` reorganized)

- **Company details** section (shared): logo upload + the four company
  fields, one Save — as today, minus logo position.
- **One tab per document**: layout editor on the left, live preview on the
  right (existing debounce/sequence logic, now sending the draft layout),
  page-footer editor beneath, explicit **Save layout** button, **Reset to
  default**, **Copy layout from…**.
- **`PdfLayoutEditor.svelte`**: rows stacked vertically, cells side by side
  at their proportions, blocks as cards. Add row (choose preset), change a
  row's preset (blocks from dropped cells move into the last kept cell),
  move row up/down, delete row; add block (palette filtered to the kind's
  catalog, single-use blocks greyed when placed), move block up/down within
  a cell and left/right between cells, native HTML5 drag between cells as a
  convenience, delete block. No confirmations — all reversible until Save.
  `line_items` row is locked to `full` and can't be deleted.
- **`PdfBlockSettings.svelte`**: the selected block's settings — align,
  spacer size, and `RichTextEditor` for text blocks.

## Tests (TDD, per CLAUDE.md)

- `tests/test_pdf_layout.py`: validator (each rule, both directions),
  default layouts, resolve/render (blocks land in the right cells, line
  table outside a layout table, text sanitized + placeholders substituted),
  generated PDFs for all three kinds with default and custom layouts.
- API tests: GET/PUT/DELETE layout endpoint, permissions, preview with draft
  layout, rejected drafts.
- Migration test: old slot keys + each logo position → equivalent layout.
- Update `tests/test_pdf_branding.py` for removed slots/logo position.
- Vitest: `PdfLayoutEditor` (add/move/delete rows and blocks, preset change,
  locked line-items row) and the reorganized settings component.
- E2E: update `e2e/specs/settings/document-pdfs.spec.js` — build a two-column
  row, add a text block, save, reload, preview reflects it.

## Docs to update when shipped

`docs/designs/architecture-and-conventions.md` §7.15 (PDF branding),
`docs/designs/data-constraints.md` §1.1 (config keys), `docs/ui-flows/Settings.md`,
`frontend/README.md` if new conventions, CLAUDE.md's PDF Templates paragraph.

## Out of scope (follow-ups)

Line-table column selection/labels/widths; totals as a separate block;
fonts, colours, page size/margins; per-row spacing/borders; free
positioning.
