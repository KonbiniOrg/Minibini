# View mode seams: lite / full density and desktop / phone layout

Status: DESIGN DRAFT — discussed RM ↔ Claude 2026-10-08. Not yet planned or
implemented. §7 (lite-view inventory) is RM's to fill before this becomes a
plan; the mechanism in §3–§5 is agreed in principle and should be re-checked
against that inventory.

Related durable doc: `docs/designs/architecture-and-conventions.md` §6 (View
mode) and §10 ("Lite-mode rollout" in Unfinished work). Those sections get
rewritten when this ships.

## 1. Problem

The SPA has a `full` / `lite` view-mode toggle, but the only visible
difference today is a background colour. The intent is for lite to show
materially less: fewer table columns, fewer links, shorter labels, fewer rows
(closed items hidden), fewer sections. Separately, the app should eventually
work on a phone, which needs layout changes (stacked instead of tabular,
drawer nav instead of sidebar) on top of CSS.

Two obvious implementations were considered and rejected:

- **Parallel page trees** (one set of routes/components per mode). Two of
  everything to write, test (Vitest + e2e), and keep in sync; drift is
  guaranteed, and a phone layout would make it three.
- **`{#if $viewMode === 'lite'}` sprinkled through templates.** Every page
  learns about mode, `<th>`/`<td>` pairs get wrapped individually, and the
  template becomes unreadable the moment layout joins density as a second
  condition.

Both treat "mode" as something every page must know. The design below pushes
the branching into a small number of *seams* so pages describe **what** they
show and the seams decide **how much** and **in what shape**.

## 2. Current state (2026-10-08)

- `frontend/src/stores/viewMode.js`: writable `'full' | 'lite'`, default
  `'lite'`, persisted to `localStorage` key `minibini_view_mode`.
  `main.js` mirrors it to `document.body.dataset.viewMode`; `css/app.css` has
  one rule (`body[data-view-mode="full"]` background).
- `components/FullOnly.svelte`: renders children only in full mode. Two
  consumers (`contacts/ContactDetail.svelte`, `contacts/BusinessDetail.svelte`).
- Direct `$viewMode` reads: `HistoryPanel.svelte` (filters entries in lite),
  `ContactDetail.svelte` (hides closed jobs / invoices / POs in lite, varies
  empty-state copy), `Sidebar.svelte` (toggle + a full-only block),
  `home/ProfilePanel.svelte` (toggle), `home/HelpPanel.svelte`,
  `settings/EmailTemplates.svelte`.
- Toggle lives in two places: bottom of the sidebar (`LITE | FULL`) and the
  profile panel.
- **No responsive CSS** anywhere (one `@media print` in
  `PackingListPrint.svelte`). No `matchMedia` use.
- **Tables are hand-written per component** — roughly 70 files contain a
  `<table>`. Each declares its own `<thead>`/`<tbody>`. There is no shared
  generic table; `LineItemTable.svelte` is the closest (props + an `actions`
  snippet) but is specific to line items. Svelte 5 snippets are already an
  established pattern (~20 components use `{#snippet}` / `{@render}`).
- Routes are thin wiring (100–600 lines); components carry the content. This
  is what makes a seam-based approach cheap: the branching lands in
  components and shared primitives, not routes.

## 3. Two axes, not three modes

**Density** (`lite` / `full`) is a *user preference*: how much of the data a
person wants in front of them. RM expects most shop-floor workers to stay in
lite, but the toggle is about working style, not role — some people want
everything, some want only what the task at hand needs. It is not a
permission mechanism and must never be the thing that hides data a user
isn't allowed to see (permissions do that).

**Layout** (`desktop` / `phone`) is a *device fact*: is there room for a
sidebar and a wide table, or not. Derived from `matchMedia`, never from the
user's density choice.

The two stay independently switchable. A phone may *default* a first-time
user to lite, but a phone user who wants full gets full in a stacked layout,
and a desktop user who wants lite gets lite in a tabular layout. Nothing in
the codebase may read layout to infer density or vice versa.

Stores:

```
stores/viewMode.js   — unchanged contract: 'lite' | 'full', persisted.
                        (Server-side per-user persistence remains future work.)
stores/layout.js     — NEW: readable 'desktop' | 'phone' from
                        window.matchMedia('(max-width: <breakpoint>px)');
                        updates on the media query's change event.
                        main.js mirrors it to document.body.dataset.layout.
```

