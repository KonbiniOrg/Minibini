# CSS review & reorg — findings and recommendations

**Date:** 2026-07-08
**Scope:** Svelte SPA styles (`frontend/src`). 187 components, 114 with
`<style>` blocks, one global sheet (`css/app.css`) shared by the app and the
customer portal.

## Frame

The style system serves three kinds of pages (the `.page-body` rollout
categories):

- **I. Fully individualized** — job board, job overview, schedule (+ login,
  packing-list print). Own their whole layout; use only the BASE layer.
- **II. Banner pages** — a full-bleed `JobHeader`/`CustomerHeader` with
  `.page-body` beneath: the est/inv/PO/CO detail and wizard pages, job task
  list, task detail, shipments, history, contact/business detail. This is
  where most future page-level work lands; the **task detail page is the
  reference implementation**.
- **III. Plain pages** — everything else, wrapped in `.page-body`: lists,
  forms, settings, home, catalog, search.

## Findings

1. **The global layer was healthy but thin.** Strong adoption where it
   existed (`.page-body` ×52 files, `.data-table` ×42, `.preserve-breaks`
   ×19, z-index tokens ×9), and almost no abuse (`:global(` appears 9 times,
   each defensible). But everything above the primitives lived as
   copy-paste.
2. **Category-II pages were the duplication epicenter.** The five
   est/inv/CO detail+wizard pages shared `.toolbar`, `.back-link`,
   `.page-title`, `.action-link` **byte-identically** (6/6/2/2 copies); the
   PO detail had the same toolbar-button rules under another name. Two
   size-families of "small white bordered button" existed in ~10 components
   with drifted borders/radii/padding.
3. **Same class name, different looks.** `.badge-invoiced` had three
   identical green-text copies plus a *fourth divergent* bordered-box look in
   JobDetail — one name, two visuals. `.home-tabs` was defined in both Home
   and UserListPage (copy signal).
4. **JobDetail (Category I) is the single largest style surface** — a
   454-line block (3× the next largest) with a private `.pill-*` status
   palette (~20 variants) parallel to the consolidated global one, three
   internally-identical in-content tab bars, and its own table headers.
5. **Known but unresolved:** the `.panel` chrome duplication
   (JobDetail ↔ DeliverablesSection) the README §5.5 gotcha documents; four
   copies of the page-tab idiom; no form-layout vocabulary at all; ~5
   different greys standing in for "muted text".

## What was done (this pass)

- **`app.css` reorganized into three labeled sections** — BASE / SHARED /
  PAGE KINDS (II. banner-page kit, III. plain-page kit) — with the rules of
  the road in the header comment: promote instead of copy; local overrides
  may resize, never recolor. Border tokens added (`--border-control`,
  `--border-subtle`).
- **Every rule that existed as 2+ copies was promoted** and the local copies
  deleted: `.toolbar` (+buttons), `.back-link`, `.page-title`,
  `.action-link`, `.edit-link` (dark-banner links), `.panel` family,
  `.badge-invoiced`, `.row-actions button` (row edit/del buttons),
  `.page-tabs` (Home/Users/Settings/Catalog markup switched to it).
- **Deliberate unifications (small visual changes):** PO detail's action row
  adopts `.toolbar` (12px margin → 8px padding); JobDetail's divergent
  `.badge-invoiced` adopts the green text-link style; shipment matrix row
  buttons adopt the bordered `.row-actions` look; DeliverablesSection's
  blue "Edit" link renamed `.panel-link` (was shadowing `.edit-link`).
- Docs updated (`frontend/README.md` §CSS, architecture doc §5.5a); five
  deferred items logged in `docs/designs/LATER.md`.

## Recommendations for the coming page passes

1. **Work Category II first, page by page** — the banner-page kit (toolbar,
   action-band, stat-chips, panel, badge/pill vocabulary) is now complete
   enough that each pass should mostly *delete* local styles. Treat the task
   detail page as the exemplar: crumbs → title+pill → chips → action band →
   sections.
2. **Category I pages get their own bespoke passes** — job overview first
   (its 454-line block, `.pill-*` palette, and in-content tabs are the big
   incoherence reservoir), then board, then schedule. Don't force the shared
   kit on them; do fold their status colors into the global palette.
3. **Before many Category-III form pages get touched, define the form kit**
   (LATER item) — it's the one vocabulary that doesn't exist at all.
4. **Add text-grey tokens next to the border tokens** and adopt them
   opportunistically; don't do a big-bang hex hunt.
5. **Keep the promote-don't-copy rule enforced in review** — the drift this
   pass cleaned up (two button families, two badge looks, five mutes) all
   started as one innocent copy.
