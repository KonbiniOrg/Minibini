# PDF canvas editor — design + plan (v2 of the layout editor)

Status: built 2026-10-16 (see architecture-and-conventions.md §7.15). Changed while building: the page is A4, not Letter (the PDFs are A4 — WeasyPrint's default); the palette lives inside `PdfCanvas.svelte` (no separate `PdfBlockPalette`); the stylesheet is scoped server-side (`scope_css`); the list editor `PdfLayoutEditor` was removed. Builds on
`2026-10-16-pdf-layout-editor.md` (v1, built): same saved layout format,
same server validation; the list-style `PdfLayoutEditor` is replaced by an
on-page canvas.

## Goal

Arrange a document PDF by dragging blocks around a page-shaped canvas that
looks like the PDF, and edit them in place — "moving the blocks on the PDF
itself".

## Decisions

- **Snap-into-place, not free x/y.** Drops land in the existing
  rows → columns → blocks model, so pagination stays reliable and the
  layout format doesn't change.
- **Column widths snap** to the existing presets (⅓ / ½ / ⅔ combinations).
  Free percentages are a possible later change to the format.
- **The canvas is a browser rendering, not the PDF.** The real WeasyPrint
  render stays one click away as **Print view**.

## The canvas

- A Letter-sized white page (8.5 × 11 at the canvas scale) with the
  document's body margins, rendered with the same stylesheet as the PDF.
- Blocks render as they print: real logo and company text, the document's
  own text blocks, and the sample title / details / line items the preview
  already uses. The page footer sits in the bottom margin, editable there.
- Content longer than one page simply runs on (no page-break simulation in
  v2); Print view shows real pagination.

### Rendering the blocks

- Shared blocks (logo, company fields, text, divider, spacer) render
  client-side from the layout + company values, using the PDF classes.
- Document blocks (title, details, line items) come from a new
  `GET /api/settings/pdf-canvas/<kind>/` returning
  `{blocks: {title: html, details: html, line_items: html}, stylesheet: css}`
  — the real block partials rendered with the preview's sample data, plus
  the document's PDF CSS (head styles + `_branding_styles.html`). The
  canvas scopes that CSS under its page element. The HTML is our own
  template output from sample objects (no user markup beyond the sanitized
  rich text), rendered into the canvas with `{@html}`.

## Interaction

- **Palette** beside the page lists the block types (single-use ones greyed
  once placed; never Line items). Drag one onto the page to add it.
- **Drag a block on the page** to move it. While dragging, an indicator
  shows where it would land:
  - horizontal line between two blocks in a column → stack there;
  - vertical bar at a block's left / right edge → beside it: the row gains
    a column (up to three), split equally (½ + ½ or thirds);
  - line in the gap between rows → a new full-width row there.
  The line-item row only accepts above/below-row drops; nothing lands
  beside or inside it.
- **Column dividers** are drag handles snapping between the presets the
  row's column count allows (two columns: ⅓+⅔, ½+½, ⅔+⅓; three: thirds).
- **Click to select** a block: a floating toolbar above it with alignment,
  spacer height, arrow moves (the v1 keyboard-friendly path), and remove.
  Text blocks and the footer become editable in place with the existing
  rich-text toolbar. Company blocks say they edit the shared company
  details. Clicking empty page deselects; Delete/Backspace on a selected
  (non-editing) block removes it.
- An emptied column disappears (its row loses a column, re-split to the
  nearest preset); an emptied row disappears.
- Everything stays an unsaved draft until **Save <document>**; Reset to
  default and Copy layout from… stay.

## Code

- `lib/pdfLayout.js`: add drop operations — `insertBlockAt(layout, block,
  target)` / `dropBlock(layout, from, target)` with target kinds
  `{stack: row, cell, index}`, `{beside: row, cell, side}`,
  `{newRow: index}`; `setRowWidths(row, preset)`; empty-column / empty-row
  cleanup; preset choice by column count. All pure, Vitest-covered.
- `components/settings/PdfCanvas.svelte` (page, rows, columns, dividers,
  drop indicators), `PdfCanvasBlock.svelte` (one block: render, select,
  in-place edit), `PdfBlockPalette.svelte`. Pointer events (not HTML5 DnD)
  for the drag so the indicator can track the cursor precisely.
- `DocumentPdfSettings.svelte`: canvas replaces the list editor; preview
  pane becomes a **Canvas / Print view** toggle.
- Backend: `pdf_canvas_view` + `canvas_blocks(kind)` in `pdf_branding.py`
  (renders the three document-block partials with each `pdf.py`'s sample
  context — factor the sample contexts out of `preview_*_html`).

## Tests

- Vitest: drop/cleanup/width operations; canvas renders blocks in layout
  order and positions; selecting, toolbar actions, in-place text edit,
  palette add, divider snap (pointer events simulated).
- Backend: canvas endpoint (permission, kinds, sample HTML present,
  stylesheet), sample-context refactor keeps previews identical.
- E2E: drag a palette block beside the title, drag a divider, edit a text
  block in place, save, reload, Print view shows it.
- Docs: §7.15, Settings UI flow.