Breakpoint value is a single exported constant; pick it when the first phone
layout is built (likely ~720px). CSS that needs it uses the same number via a
`@media` rule, components that need a structural swap read the store.

## 4. The four seams

Everything mode-dependent lives in exactly one of these. A template that
mentions `$viewMode` or `$layout` directly outside of these seams is a
convention violation.

### 4.1 Sections — `<FullOnly>` (exists)

Whole blocks that lite simply doesn't show: a secondary `<h3>` + `<dl>`, a
history panel, a side list. Keep the existing wrapper; widen adoption. No new
mechanism needed.

Consider a `<LiteOnly>` sibling only if the §7 inventory turns up something
lite shows that full doesn't (e.g. a compact summary line replacing a table).
Don't add it speculatively.

### 4.2 Rows and labels — `$derived` view objects

Which rows appear (closed items hidden), what a label says ("Jobs" vs "Open
jobs"), whether a cell links out — these are *data-shaping* decisions. The
pattern `ContactDetail.svelte` already uses is the convention:

```svelte
let visibleJobs = $derived(
  $viewMode === 'full' ? contact.jobs : contact.jobs.filter(isOpen)
);
```

The `$derived` (or a pure helper in `lib/`) is the single place the component
consults mode; the markup iterates `visibleJobs` and never branches on mode
itself. Shared row filters (open-vs-closed per entity) belong in a `lib/`
module so the same definition of "closed" is used everywhere.

### 4.3 Columns — a declarative `DataTable` (new)

This is the seam the current code lacks and the one that makes "different
columns per mode" cheap. A shared `components/DataTable.svelte` takes the
column list as data:

```svelte
<DataTable
  rows={pageItems}
  key={(r) => `${r._type}-${r._id}`}
  columns={[
    { id: 'name',     label: 'Name',     cell: nameCell },
    { id: 'type',     label: 'Type',     cell: typeCell,     lite: false },
    { id: 'business', label: 'Business', cell: businessCell },
    { id: 'email',    label: 'Email',    field: 'email',     lite: false },
    { id: 'phone',    label: 'Phone',    field: 'phone' },
    { id: 'tags',     label: 'Tags',     cell: tagsCell,     lite: false, phone: false },
  ]}
/>

{#snippet nameCell(row)}<a href={row.href}>{row.name}</a>{/snippet}
```

Column fields (first cut; trim after the pilot):

| key | meaning |
|---|---|
| `id` | stable identifier, used as `key` and as a `data-col` attribute for CSS/tests |
| `label` | header text |
| `field` | simple accessor — render `row[field]` as text |
| `cell` | snippet `(row) => markup` for anything richer (links, badges, buttons) |
| `lite` | `false` → omitted in lite density. Default `true`. |
| `phone` | `false` → omitted in phone layout regardless of density. Default `true`. |
| `liteLabel` | optional shorter header for lite |
| `align`, `width` | presentational hints, optional |

Behaviour:

- Filters `columns` by `$viewMode` and `$layout`, renders `<thead>`/`<tbody>`
  (satisfying the Svelte 5 strict `<tbody>` rule in one place).
- On `phone` layout, renders the **same filtered columns as a stacked card
  per row** (`<dl>` of label/value, or a `<ul>` of rows) instead of a
  `<table>`. One declaration, three presentations.
- Optional `empty` snippet / `emptyText` for the no-rows case, so the
  `{#if rows.length === 0}<p>…</p>{:else}<table>` boilerplate disappears too.
- Pagination stays outside the table; it is unaffected by mode.
- Removing a link in lite is a `cell` concern: the snippet reads `$viewMode`
  *only if* the link/no-link difference is per-cell. Prefer a `linkInLite:
  false` column flag if the inventory shows this is common, so the snippet
  stays mode-blind.

`LineItemTable.svelte` is **not** migrated onto `DataTable` in the first
pass — it has footers, adjustments and edit affordances that would distort
the generic API. Revisit after the pilot.

### 4.4 Shell — one structural choice in `App.svelte`

The only place parallel *components* are legitimate is the app shell: on
`phone` layout, `App.svelte` mounts a drawer/bottom nav instead of
`Sidebar.svelte`, and `Modal.svelte` goes full-screen. That is a one-time
choice at one spot, not per page. Everything else about phone layout is CSS
under `body[data-layout="phone"]` or `@media`.

## 5. Conventions and anti-patterns

- Pages (`routes/`) never import `viewMode` or `layout`. If a route needs
  mode-aware behaviour it belongs in a component that owns one of the seams.
- Density hides *noise*, never *rights*. Anything a user may not see is
  gated by permissions stores, and the permission check is applied before
  density filtering so a lite-mode user can't toggle into data they lack.
- Don't hide data-heavy content with `display: none`: it is still fetched
  and rendered. CSS-only hiding is fine for decorative/low-cost elements.
- `FullOnly` is for sections; don't wrap a single `<th>` in it (use a column
  flag) or a single row (use a `$derived` filter).
