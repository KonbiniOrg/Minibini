# Site-wide z-index audit

Addresses the LATER item **"Review site-wide z-index usage; decide whether to impose a scale."** The SPA has no documented z-index scale; stacking values have been chosen one-off (the catalyst was commit `270c79d`, which added an ad-hoc `z-index: 30` to `.job-header` plus `z-index: 1` on `.hold-reason-form` to lift the on-hold reason popover above the page body). This document enumerates every `z-index` in `frontend/src`, classifies each by UI layer, flags real ordering hazards, and proposes a small named scale the user can accept or adjust. It is a read-only audit — no source files were changed.

Scope note: all values live in Svelte component `<style>` blocks (which Svelte scopes per-component) or in `src/css/app.css`. There are **no** inline `style="z-index:..."` attributes and **no** `zIndex` (camelCase / JS-set) usages anywhere in `src`. Two `.css` files exist (`css/app.css`, `css/accordion.css`); only `app.css` is relevant and notably it sets `position: fixed` on the global error/success overlay with **no z-index at all**.

## All occurrences (sorted by numeric value)

| value | selector | file:line | layer it represents |
|---|---|---|---|
| 0 | `.bg-overlay` | routes/schedule/SchedulePage.svelte:349 | base content (schedule background hatch, behind lanes) |
| 1 | `.hold-reason-form` | components/jobs/JobHeader.svelte:246 | base content (local stacking inside the header's z:30 context) |
| 1 | `.lanes` | routes/schedule/SchedulePage.svelte:347 | base content (schedule lane stack) |
| 1 | `.unavailable-overlay` (`.bg-overlay` child) | routes/schedule/SchedulePage.svelte:362 | base content (schedule shading) |
| 2 | `.now-line` | components/schedule/NowLine.svelte:17 | sticky/marker within schedule (current-time line) |
| 2 | `.now-overlay` | routes/schedule/SchedulePage.svelte:348 | sticky/marker within schedule (now-line container) |
| 3 | `.drop-indicator` | components/schedule/WorkerLane.svelte:198 | drag affordance within schedule lane |
| 10 | `.add-worker-dropdown` | components/board/WorkerColumns.svelte:176 | dropdown (board add-worker menu) |
| 30 | `.job-header` | components/jobs/JobHeader.svelte:199 | sticky header (stacking context for the hold-reason popover) |
| 50 | `.dropdown` (CatalogPicker) | components/CatalogPicker.svelte:130 | dropdown / typeahead results |
| 100 | `.blep-band` | components/CurrentBlepBand.svelte:91 | sticky band (current blep, `position: sticky`) |
| 100 | `.suggestions` (TagEditor) | components/TagEditor.svelte:190 | dropdown / typeahead suggestions |
| 200 | `.overlay` (LineItemModal) | components/LineItemModal.svelte:174 | modal / overlay |
| 200 | `.overlay` (MaterialModal) | components/MaterialModal.svelte:252 | modal / overlay |
| 200 | `.overlay` (WorkItemForm) | components/WorkItemForm.svelte:354 | modal / overlay |
| 200 | `.overlay` (PlanMaterialModal) | components/PlanMaterialModal.svelte:253 | modal / overlay |
| 200 | `.overlay` (COLineItemModal) | components/changeorders/COLineItemModal.svelte:166 | modal / overlay |
| 200 | `.overlay` (TimeEditModal) | components/time/TimeEditModal.svelte:188 | modal / overlay |
| 300 | `.dropdown` (PriceListItemPicker) | components/PriceListItemPicker.svelte:146 | dropdown / typeahead results |
| 300 | `.overlay` (WorkerTimePromptModal) | components/board/WorkerTimePromptModal.svelte:63 | modal / overlay |
| 500 | `.error-overlay` (page-scoped) | routes/purchaseorders/PurchaseOrderDetailPage.svelte:451 | toast / notification (top error banner; PO page only) |
| 600 | `.dialog-overlay` (SendPODialog) | components/purchaseorders/SendPODialog.svelte:94 | modal / overlay |
| 999 | `.sidebar` | components/Sidebar.svelte:146 | app chrome (slide-in nav drawer) |
| 1000 | `.hamburger` | components/Sidebar.svelte:115 | app chrome (nav toggle button) |
| 1000 | `.task-popup` | components/board/TaskCard.svelte:183 | popover (board task hover/click card) |
| 1000 | `.chip-popup` | components/board/JobChipStrip.svelte:148 | popover (board job chip card) |
| 1000 | `.overlay` (TaskQuickCard) | components/schedule/TaskQuickCard.svelte:220 | popover (schedule task quick card) |
| 1000 | `.backdrop` (DeliverablesEditModal) | components/jobs/DeliverablesEditModal.svelte:163 | modal / overlay |
| 1000 | `.overlay` (MaterialSeverDialog) | components/purchaseorders/MaterialSeverDialog.svelte:66 | modal / overlay |
| 1000 | `.overlay` (PurchaseOrderDetail) | components/purchaseorders/PurchaseOrderDetail.svelte:369 | modal / overlay |
| 1100 | `.overlay` (AssignModal) | components/AssignModal.svelte:122 | modal / overlay (must clear z:1000 popovers) |
| 1100 | `.overlay` (ActualQtyModal) | components/tasks/ActualQtyModal.svelte:46 | modal / overlay |
| 1100 | `.overlay` (StartWorkConflictModal) | components/tasks/StartWorkConflictModal.svelte:61 | modal / overlay (must clear z:1000 popovers) |
| (none) | `.error-overlay`, `.success-overlay` | css/app.css:66 | **global toast/feedback — `position: fixed`, NO z-index** |

35 z-index declarations across 30 files, plus the un-z-indexed global overlay (the single most important finding).

## Conflicts / hazards

**1. The global error/success overlay has no z-index at all (`css/app.css:66`).** This is the api.js feedback mechanism used app-wide. Because it is `position: fixed` with no z-index, it stacks at the auto level (0) of its place in the DOM. It will be painted **behind almost every other layer here** — any modal (200–1100), any popover (1000), the sidebar (999), the blep band (100), even most dropdowns (50–300) — whenever those layers are positioned and have a higher z-index. A modal validation failure that triggers the global error overlay would render the red error box *behind* the open modal. This is the highest-priority defect: the user-facing feedback layer must be the topmost tier, and it currently has the weakest possible stacking value.

**2. Sidebar (999) vs. modals/popovers (1000–1100).** The slide-in nav drawer is z:999 and the hamburger is z:1000. Modals and popovers at 1000+ sit above the drawer, which is fine — but the hamburger button (1000) ties with board popups, the schedule TaskQuickCard, and several modal backdrops, all also 1000. If the nav drawer is open and a 1000 modal/popover opens, ordering between them is DOM-order-dependent (last-painted wins) rather than intentional. In practice the drawer and these popovers rarely co-occur, but the equal values make the result accidental rather than designed.

**3. The 1000 tier is overloaded and mixes two different layers.** Six selectors share z:1000: the hamburger (chrome), three popovers (`task-popup`, `chip-popup`, TaskQuickCard `.overlay`), and three true modals (DeliverablesEditModal, MaterialSeverDialog, PurchaseOrderDetail). Popovers and modals are conceptually different tiers but collide numerically. The only reason this works today is that the modals that must beat a popover were bumped to 1100 (see below). Any new modal copied from the 1000 set instead of the 1100 set would silently fail to cover a popover.

**4. 1100 tier exists *because of* hazard 3 — and the nesting is real.** `TaskQuickCard` (a `position: fixed; z:1000` popover on the schedule page) renders `AssignModal` (1100) and `StartWorkConflictModal` (1100) *inside* itself; `TaskDetailPage`/`JobTaskListPage` also open these. The 1100 values are deliberate so these modals clear the 1000 popovers. This is correct but undocumented — the 100-unit gap is load-bearing and easy to break.

**5. Two unrelated "modal" conventions at 200 vs 1000.** Line-item-style modals (LineItemModal, MaterialModal, WorkItemForm, PlanMaterialModal, COLineItemModal, TimeEditModal) all use 200, while another cluster of modals (DeliverablesEditModal, MaterialSeverDialog, PurchaseOrderDetail) uses 1000, and WorkerTimePromptModal uses 300. These are all the same conceptual layer (a centered dialog over a dimmed backdrop) yet span 200→1000. A 200-modal opened on a page that also shows the z:999 sidebar or a z:1000 popover would be **covered by them**. The 200-modals are typically opened from detail pages where no popover/sidebar overlaps, so this is latent rather than currently-broken, but it is fragile.

**6. PriceListItemPicker dropdown (300) ties the WorkerTimePromptModal (300) and sits above the 200-modals.** The PLI picker dropdown is z:300; the LineItem/Material/etc. modals that *contain* such pickers are z:200. Within a single modal this is harmless (child stacking inside the modal's own context), but the equal/inverted numbers are confusing and the dropdown's 300 exceeding the 200 modal backdrop is only safe because the dropdown lives inside the modal's DOM subtree.

**7. CatalogPicker dropdown (50) vs TagEditor suggestions (100) — same layer, different value.** Both are typeahead result lists; no functional conflict (they never co-occur), but inconsistent.

**8. `position` context matters.** Several values only work because of their stacking context. `.hold-reason-form` (z:1) is meaningful *only* inside `.job-header`'s z:30 stacking context; pulled out, the 1 would mean little. The schedule layers (0/1/2/3) are all scoped within `.lanes`/`.bg-overlay`/`.now-overlay` parents and form a self-contained local stack — they should **not** be flattened into the global scale; they are an internal sub-system and are fine as-is.

## Proposed scale

A small set of named tiers with generous gaps. Schedule-internal values (0–3) and the JobHeader/hold-reason local pair (30/1) stay as **local** stacking contexts and are intentionally excluded from the global ladder — only cross-page, cross-component layers need to agree.

| Tier | Value | Use |
|---|---|---|
| `--z-base` | 0 | default content; not usually set explicitly |
| `--z-sticky` | 100 | sticky headers/bands that scroll with content (blep band, sticky page header) |
| `--z-dropdown` | 200 | typeahead/autocomplete result lists, inline menus (CatalogPicker, PriceListItemPicker, TagEditor, board add-worker menu) |
| `--z-popover` | 400 | floating cards anchored to an element (board task/chip popups, schedule TaskQuickCard) |
| `--z-sidebar` | 600 | the slide-in nav drawer + hamburger (app chrome) |
| `--z-modal` | 800 | centered dialogs over a dimmed backdrop (all `.overlay` / `.backdrop` modals) |
| `--z-modal-nested` | 900 | a modal opened from within a popover/another modal (AssignModal, StartWorkConflictModal, ActualQtyModal) |
| `--z-toast` | 1000 | the global error/success feedback overlay + page-level error banners — always on top |

Rationale for ordering: feedback (`toast`) must beat everything, including modals, because errors can fire from inside an open modal. Modals beat the sidebar (you can dim/cover the nav while a dialog is up). The sidebar beats popovers and dropdowns (the drawer is full-height chrome). Popovers beat dropdowns (a popover may host a dropdown). Sticky bands sit just above base content. The `modal-nested` tier formalizes the existing 1000→1100 jump that today is undocumented but load-bearing.

### Mapping of existing usages onto the proposed scale

| Current | Where | → Tier (value) |
|---|---|---|
| `css/app.css` `.error-overlay`/`.success-overlay` (no z-index) | global feedback | **`--z-toast` (1000)** — fixes hazard 1 |
| `PurchaseOrderDetailPage` `.error-overlay` 500 | page error banner | `--z-toast` (1000) |
| `CurrentBlepBand` 100 | sticky band | `--z-sticky` (100) |
| `JobHeader` 30 (+ `.hold-reason-form` 1) | local stacking context | **leave as local**, unchanged |
| Schedule 0/1/2/3 (SchedulePage, NowLine, WorkerLane) | local schedule stack | **leave as local**, unchanged |
| `CatalogPicker` 50 | dropdown | `--z-dropdown` (200) |
| `TagEditor` 100 | dropdown | `--z-dropdown` (200) |
| `WorkerColumns` add-worker 10 | dropdown | `--z-dropdown` (200) |
| `PriceListItemPicker` 300 | dropdown | `--z-dropdown` (200) |
| `TaskCard` `.task-popup` 1000 | popover | `--z-popover` (400) |
| `JobChipStrip` `.chip-popup` 1000 | popover | `--z-popover` (400) |
| `TaskQuickCard` `.overlay` 1000 | popover | `--z-popover` (400) |
| `Sidebar` `.sidebar` 999 | chrome | `--z-sidebar` (600) |
| `Sidebar` `.hamburger` 1000 | chrome | `--z-sidebar` (600) |
| LineItemModal / MaterialModal / WorkItemForm / PlanMaterialModal / COLineItemModal / TimeEditModal — all 200 | modals | `--z-modal` (800) |
| WorkerTimePromptModal 300 | modal | `--z-modal` (800) |
| DeliverablesEditModal / MaterialSeverDialog / PurchaseOrderDetail / SendPODialog — 1000/600 | modals | `--z-modal` (800) |
| AssignModal 1100 | modal opened from popover/page | `--z-modal-nested` (900) |
| StartWorkConflictModal 1100 | modal opened from popover/page | `--z-modal-nested` (900) |
| ActualQtyModal 1100 | nested modal | `--z-modal-nested` (900) |

### Implementation note (for whenever this is acted on)

Define the tokens once as CSS custom properties on `:root` in `css/app.css`, then reference `var(--z-modal)` etc. in each component's `<style>`. Svelte scopes selectors but **not** custom properties, so `:root` vars are visible everywhere. The single highest-value change is giving the global `.error-overlay`/`.success-overlay` a `--z-toast` value so user feedback stops rendering behind modals.