- The two stores are read-only facts to components. Only the toggle
  affordances (sidebar / profile) write `viewMode`; nothing writes `layout`.
- Toggle home: consolidate to one place when the shape is decided (the
  architecture doc's open question). Not blocking.

## 6. Rollout

1. `stores/layout.js` + `body[data-layout]` mirror. Trivial, no visible
   change until something consumes it.
2. `DataTable.svelte` with Vitest coverage for: column filtering by density,
   column filtering by layout, card rendering on phone, `field` vs `cell`,
   empty state.
3. **Pilot:** convert `routes/contacts/ContactListPage.svelte` (the richest
   plain table: links, badges, mixed entity types). Decide which of its
   columns are `lite: false` from §7. Update its Vitest + e2e specs.
4. Document the two axes and four seams in
   `docs/designs/architecture-and-conventions.md` §6, replacing the current
   "deferred pending feedback" text; drop the §10 "Lite-mode rollout" item.
5. Migrate remaining list tables as pages are touched. Candidates in rough
   order of payoff: `JobList`, `InvoiceListPage`, `PurchaseOrderList`,
   `ExpenseListPage`, `CatalogInventoryPage`, `UserListPage`, `Search`.
   Detail-page tables (`ContactDetail` jobs/invoices/POs) follow.
6. Phone shell (§4.4) is its own later effort once the breakpoint and the
   first stacked table exist. It needs its own e2e specs at a phone viewport.

Each step is independently shippable. Steps 1–4 are one plan; step 5 is
ongoing; step 6 is a separate spec.

## 7. Lite-view inventory (RM to fill)

The mechanism above is only as good as the examples it has to express. Before
planning, list concretely what lite hides or shortens, per page, so the
column/section/row flags can be checked against real cases. Suggested
format — one line per page, grouped by seam:

```
Contacts list
  columns hidden in lite:   Type, Email, Tags
  rows hidden in lite:      —
  sections hidden in lite:  —
  text shortened in lite:   —
  links removed in lite:    Business column plain text

Job detail
  columns: …
  rows:    closed estimates / superseded COs?
  sections: history panel detail entries (already), …
```

Things to watch for while filling it in — each would change the design:

- A case where **lite shows something full does not** → needs `<LiteOnly>`
  or a "compact summary" snippet on `DataTable`.
- A case where the hidden thing depends on **who** the user is rather than
  the mode → that is a permission, not density; keep it out of this spec.
- A case where lite wants a **different column order**, not just a subset →
  the column list would need a `liteOrder` or a second ordering.
- A case where "shorter text" means a **different field** rather than a
  shorter label (e.g. job number instead of job title) → `field` /
  `liteField` on the column.
- Anything that varies per **page** rather than per component → suggests the
  page should pass a mode-aware prop into a shared component rather than the
  component reading the store; note it.

## 8. Open questions

- Breakpoint value and whether tablets count as `desktop` (§3).
- Whether phone should default a first-time user to lite (§3). Leaning yes;
  harmless because the toggle remains.
- Where the single toggle lives (sidebar vs profile vs settings).
- Server-side persistence of density per user (existing future-work item;
  unchanged by this spec, but the pilot should not make it harder).
- Whether `DataTable` should own sorting. Today no list sorts client-side
  except by pre-sorting rows; keep sorting out until a page needs it.
