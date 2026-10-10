# View-mode Seams Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the lite/full density and desktop/phone layout plumbing in place (a `layout` store, a declarative `DataTable`), then consolidate every plain list table in the SPA onto `DataTable`, so UI polish and lite-view decisions each have one place to land.

**Architecture:** Two independent Svelte stores (`viewMode` exists; `layout` is new, from `matchMedia`) are consumed only at four seams: `<FullOnly>` for sections (exists), `$derived` filters for rows, a new `components/DataTable.svelte` for columns, and the app shell (out of scope here). `DataTable` takes columns as data with `lite`/`phone` flags and renders a `<table>` on desktop or stacked cards on phone. Three pilots of different shapes (links, row-action buttons, many dense tables with HTML highlights) settle the component's API; the remaining ~35 plain list tables then migrate in five domain batches. Editing grids, document line tables and layout-only tables are explicitly left alone.

**Tech Stack:** Svelte 5 (runes + snippets), Vitest + @testing-library/svelte (jsdom), Playwright e2e, plain CSS in `frontend/src/css/app.css`.

**Spec:** `docs/plans/2026-10-08-view-mode-seams.md` (§3 two axes, §4 four seams, §5 conventions, §6 rollout). This plan implements rollout steps 1–5 (step 5, "migrate remaining list tables", is pulled forward from "as touched" into a deliberate consolidation pass — RM decision 2026-10-09). Step 6 (phone shell) stays out.

**Branch:** all commits go on `feature/lite-view` (already checked out). Do not create a new branch.

## Global Constraints

- Density store values are exactly `'lite'` and `'full'` (spec §3); layout store values are exactly `'desktop'` and `'phone'`.
- Phone breakpoint: `max-width: 720px`, one exported constant `PHONE_MAX_WIDTH = 720` (spec §3).
- Nothing reads `layout` to infer density or `viewMode` to infer layout (spec §3).
- `routes/*.svelte` never import `viewMode` or `layout` (spec §5). A route that uses `DataTable` passes column flags; it does not read the stores.
- Density hides noise, never rights: permission gating stays on the permission stores and is applied **before** density filtering — a page builds its `columns` array from `$canManageX` and hands the result to `DataTable` (spec §5).
- Every `<tr>` lives inside `<thead>`/`<tbody>` (CLAUDE.md "Table markup").
- Migrations are behaviour-preserving: same visible text, same links, same buttons, same `href`s in full density. Lite/phone flags are the only intended visible change, and until RM's §7 inventory exists they are set conservatively (see Task 6 recipe).
- `DataTable`'s API grows only when a migration needs it, and every growth lands with a `DataTable.test.js` case in the same commit.
- Front-end tests: Vitest in `frontend/tests/`, run `npm run test:run` from `frontend/` — never watch mode. E2E: `npx playwright test` from `e2e/`. No Django tests are involved (no backend changes).
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Never push, merge, or open a PR.
- The dev DB is never written to. This plan has no DB-touching steps; the e2e suite uses its own `minibini_e2e` DB.

## Review Focus

1. **`matchMedia` missing** (jsdom, very old browsers): `layout` must stay `'desktop'` and must not throw at import or subscribe. → Task 1 test "stays desktop when matchMedia is unavailable".
2. **Axes are independent**: phone + full must hide `phone: false` columns while showing `lite: false` ones. → Task 2 test "phone layout in full density".
3. **Toggle while mounted**: switching density after the table rendered must add/remove columns reactively, not only on mount. → Task 2 test "reacts to a density change after mount".
4. **Row key collisions**: contacts and businesses share numeric ids (a contact 1 and a business 1 are both real). The pilot's `key` must combine type and id. → Task 3 test "renders a contact and a business that share an id".
5. **Permission-gated columns stay gated in full density**: a user without `can_manage_financials` must not gain the Actions column by switching to full. → Task 6 batch 5 step for `CatalogEarmarksPage` adds the test "no Actions column for a worker in full density".

---

### Task 1: `layout` store (desktop / phone from `matchMedia`)

**Files:**
- Create: `frontend/src/stores/layout.js`
- Modify: `frontend/src/main.js` (mirror to `document.body.dataset.layout`)
- Test: `frontend/tests/stores/layout.test.js`

**Interfaces:**
- Consumes: nothing.
- Produces: `export const PHONE_MAX_WIDTH = 720;` and `export const layout` — a Svelte **readable** store whose value is `'desktop' | 'phone'`. Later tasks `import { layout } from '../stores/layout.js'` and read `$layout`.

- [ ] **Step 1: Write the failing tests**

`frontend/tests/stores/layout.test.js`:

```js
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';

// The store reads window.matchMedia lazily (on first subscribe), so each test
// installs its own fake before importing a fresh copy of the module.
let listeners;
let mq;

function installMatchMedia({ matches }) {
  listeners = [];
  mq = {
    matches,
    media: '(max-width: 720px)',
    addEventListener: (type, fn) => { if (type === 'change') listeners.push(fn); },
    removeEventListener: (type, fn) => { listeners = listeners.filter((l) => l !== fn); },
  };
  window.matchMedia = vi.fn(() => mq);
}

function fireChange(matches) {
  mq.matches = matches;
  for (const fn of listeners) fn({ matches });
}

const originalMatchMedia = window.matchMedia;

beforeEach(() => { vi.resetModules(); });
afterEach(() => { window.matchMedia = originalMatchMedia; });

describe('layout store', () => {
  it('exports the phone breakpoint constant', async () => {
    installMatchMedia({ matches: false });
    const { PHONE_MAX_WIDTH } = await import('@/stores/layout.js');
    expect(PHONE_MAX_WIDTH).toBe(720);
  });

  it('is desktop when the phone media query does not match', async () => {
    installMatchMedia({ matches: false });
    const { layout } = await import('@/stores/layout.js');
    expect(get(layout)).toBe('desktop');
    expect(window.matchMedia).toHaveBeenCalledWith('(max-width: 720px)');
  });

  it('is phone when the phone media query matches', async () => {
    installMatchMedia({ matches: true });
    const { layout } = await import('@/stores/layout.js');
    expect(get(layout)).toBe('phone');
  });

  it('follows change events in both directions while subscribed', async () => {
    installMatchMedia({ matches: false });
    const { layout } = await import('@/stores/layout.js');
    const seen = [];
    const unsubscribe = layout.subscribe((v) => seen.push(v));
    fireChange(true);
    fireChange(false);
    unsubscribe();
    expect(seen).toEqual(['desktop', 'phone', 'desktop']);
  });

  it('removes its listener when the last subscriber leaves', async () => {
    installMatchMedia({ matches: false });
    const { layout } = await import('@/stores/layout.js');
    const unsubscribe = layout.subscribe(() => {});
    expect(listeners).toHaveLength(1);
    unsubscribe();
    expect(listeners).toHaveLength(0);
  });

  it('stays desktop when matchMedia is unavailable', async () => {
    window.matchMedia = undefined;
    const { layout } = await import('@/stores/layout.js');
    expect(() => get(layout)).not.toThrow();
    expect(get(layout)).toBe('desktop');
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run from `frontend/`: `npx vitest run tests/stores/layout.test.js`
Expected: FAIL — every test errors with "Failed to resolve import "@/stores/layout.js"" (module does not exist).

- [ ] **Step 3: Write the store**

`frontend/src/stores/layout.js`:

```js
import { readable } from 'svelte/store';

// Layout axis of the view-mode design (docs/designs/architecture-and-conventions.md
// §6): a DEVICE FACT — is there room for a sidebar and a wide table? — as
// opposed to `viewMode` (lite/full), which is a USER PREFERENCE about data
// density. The two are independent: nothing may read one to infer the other.
//
// 'phone' when the viewport is at most PHONE_MAX_WIDTH px wide, else
// 'desktop'. CSS that needs the same threshold uses `@media (max-width: 720px)`
// or the `body[data-layout]` attribute main.js mirrors this store onto.
export const PHONE_MAX_WIDTH = 720;

const QUERY = `(max-width: ${PHONE_MAX_WIDTH}px)`;

export const layout = readable('desktop', (set) => {
  // jsdom and very old browsers have no matchMedia: stay 'desktop', no throw.
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return undefined;
  }
  const mq = window.matchMedia(QUERY);
  const apply = () => set(mq.matches ? 'phone' : 'desktop');
  apply();
  mq.addEventListener('change', apply);
  return () => mq.removeEventListener('change', apply);
});
```

- [ ] **Step 4: Run the tests to verify they pass**

Run from `frontend/`: `npx vitest run tests/stores/layout.test.js`
Expected: PASS, 6 tests.

- [ ] **Step 5: Mirror the store onto `<body>` in `main.js`**

Edit `frontend/src/main.js` so it reads:

```js
import App from './App.svelte';
import { mount } from 'svelte';
import './css/app.css';
import { viewMode } from './stores/viewMode.js';
import { layout } from './stores/layout.js';

// Density (user preference) and layout (device fact) are mirrored onto <body>
// as data attributes so plain CSS can key off either axis without a component.
viewMode.subscribe((mode) => {
  document.body.dataset.viewMode = mode;
});

// This permanent subscription also keeps the readable store's matchMedia
// listener alive for the lifetime of the app.
layout.subscribe((mode) => {
  document.body.dataset.layout = mode;
});

mount(App, {
  target: document.getElementById('app'),
});
```

- [ ] **Step 6: Run the whole Vitest suite and the production build**

Run from `frontend/`: `npm run test:run`
Expected: all tests pass (read the summary line; the count grows by 6).

Run from `frontend/`: `npm run build`
Expected: build completes with no errors.

- [ ] **Step 7: Commit**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git add frontend/src/stores/layout.js frontend/src/main.js frontend/tests/stores/layout.test.js
git commit -m "feat(frontend): layout store (desktop/phone) mirrored to body[data-layout]

Second axis of the view-mode design: a device fact from matchMedia,
independent of the lite/full density preference.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `DataTable` component (columns as data, density + layout aware)

**Files:**
- Create: `frontend/src/components/DataTable.svelte`
- Modify: `frontend/src/css/app.css` (add `.data-cards` baseline after the `.data-table` block, ~line 152)
- Create: `frontend/tests/components/_DataTableHarness.svelte` (test-only; declares the `cell` snippets a `.js` test cannot)
- Test: `frontend/tests/components/DataTable.test.js`

**Interfaces:**
- Consumes: `viewMode` from `stores/viewMode.js` (`'lite' | 'full'`), `layout` from `stores/layout.js` (`'desktop' | 'phone'`, Task 1).
- Produces: `DataTable` with props:
  - `rows` — array of plain objects.
  - `columns` — array of column defs: `{ id, label, liteLabel?, field?, cell?, lite?, phone?, align? }`.
    - `id` (string, required): stable key; emitted as `data-col={id}` on `<th>`/`<td>`/`<dd>`.
    - `label` (string): header text. `liteLabel` (string, optional): header text used instead when density is lite.
    - `field` (string): render `row[field]` as text (`''` for null/undefined).
    - `cell` (snippet `(row) => markup`): rich cell; wins over `field` when both are given.
    - `lite` (boolean, default `true`): `false` ⇒ omitted when `$viewMode === 'lite'`.
    - `phone` (boolean, default `true`): `false` ⇒ omitted when `$layout === 'phone'`.
    - `align` (`'left' | 'right' | 'center'`, optional): applied as a `text-align` style on `<td>`/`<th>`.
  - `key` — `(row, index) => string|number`, default `(row, i) => i`. Used as the `{#each}` key.
  - `emptyText` — string, default `'No results found.'`; rendered as `<p class="data-table-empty">` when `rows` is empty.
  - `class` — extra class names added to the `<table>` / `<ul>` root.
  - Rendering: desktop ⇒ `<table class="data-table">` with `<thead>` + `<tbody>`; phone ⇒ `<ul class="data-cards">` of `<li class="data-card"><dl>` with one `<dt>`/`<dd>` pair per visible column.
  - Later tasks add `rowClass` (Task 4) and `header` (Task 6 batch 5); those are documented where they land.

- [ ] **Step 1: Write the test harness**

`frontend/tests/components/_DataTableHarness.svelte`:

```svelte
<script>
  // Test-only harness: a .js test can't author Svelte snippets, so the `cell`
  // snippet lives here. Not collected as a test (no .test.js name). Mirrors
  // the harness pattern in tests/components/docsurface/.
  import DataTable from '@/components/DataTable.svelte';
  let { rows = [], emptyText = undefined, extraClass = '' } = $props();
</script>

<DataTable
  {rows}
  {emptyText}
  class={extraClass}
  key={(r) => `${r.kind}-${r.id}`}
  columns={[
    { id: 'name',  label: 'Name',  cell: nameCell },
    { id: 'kind',  label: 'Kind',  field: 'kind',  lite: false },
    { id: 'email', label: 'Email', field: 'email', phone: false },
    { id: 'phone', label: 'Phone number', liteLabel: 'Phone', field: 'phone' },
    { id: 'tags',  label: 'Tags',  field: 'tags',  lite: false, phone: false },
    { id: 'total', label: 'Total', field: 'total', align: 'right' },
  ]}
/>

{#snippet nameCell(row)}
  <a href={row.href}>{row.name}</a>
{/snippet}
```

- [ ] **Step 2: Write the failing tests**

`frontend/tests/components/DataTable.test.js`:

```js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import { tick } from 'svelte';

// Replace the matchMedia-backed readable with a writable so tests can drive
// the layout axis directly (the store itself is covered in tests/stores/).
vi.mock('@/stores/layout.js', async () => {
  const { writable } = await import('svelte/store');
  return { layout: writable('desktop'), PHONE_MAX_WIDTH: 720 };
});

import { viewMode } from '@/stores/viewMode.js';
import { layout } from '@/stores/layout.js';
import Harness from './_DataTableHarness.svelte';

const rows = [
  { kind: 'contact',  id: 1, name: 'Jane Doe',  href: '#/contacts/1',   email: 'j@x.com', phone: '555-0100', tags: 'vip', total: '10.00' },
  { kind: 'business', id: 1, name: 'Acme Corp', href: '#/businesses/1', email: '',        phone: null,       tags: '',    total: '20.00' },
];

function headers(container) {
  return Array.from(container.querySelectorAll('thead th')).map((th) => th.textContent.trim());
}

beforeEach(() => {
  viewMode.set('lite');
  layout.set('desktop');
});

describe('DataTable — density (lite/full) column filtering', () => {
  it('omits lite:false columns in lite density', () => {
    const { container } = render(Harness, { props: { rows } });
    expect(headers(container)).toEqual(['Name', 'Email', 'Phone', 'Total']);
  });

  it('shows every column in full density', () => {
    viewMode.set('full');
    const { container } = render(Harness, { props: { rows } });
    expect(headers(container)).toEqual(['Name', 'Kind', 'Email', 'Phone number', 'Tags', 'Total']);
  });

  it('uses liteLabel only in lite density', async () => {
    const { container } = render(Harness, { props: { rows } });
    expect(headers(container)).toContain('Phone');
    expect(headers(container)).not.toContain('Phone number');
    viewMode.set('full');
    await tick();
    expect(headers(container)).toContain('Phone number');
    expect(headers(container)).not.toContain('Phone');
  });

  it('reacts to a density change after mount', async () => {
    const { container } = render(Harness, { props: { rows } });
    expect(headers(container)).not.toContain('Kind');
    viewMode.set('full');
    await tick();
    expect(headers(container)).toContain('Kind');
    viewMode.set('lite');
    await tick();
    expect(headers(container)).not.toContain('Kind');
  });
});

describe('DataTable — cells', () => {
  it('renders field columns as text and cell columns via the snippet', () => {
    viewMode.set('full');
    const { container, getByRole } = render(Harness, { props: { rows } });
    expect(getByRole('link', { name: 'Jane Doe' })).toHaveAttribute('href', '#/contacts/1');
    const firstRow = container.querySelector('tbody tr');
    expect(firstRow.querySelector('td[data-col="kind"]').textContent.trim()).toBe('contact');
    expect(firstRow.querySelector('td[data-col="email"]').textContent.trim()).toBe('j@x.com');
  });

  it('renders null/undefined field values as empty, never "null"/"undefined"', () => {
    const { container } = render(Harness, { props: { rows } });
    const secondRow = container.querySelectorAll('tbody tr')[1];
    expect(secondRow.querySelector('td[data-col="phone"]').textContent.trim()).toBe('');
    const bare = [{ kind: 'contact', id: 9, name: 'No Phone', href: '#/contacts/9' }];
    const { container: c2 } = render(Harness, { props: { rows: bare } });
    expect(c2.querySelector('td[data-col="phone"]').textContent.trim()).toBe('');
    expect(c2.textContent).not.toMatch(/undefined|null/);
  });

  it('stamps data-col on header and body cells and applies align', () => {
    const { container } = render(Harness, { props: { rows } });
    expect(container.querySelector('th[data-col="total"]')).toBeTruthy();
    const totalCell = container.querySelector('td[data-col="total"]');
    expect(totalCell).toBeTruthy();
    expect(totalCell.getAttribute('style')).toMatch(/text-align:\s*right/);
  });

  it('keys rows by the supplied key so same-id rows of different kinds both render', () => {
    const { container } = render(Harness, { props: { rows } });
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
  });

  it('always wraps rows in thead/tbody', () => {
    const { container } = render(Harness, { props: { rows } });
    expect(container.querySelectorAll('table > tr')).toHaveLength(0);
    expect(container.querySelectorAll('thead > tr')).toHaveLength(1);
    expect(container.querySelectorAll('tbody > tr')).toHaveLength(2);
  });
});

describe('DataTable — empty state', () => {
  it('renders the default empty text and no table when rows is empty', () => {
    const { container, getByText } = render(Harness, { props: { rows: [] } });
    expect(getByText('No results found.')).toBeInTheDocument();
    expect(container.querySelector('table')).toBeNull();
  });

  it('renders a custom emptyText', () => {
    const { getByText } = render(Harness, { props: { rows: [], emptyText: 'No contacts yet.' } });
    expect(getByText('No contacts yet.')).toBeInTheDocument();
  });
});

describe('DataTable — phone layout', () => {
  it('renders stacked cards instead of a table, omitting phone:false columns', () => {
    layout.set('phone');
    const { container } = render(Harness, { props: { rows } });
    expect(container.querySelector('table')).toBeNull();
    const cards = container.querySelectorAll('ul.data-cards > li.data-card');
    expect(cards).toHaveLength(2);
    const labels = Array.from(cards[0].querySelectorAll('dt')).map((dt) => dt.textContent.trim());
    // lite + phone: Kind (lite:false), Email (phone:false), Tags (both) are gone.
    expect(labels).toEqual(['Name', 'Phone', 'Total']);
    expect(cards[0].querySelector('dd[data-col="name"] a')).toHaveAttribute('href', '#/contacts/1');
  });

  it('phone layout in full density hides phone:false columns but shows lite:false ones', () => {
    layout.set('phone');
    viewMode.set('full');
    const { container } = render(Harness, { props: { rows } });
    const labels = Array.from(container.querySelectorAll('li.data-card')[0].querySelectorAll('dt'))
      .map((dt) => dt.textContent.trim());
    expect(labels).toEqual(['Name', 'Kind', 'Phone number', 'Total']);
  });

  it('switches between table and cards when layout changes after mount', async () => {
    const { container } = render(Harness, { props: { rows } });
    expect(container.querySelector('table')).toBeTruthy();
    layout.set('phone');
    await tick();
    expect(container.querySelector('table')).toBeNull();
    expect(container.querySelector('ul.data-cards')).toBeTruthy();
    layout.set('desktop');
    await tick();
    expect(container.querySelector('table')).toBeTruthy();
  });

  it('passes the extra class to whichever root is rendered', async () => {
    const { container } = render(Harness, { props: { rows, extraClass: 'contacts-table' } });
    expect(container.querySelector('table.data-table.contacts-table')).toBeTruthy();
    layout.set('phone');
    await tick();
    expect(container.querySelector('ul.data-cards.contacts-table')).toBeTruthy();
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run from `frontend/`: `npx vitest run tests/components/DataTable.test.js`
Expected: FAIL — "Failed to resolve import "@/components/DataTable.svelte"".

- [ ] **Step 4: Write the component**

`frontend/src/components/DataTable.svelte`:

```svelte
<script>
  // The COLUMN seam of the view-mode design
  // (docs/designs/architecture-and-conventions.md §6). A page declares its
  // columns as data; this component decides which are visible for the
  // current density ($viewMode: lite/full) and layout ($layout:
  // desktop/phone) and renders a <table> on desktop or stacked cards on a
  // phone. Pages never branch on mode themselves.
  //
  // Column def: { id, label, liteLabel?, field?, cell?, lite?, phone?, align? }
  //   id        stable key; emitted as data-col on th/td/dd
  //   label     header text; liteLabel replaces it in lite density
  //   field     render row[field] as text ('' for null/undefined)
  //   cell      snippet (row) => markup; wins over field
  //   lite      false => hidden in lite density        (default true)
  //   phone     false => hidden in phone layout        (default true)
  //   align     'left' | 'right' | 'center' (text-align on th/td)
  import { viewMode } from '../stores/viewMode.js';
  import { layout } from '../stores/layout.js';

  let {
    rows = [],
    columns = [],
    key = (row, i) => i,
    emptyText = 'No results found.',
    class: className = '',
  } = $props();

  let visibleColumns = $derived(
    columns.filter((c) =>
      ($viewMode === 'full' || c.lite !== false) &&
      ($layout === 'desktop' || c.phone !== false)
    )
  );

  function header(col) {
    return $viewMode === 'lite' && col.liteLabel ? col.liteLabel : col.label;
  }

  function text(row, col) {
    const v = row?.[col.field];
    return v == null ? '' : v;
  }

  function alignStyle(col) {
    return col.align ? `text-align: ${col.align}` : undefined;
  }
</script>

{#snippet cellContent(row, col)}
  {#if col.cell}
    {@render col.cell(row)}
  {:else}
    {text(row, col)}
  {/if}
{/snippet}

{#if rows.length === 0}
  <p class="data-table-empty">{emptyText}</p>
{:else if $layout === 'phone'}
  <ul class="data-cards {className}">
    {#each rows as row, i (key(row, i))}
      <li class="data-card">
        <dl>
          {#each visibleColumns as col (col.id)}
            <dt>{header(col)}</dt>
            <dd data-col={col.id}>{@render cellContent(row, col)}</dd>
          {/each}
        </dl>
      </li>
    {/each}
  </ul>
{:else}
  <table class="data-table {className}">
    <thead>
      <tr>
        {#each visibleColumns as col (col.id)}
          <th data-col={col.id} style={alignStyle(col)}>{header(col)}</th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each rows as row, i (key(row, i))}
        <tr>
          {#each visibleColumns as col (col.id)}
            <td data-col={col.id} style={alignStyle(col)}>{@render cellContent(row, col)}</td>
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run from `frontend/`: `npx vitest run tests/components/DataTable.test.js`
Expected: PASS, 14 tests.

- [ ] **Step 6: Add the card baseline CSS**

In `frontend/src/css/app.css`, directly after the line
`:where(.data-table) tbody tr:nth-child(even) { background: var(--doc-faint); }`
insert:

```css

/*
 * Phone-layout counterpart of .data-table: DataTable.svelte renders one card
 * per row (a <dl> of label/value pairs) when body[data-layout="phone"].
 * Same colorway variables as .data-table so a page's .cw-* class themes both.
 */
.data-cards { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.data-card { border: 1px solid var(--doc-border); border-radius: 4px; background: var(--doc-faint); padding: 10px 12px; }
.data-card dl { margin: 0; row-gap: 4px; column-gap: 12px; }
.data-card dt { font-weight: 600; color: var(--doc-accent); font-size: 13px; }
.data-card dd { margin: 0; font-size: 14px; overflow-wrap: anywhere; }
.data-table-empty { color: #555; }
```

(The global `dl` rule already lays `dl` out as a two-column grid, so the card inherits label/value columns.)

- [ ] **Step 7: Run the whole Vitest suite and the production build**

Run from `frontend/`: `npm run test:run`
Expected: all pass (count grows by 14).

Run from `frontend/`: `npm run build`
Expected: no errors (in particular no "`<tr>` is invalid inside `<table>`" compile error).

- [ ] **Step 8: Commit**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git add frontend/src/components/DataTable.svelte frontend/src/css/app.css frontend/tests/components/DataTable.test.js frontend/tests/components/_DataTableHarness.svelte
git commit -m "feat(frontend): DataTable — declarative columns with lite/phone flags, cards on phone

The column seam of the view-mode design: pages declare columns as data,
DataTable filters them by density and layout and renders a table or
stacked cards. Pages stay mode-blind.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Pilot A (links) — Contacts & Businesses list

**Files:**
- Modify: `frontend/src/routes/contacts/ContactListPage.svelte` (the `<table class="data-table">…</table>` block inside the `{:else}` branch near the end of the template, plus the `{:else if filteredItems.length === 0}` branch just above it)
- Test: `frontend/tests/components/contacts/ContactListPage.test.js` (new)
- Create: `frontend/tests/components/contacts/_Noop.svelte` (test-only stub for the two QBO import children)

**Interfaces:**
- Consumes: `DataTable` (Task 2) with props `rows`, `columns`, `key`, `emptyText`.
- Produces: no new exports. Column decision for the pilot (RM may flip any flag — spec §7 inventory is still open; this is a starting point, not a ruling):

  | column | lite | phone |
  |---|---|---|
  | Name | ✓ | ✓ |
  | Type | hidden | ✓ |
  | Business | ✓ | hidden |
  | Email | ✓ | ✓ |
  | Phone | ✓ | ✓ |
  | Tags | hidden | hidden |

- [ ] **Step 1: Write the test stub component**

`frontend/tests/components/contacts/_Noop.svelte`:

```svelte
<script>
  // Test-only stand-in for children that make their own API calls
  // (ContactsImportPanel, QboPullButton) so the list page test only has to
  // mock the list endpoints. Not collected as a test (no .test.js name).
</script>
```

- [ ] **Step 2: Write the failing tests**

`frontend/tests/components/contacts/ContactListPage.test.js`:

```js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import { tick } from 'svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.message || fallback,
}));
vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => {} }));
vi.mock('@/components/qboimport/ContactsImportPanel.svelte', async () =>
  ({ default: (await import('./_Noop.svelte')).default }));
vi.mock('@/components/qboimport/QboPullButton.svelte', async () =>
  ({ default: (await import('./_Noop.svelte')).default }));

import { api } from '@/lib/api.js';
import { viewMode } from '@/stores/viewMode.js';
import { user } from '@/stores/auth.js';
import ContactListPage from '@/routes/contacts/ContactListPage.svelte';

function mockLists({ contacts, businesses }) {
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/tags/')) return Promise.resolve({ results: [] });
    if (url.startsWith('/api/contacts/')) return Promise.resolve({ count: contacts.length, results: contacts });
    if (url.startsWith('/api/businesses/')) return Promise.resolve({ count: businesses.length, results: businesses });
    return Promise.resolve({});
  });
}

const jane = {
  contact_id: 1, name: 'Jane Doe', email: 'jane@example.com', work_number: '555-0100',
  business: { business_id: 1, business_name: 'Acme Corp' },
  tags: [{ tag_id: 3, name: 'vip' }],
};
const acme = { business_id: 1, business_name: 'Acme Corp', business_phone: '555-0200', tags: [] };

function headers(container) {
  return Array.from(container.querySelectorAll('thead th')).map((th) => th.textContent.trim());
}

beforeEach(() => {
  api.get.mockReset();
  api.delete.mockReset();
  viewMode.set('lite');
  user.set({ id: 1, permissions: [] });
  mockLists({ contacts: [jane], businesses: [acme] });
});

describe('ContactListPage — DataTable pilot', () => {
  it('renders a contact and a business that share an id as two rows', async () => {
    const { container } = render(ContactListPage);
    await waitFor(() => expect(container.querySelectorAll('tbody tr')).toHaveLength(2));
    const names = Array.from(container.querySelectorAll('td[data-col="name"]')).map((td) => td.textContent.trim());
    expect(names).toEqual(['Acme Corp', 'Jane Doe']); // sorted by name
  });

  it('in lite density hides the Type and Tags columns', async () => {
    const { container } = render(ContactListPage);
    await waitFor(() => expect(container.querySelector('table')).toBeTruthy());
    expect(headers(container)).toEqual(['Name', 'Business', 'Email', 'Phone']);
    expect(container.textContent).not.toContain('vip');
  });

  it('in full density shows every column including Type and Tags', async () => {
    viewMode.set('full');
    const { container } = render(ContactListPage);
    await waitFor(() => expect(container.querySelector('table')).toBeTruthy());
    expect(headers(container)).toEqual(['Name', 'Type', 'Business', 'Email', 'Phone', 'Tags']);
    expect(container.textContent).toContain('vip');
  });

  it('switching density after load adds the hidden columns without refetching', async () => {
    const { container } = render(ContactListPage);
    await waitFor(() => expect(container.querySelector('table')).toBeTruthy());
    const callsBefore = api.get.mock.calls.length;
    viewMode.set('full');
    await tick();
    expect(headers(container)).toContain('Type');
    expect(api.get.mock.calls.length).toBe(callsBefore);
  });

  it('links the name to the detail route and the business column to the business', async () => {
    const { getByRole, getAllByRole } = render(ContactListPage);
    await waitFor(() => getByRole('link', { name: 'Jane Doe' }));
    expect(getByRole('link', { name: 'Jane Doe' })).toHaveAttribute('href', '#/contacts/1');
    // "Acme Corp" appears as the business row's name link and as Jane's business link.
    const acmeLinks = getAllByRole('link', { name: 'Acme Corp' });
    expect(acmeLinks.map((a) => a.getAttribute('href'))).toEqual(['#/businesses/1', '#/businesses/1']);
  });

  it('shows the dash when a row has no business', async () => {
    mockLists({ contacts: [{ ...jane, business: null }], businesses: [] });
    const { container } = render(ContactListPage);
    await waitFor(() => expect(container.querySelector('table')).toBeTruthy());
    expect(container.querySelector('td[data-col="business"]').textContent.trim()).toBe('—');
  });

  it('shows "No results found." when both lists are empty', async () => {
    mockLists({ contacts: [], businesses: [] });
    const { findByText } = render(ContactListPage);
    expect(await findByText('No results found.')).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run from `frontend/`: `npx vitest run tests/components/contacts/ContactListPage.test.js`
Expected: the "shares an id" and "links the name" tests may pass against the old table; the lite/full header tests FAIL (headers are always all six, and `data-col` attributes don't exist yet). Confirm at least "in lite density hides the Type and Tags columns" fails.

- [ ] **Step 4: Convert the page**

In `frontend/src/routes/contacts/ContactListPage.svelte`:

(a) Add the import at the top of `<script>`, after the existing imports:

```js
  import DataTable from '../../components/DataTable.svelte';
```

(b) Replace the template block that starts at `{:else if filteredItems.length === 0}` and runs through the closing `</table>` with:

```svelte
{:else}
  <DataTable
    rows={pageItems}
    key={(item) => `${item._type}-${item._id}`}
    emptyText="No results found."
    columns={[
      { id: 'name',     label: 'Name',     cell: nameCell },
      { id: 'type',     label: 'Type',     cell: typeCell,     lite: false },
      { id: 'business', label: 'Business', cell: businessCell, phone: false },
      { id: 'email',    label: 'Email',    field: 'email' },
      { id: 'phone',    label: 'Phone',    field: 'phone' },
      { id: 'tags',     label: 'Tags',     cell: tagsCell,     lite: false, phone: false },
    ]}
  />
```

so that the whole loading/error/table region reads:

```svelte
{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else}
  <DataTable … (as above) … />
{/if}
```

The `{:else if filteredItems.length === 0}` branch is removed on purpose: when `filteredItems` is empty so is `pageItems`, and `DataTable` renders the same "No results found." text.

(c) Keep the existing `{#if totalPages > 1}` pagination block unchanged below it.

(d) Add the snippets at the **top level of the template** (after the closing `</div>` of `.page-body`, before `<style>`). Top-level snippets are visible throughout the component's markup, including inside the `columns={[…]}` expression:

```svelte
{#snippet nameCell(item)}
  <a href={item.href}>{item.name}</a>
{/snippet}

{#snippet typeCell(item)}
  {item._type === 'contact' ? 'Contact' : 'Business'}
{/snippet}

{#snippet businessCell(item)}
  {#if item.business_name}<a href="#/businesses/{item.business_id}">{item.business_name}</a>{:else}—{/if}
{/snippet}

{#snippet tagsCell(item)}
  {#each item.tags.slice(0, 3) as tag (tag.tag_id)}
    <span class="row-tag">{tag.name}</span>
  {/each}
  {#if item.tags.length > 3}
    <span class="row-tag-more">+{item.tags.length - 3} more</span>
  {/if}
{/snippet}
```

The `.row-tag` / `.row-tag-more` rules in this component's `<style>` keep applying: snippet markup is compiled in the declaring component, so it carries this component's scope class even when rendered inside `DataTable`.

- [ ] **Step 5: Run the tests to verify they pass**

Run from `frontend/`: `npx vitest run tests/components/contacts/ContactListPage.test.js`
Expected: PASS, 7 tests.

- [ ] **Step 6: Run the whole Vitest suite and the production build**

Run from `frontend/`: `npm run test:run`
Expected: all pass.

Run from `frontend/`: `npm run build`
Expected: no errors. If the build reports an unused CSS selector warning for `.row-tag`, that means the snippet is not scoped as expected — stop and inspect rather than deleting the style.

- [ ] **Step 7: Commit**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git add frontend/src/routes/contacts/ContactListPage.svelte frontend/tests/components/contacts/ContactListPage.test.js frontend/tests/components/contacts/_Noop.svelte
git commit -m "feat(contacts): list page uses DataTable; Type and Tags hidden in lite

Pilot A (links) for the view-mode column seam. Column flags are a
starting point pending the lite-view inventory (spec §7).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Pilot B (row actions + row styling) — `JobList`, adds `rowClass`

`JobList` is the shape "cell that is a `<button>` when a callback is supplied, text otherwise" plus a status column that wants per-row styling. This pilot adds the first API growth: a `rowClass` prop.

**Files:**
- Modify: `frontend/src/components/DataTable.svelte` (add `rowClass`)
- Modify: `frontend/tests/components/_DataTableHarness.svelte` (pass `rowClass` through)
- Modify: `frontend/tests/components/DataTable.test.js` (add one test)
- Modify: `frontend/src/components/jobs/JobList.svelte` (whole file)
- Modify: `frontend/tests/components/jobs/JobList.test.js` (add tests)

**Interfaces:**
- Consumes: `DataTable` from Task 2.
- Produces: `DataTable` prop `rowClass` — `(row) => string | undefined`, default `() => undefined`; its result is added to the `<tr>` class on desktop and the `<li class="data-card">` class on phone. `JobList` keeps its public props `{ jobs, onSelect }` unchanged.

- [ ] **Step 1: Add the `rowClass` test to `DataTable.test.js`**

In `_DataTableHarness.svelte`, add `rowClass = undefined` to the destructured props and pass `{rowClass}` to `<DataTable>`.

Append to `DataTable.test.js`:

```js
describe('DataTable — rowClass', () => {
  it('adds the per-row class to <tr> on desktop and to the card on phone', async () => {
    const rowClass = (r) => `kind-${r.kind}`;
    const { container } = render(Harness, { props: { rows, rowClass } });
    const trs = container.querySelectorAll('tbody tr');
    expect(trs[0].classList.contains('kind-contact')).toBe(true);
    expect(trs[1].classList.contains('kind-business')).toBe(true);
    layout.set('phone');
    await tick();
    const cards = container.querySelectorAll('li.data-card');
    expect(cards[0].classList.contains('kind-contact')).toBe(true);
  });

  it('omits the class attribute noise when rowClass returns undefined', () => {
    const { container } = render(Harness, { props: { rows } });
    expect(container.querySelector('tbody tr').getAttribute('class') || '').toBe('');
  });
});
```

- [ ] **Step 2: Run to verify the new tests fail**

Run from `frontend/`: `npx vitest run tests/components/DataTable.test.js`
Expected: the two new tests FAIL (no class applied); the earlier 14 still pass.

- [ ] **Step 3: Implement `rowClass`**

In `DataTable.svelte`:
- Add `rowClass = () => undefined,` to the `$props()` destructure and document it in the header comment (`rowClass  (row) => extra class on the <tr> / card`).
- Change `<tr>` inside `<tbody>` to `<tr class={rowClass(row)}>`.
- Change `<li class="data-card">` to `<li class="data-card {rowClass(row) || ''}">`.

- [ ] **Step 4: Run to verify they pass**

Run from `frontend/`: `npx vitest run tests/components/DataTable.test.js`
Expected: PASS, 16 tests.

- [ ] **Step 5: Extend `JobList.test.js`**

Replace the file with:

```js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { viewMode } from '@/stores/viewMode.js';
import JobList from '@/components/jobs/JobList.svelte';

const jobs = [
  { job_id: 1, job_number: 'JOB-1', name: 'Alpha', status: 'draft', project_manager: 4, project_manager_name: 'Dana Doe' },
  { job_id: 2, job_number: 'JOB-2', name: 'Beta', status: 'approved' },
];

beforeEach(() => viewMode.set('lite'));

describe('JobList project manager column', () => {
  it('renders the PM name as a link to the PM-filtered list', () => {
    const { getByRole } = render(JobList, { props: { jobs: [jobs[0]] } });
    const link = getByRole('link', { name: 'Dana Doe' });
    expect(link).toHaveAttribute('href', '#/jobs?pm=4');
  });

  it('shows an em dash when a job has no PM', () => {
    const { getByText } = render(JobList, { props: { jobs: [jobs[1]] } });
    expect(getByText('—')).toBeInTheDocument();
  });
});

describe('JobList row selection', () => {
  it('renders the job number as plain text when no onSelect is given', () => {
    const { queryByRole, getByText } = render(JobList, { props: { jobs } });
    expect(queryByRole('button', { name: 'JOB-1' })).toBeNull();
    expect(getByText('JOB-1')).toBeInTheDocument();
  });

  it('renders the job number as a button that calls onSelect with the job', async () => {
    const onSelect = vi.fn();
    const { getByRole } = render(JobList, { props: { jobs, onSelect } });
    await fireEvent.click(getByRole('button', { name: 'JOB-2' }));
    expect(onSelect).toHaveBeenCalledWith(jobs[1]);
  });

  it('stamps a status class on each row', () => {
    const { container } = render(JobList, { props: { jobs } });
    const trs = container.querySelectorAll('tbody tr');
    expect(trs[0].classList.contains('status-draft')).toBe(true);
    expect(trs[1].classList.contains('status-approved')).toBe(true);
  });

  it('shows "No jobs found." for an empty list', () => {
    const { getByText } = render(JobList, { props: { jobs: [] } });
    expect(getByText('No jobs found.')).toBeInTheDocument();
  });

  it('shows all four columns in both densities (no lite flags yet — pending the §7 inventory)', () => {
    const headers = (c) => Array.from(c.querySelectorAll('thead th')).map((th) => th.textContent.trim());
    const { container } = render(JobList, { props: { jobs } });
    expect(headers(container)).toEqual(['Job #', 'Name', 'Status', 'PM']);
    viewMode.set('full');
    const { container: c2 } = render(JobList, { props: { jobs } });
    expect(headers(c2)).toEqual(['Job #', 'Name', 'Status', 'PM']);
  });
});
```

- [ ] **Step 6: Run to verify the new JobList tests fail**

Run from `frontend/`: `npx vitest run tests/components/jobs/JobList.test.js`
Expected: "stamps a status class" FAILS (old markup has no row class); the others pass against the old markup. That one failing test is the signal the conversion is observable.

- [ ] **Step 7: Convert `JobList.svelte`**

Replace the whole file with:

```svelte
<script>
  import DataTable from '../DataTable.svelte';
  const { jobs = [], onSelect = null } = $props();
</script>

<DataTable
  rows={jobs}
  key={(job) => job.job_id}
  emptyText="No jobs found."
  rowClass={(job) => `status-${job.status}`}
  columns={[
    { id: 'number', label: 'Job #',  cell: numberCell },
    { id: 'name',   label: 'Name',   field: 'name' },
    { id: 'status', label: 'Status', field: 'status' },
    { id: 'pm',     label: 'PM',     cell: pmCell },
  ]}
/>

{#snippet numberCell(job)}
  {#if onSelect}
    <button onclick={() => onSelect(job)}>{job.job_number}</button>
  {:else}
    {job.job_number}
  {/if}
{/snippet}

{#snippet pmCell(job)}
  {#if job.project_manager_name}
    <a href="#/jobs?pm={job.project_manager}">{job.project_manager_name}</a>
  {:else}
    —
  {/if}
{/snippet}
```

- [ ] **Step 8: Run tests, suite, build**

Run from `frontend/`: `npx vitest run tests/components/jobs/JobList.test.js` → PASS, 7 tests.
Run from `frontend/`: `npm run test:run` → all pass (PmJobList and JobListPage tests render through JobList and must still pass).
Run from `frontend/`: `npm run build` → no errors.

- [ ] **Step 9: Commit**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git add frontend/src/components/DataTable.svelte frontend/tests/components/_DataTableHarness.svelte frontend/tests/components/DataTable.test.js frontend/src/components/jobs/JobList.svelte frontend/tests/components/jobs/JobList.test.js
git commit -m "feat(jobs): JobList on DataTable; DataTable gains rowClass

Pilot B (row action button + per-row status class).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Pilot C (many dense tables, HTML highlight cells) — Search page

`routes/Search.svelte` renders seven result tables with `{@html hl(...)}` highlighted cells. It is the stress test for column density and for snippets that use `{@html}`. There is no existing test for the page; this task adds one.

**Files:**
- Modify: `frontend/src/routes/Search.svelte` (the seven `<table class="data-table">` blocks, lines ~174–314)
- Test: `frontend/tests/routes/Search.test.js` (new)

**Interfaces:**
- Consumes: `DataTable` (`rows`, `columns`, `key`, `emptyText`).
- Produces: nothing new. Lite decision for the pilot (starting point; the §7 inventory may revise): in lite, each result table keeps its identifying columns and status and drops the long-text/secondary columns:

  | table | hidden in lite |
  |---|---|
  | Jobs | Started, Description, Customer PO |
  | Contacts | Mobile, Home, City |
  | Businesses | Code, Address |
  | Invoices | Created |
  | Estimates | Version, Created |
  | Purchase Orders | Created |
  | Inventory Items | Units |

  "Matching …" columns stay in lite (they are *why* the row matched). Nothing is hidden on phone beyond the lite set; phone-specific trimming waits for the phone shell.

- [ ] **Step 1: Write the failing test**

`frontend/tests/routes/Search.test.js`:

```js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('svelte-spa-router', async () => {
  const { readable } = await import('svelte/store');
  return { querystring: readable('q=acme'), push: vi.fn(), link: () => {} };
});

import { api } from '@/lib/api.js';
import { viewMode } from '@/stores/viewMode.js';
import Search from '@/routes/Search.svelte';

const payload = {
  query: 'acme', total: 2,
  results: {
    jobs: [{
      job: { job_id: 7, job_number: 'JOB-7', name: 'Acme signage', contact_name: 'Jane', status: 'approved',
             created_date: '2026-09-01T00:00:00Z', start_date: null, description: 'Big acme sign', customer_po_number: 'PO-1' },
      tasks: [{ name: 'Cut acme letters' }],
    }],
    contacts: [{ contact_id: 3, name: 'Acme Jane', business_name: 'Acme Corp', email: 'j@acme.com',
                 mobile_number: '555-1', work_number: '555-2', home_number: '555-3', city: 'Springfield' }],
    businesses: [], invoices: [], estimates: [], purchase_orders: [], inventory_items: [],
  },
};

function headersOf(table) {
  return Array.from(table.querySelectorAll('thead th')).map((th) => th.textContent.trim());
}

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue(payload);
  viewMode.set('lite');
});

describe('Search results tables — DataTable pilot', () => {
  it('renders job and contact result tables with highlighted, linked identifiers', async () => {
    const { container, getByRole } = render(Search);
    await waitFor(() => expect(container.querySelectorAll('table.data-table')).toHaveLength(2));
    const jobLink = getByRole('link', { name: /JOB-7/ });
    expect(jobLink).toHaveAttribute('href', '#/jobs/7');
    // hl() wraps the match in <mark>; the snippet must still emit it as HTML.
    expect(container.querySelector('td[data-col="name"] mark')).toBeTruthy();
    expect(getByRole('link', { name: /Acme Jane/ })).toHaveAttribute('href', '#/contacts/3');
  });

  it('in lite density drops the long-text job columns and the secondary contact columns', async () => {
    const { container } = render(Search);
    await waitFor(() => expect(container.querySelectorAll('table.data-table')).toHaveLength(2));
    const [jobs, contacts] = container.querySelectorAll('table.data-table');
    expect(headersOf(jobs)).toEqual(['Job #', 'Name', 'Contact', 'Status', 'Created', 'Matching Tasks']);
    expect(headersOf(contacts)).toEqual(['Name', 'Business', 'Email']);
  });

  it('in full density shows every column', async () => {
    viewMode.set('full');
    const { container } = render(Search);
    await waitFor(() => expect(container.querySelectorAll('table.data-table')).toHaveLength(2));
    const [jobs, contacts] = container.querySelectorAll('table.data-table');
    expect(headersOf(jobs)).toEqual(['Job #', 'Name', 'Contact', 'Status', 'Created', 'Started', 'Description', 'Customer PO', 'Matching Tasks']);
    expect(headersOf(contacts)).toEqual(['Name', 'Business', 'Email', 'Mobile', 'Work', 'Home', 'City']);
  });

  it('renders dashes for empty values via hl()', async () => {
    viewMode.set('full');
    const { container } = render(Search);
    await waitFor(() => expect(container.querySelectorAll('table.data-table')).toHaveLength(2));
    const jobs = container.querySelector('table.data-table');
    expect(jobs.querySelector('td[data-col="started"]').textContent.trim()).toBe('—');
  });
});
```

Before running, check how `Search.svelte` triggers its fetch (an `$effect` on `query`, which comes from the mocked `querystring`). If the fetch is wired to a form submit instead, adjust the test to drive that control; do not change the page's fetch behaviour to suit the test.

- [ ] **Step 2: Run to verify it fails**

Run from `frontend/`: `npx vitest run tests/routes/Search.test.js`
Expected: the lite-density test FAILS (all nine job headers present) and the `data-col` lookups FAIL; the first test may pass.

- [ ] **Step 3: Convert the seven tables**

In `Search.svelte`, add `import DataTable from '../components/DataTable.svelte';` to the script. Replace each `<table class="data-table">…</table>` block with a `<DataTable>` whose columns are the existing headers in the existing order, `key` the entity's pk, and cells moved into top-level snippets. The `<h3>` headings and the `{#if results.results.X?.length}` guards stay as they are. Worked conversion for the first two tables (the remaining five follow the identical pattern with the lite flags from the table above):

```svelte
{#if results.results.jobs?.length}
  <h3>Jobs</h3>
  <DataTable
    rows={results.results.jobs}
    key={(g) => g.job.job_id}
    columns={[
      { id: 'number',      label: 'Job #',          cell: jobNumberCell },
      { id: 'name',        label: 'Name',           cell: jobNameCell },
      { id: 'contact',     label: 'Contact',        cell: jobContactCell },
      { id: 'status',      label: 'Status',         cell: jobStatusCell },
      { id: 'created',     label: 'Created',        cell: jobCreatedCell },
      { id: 'started',     label: 'Started',        cell: jobStartedCell,  lite: false },
      { id: 'description', label: 'Description',    cell: jobDescCell,     lite: false },
      { id: 'po',          label: 'Customer PO',    cell: jobPoCell,       lite: false },
      { id: 'tasks',       label: 'Matching Tasks', cell: jobTasksCell },
    ]}
  />
{/if}

{#if results.results.contacts?.length}
  <h3>Contacts</h3>
  <DataTable
    rows={results.results.contacts}
    key={(c) => c.contact_id}
    columns={[
      { id: 'name',     label: 'Name',     cell: contactNameCell },
      { id: 'business', label: 'Business', cell: contactBusinessCell },
      { id: 'email',    label: 'Email',    cell: contactEmailCell },
      { id: 'mobile',   label: 'Mobile',   cell: contactMobileCell, lite: false },
      { id: 'work',     label: 'Work',     cell: contactWorkCell },
      { id: 'home',     label: 'Home',     cell: contactHomeCell,   lite: false },
      { id: 'city',     label: 'City',     cell: contactCityCell,   lite: false },
    ]}
  />
{/if}
```

and the snippets, placed at the top level of the template (outside `.search-layout`), one per cell, each a one-liner carrying the exact expression the old `<td>` had:

```svelte
{#snippet jobNumberCell(g)}<a href="#/jobs/{g.job.job_id}">{@html hl(g.job.job_number)}</a>{/snippet}
{#snippet jobNameCell(g)}{@html hl(g.job.name)}{/snippet}
{#snippet jobContactCell(g)}{@html hl(g.job.contact_name)}{/snippet}
{#snippet jobStatusCell(g)}{g.job.status}{/snippet}
{#snippet jobCreatedCell(g)}{formatDate(g.job.created_date)}{/snippet}
{#snippet jobStartedCell(g)}{formatDate(g.job.start_date)}{/snippet}
{#snippet jobDescCell(g)}{@html hlt(g.job.description)}{/snippet}
{#snippet jobPoCell(g)}{@html hl(g.job.customer_po_number)}{/snippet}
{#snippet jobTasksCell(g)}{@html hlt(g.tasks.map(t => t.name).join(', ') || null)}{/snippet}

{#snippet contactNameCell(c)}<a href="#/contacts/{c.contact_id}">{@html hl(c.name)}</a>{/snippet}
{#snippet contactBusinessCell(c)}{#if c.business_name}{@html hl(c.business_name)}{:else}—{/if}{/snippet}
{#snippet contactEmailCell(c)}{@html hl(c.email)}{/snippet}
{#snippet contactMobileCell(c)}{@html hl(c.mobile_number)}{/snippet}
{#snippet contactWorkCell(c)}{@html hl(c.work_number)}{/snippet}
{#snippet contactHomeCell(c)}{@html hl(c.home_number)}{/snippet}
{#snippet contactCityCell(c)}{@html hl(c.city)}{/snippet}
```

Repeat for Businesses (`key: b.business_id`; `Code`, `Address` get `lite: false`), Invoices (`key: inv.invoice_id`; `Created` gets `lite: false`), Estimates (`key: est.estimate_id`; `Version`, `Created` get `lite: false`), Purchase Orders (`key: po.po_id`; `Created` gets `lite: false`) and Inventory Items (`key: item.inventory_item_id`; `Units` gets `lite: false`). Every old `<td>` expression moves verbatim into its snippet; `formatDate`, `hl`, `hlt` are unchanged.

If the snippet count feels heavy, that is the honest cost of this page having 38 cells; do **not** collapse them into a generic "html field" column type in this task — note the idea in `docs/designs/LATER.md` instead and let the batch migration (Task 6) decide if a second page needs it.

- [ ] **Step 4: Run tests, suite, build**

Run from `frontend/`: `npx vitest run tests/routes/Search.test.js` → PASS, 4 tests.
Run from `frontend/`: `npm run test:run` → all pass.
Run from `frontend/`: `npm run build` → no errors.

- [ ] **Step 5: Commit**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git add frontend/src/routes/Search.svelte frontend/tests/routes/Search.test.js
git commit -m "feat(search): result tables on DataTable; long-text columns hidden in lite

Pilot C (seven dense tables, {@html} highlight cells).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: API freeze, then batched migration of the remaining plain lists

After the three pilots the `DataTable` API is: `rows`, `columns` (`id, label, liteLabel, field, cell, lite, phone, align`), `key`, `emptyText`, `class`, `rowClass`. One further growth is pre-authorised in batch 5 (`header` snippet for sortable headers). Any other growth needs a one-line justification in the commit message and a `DataTable.test.js` case.

**Scope — migrate (plain lists, ~35 tables):** listed per batch below with their current headers (an empty header is an unlabeled actions column: `label: ''` + a `cell` snippet).

**Scope — do NOT migrate:**
- Editing grids with per-row inputs: all six `components/qboimport/*ImportPanel.svelte`, `purchaseorders/ReceiveItemsForm.svelte`, `purchaseorders/ReconciliationSection.svelte`, `changeorders/CODeliverablesSection.svelte`, `jobs/DeliverablesEditModal.svelte`, `settings/AccountingCategories.svelte`, `routes/SettingsPage.svelte`, `expenses/UserReimbursementPanel.svelte`, `shipments/ShipmentsPanel.svelte`.
- Document line tables with footers/totals: `LineItemTable.svelte`, `estimates/EstimateEditView.svelte`, `changeorders/COEditView.svelte`, `changeorders/COCustomerView.svelte`, `invoices/InvoiceEditView.svelte`, `docsurface/*`, `TaskTree.svelte`, `EstimatePortal.svelte`, `ChangeOrderPortal.svelte`, `routes/*/…SendPage.svelte`, `routes/shipments/PackingListPrint.svelte`, `routes/jobs/TaskDetailPage.svelte`, `purchaseorders/PurchaseOrderDetail.svelte`.
- Tables used as key/value layout (no header row): `board/UnpaidCard.svelte`, `email/EmailContent.svelte`, `email/SenderResolutionForm.svelte`, `routes/email/EmailAssociatePage.svelte`, `routes/email/EmailAssociatePOPage.svelte`, `settings/EmailTemplates.svelte`, `jobs/DeliverablesSection.svelte`, `jobs/JobHistorySection.svelte`. (Candidates for a `<dl>` cleanup later; add one line to `docs/designs/LATER.md` in batch 5.)

**The recipe (apply to every file in every batch):**

1. Read the file. Confirm it is a plain list (no `<input>`/`<select>` inside `<tbody>`, no `<tfoot>`). If it is not, leave it and note why in the batch commit message.
2. `import DataTable from '<relative path>/DataTable.svelte'`.
3. Replace `{#if items.length === 0}<p>No X found.</p>{:else}<table>…</table>{/if}` with one `<DataTable rows={items} key={…} emptyText="No X found." columns={[…]} />`. Keep the page's own loading/error branches and any pagination untouched.
4. One column per existing `<th>`, same order, same label text. A header that is a plain string becomes `label`. `<td>` content that is a bare `{row.field}` becomes `field: 'field'`; anything else (links, buttons, conditionals, formatters, `{@html}`) moves **verbatim** into a top-level `{#snippet xCell(row)}`. Right-aligned money columns get `align: 'right'` instead of the inline style.
5. Permission-gated columns (`{#if $canManageX}<th>…`) are gated by **building the array**, not by a column flag:
   ```svelte
   columns={[
     ...baseColumns,
     ...($canManageFinancials ? [{ id: 'actions', label: '', cell: actionsCell }] : []),
   ]}
   ```
   where `baseColumns` is an inline array literal in the same expression (keep snippets referenced from markup). Permission filtering is applied before density filtering by construction.
6. Row `key`: the entity pk (`job_id`, `invoice_id`, `po_id`, `contact_id`, `business_id`, `blep_id`, `shift_id`, `user_id`/`id`, `inventory_item_id`, `earmark_id`, `rate_scheme_id`, `service_item_id`, `terms_id`, …). Read the field name off the existing `{#each … (key)}` or the row's link `href`; never fall back to the index when a pk exists.
7. Per-row status styling that existed as `class={…}` on `<tr>` becomes `rowClass`.
8. **Lite flags are conservative:** set `lite: false` only on columns that are (a) free-text descriptions/notes/reasons, (b) secondary identifiers (reference codes, IP addresses, versions), or (c) a second/third phone or address. Never flag identifiers, names, status, dates that drive action, money owed, or action columns. Set no `phone: false` flags in this task (the phone shell is later). Record each page's chosen lite set as one line in the batch commit message so RM's §7 inventory can start from it.
9. Tests: run the component's existing test file first (unchanged, must still pass — behaviour preserved). Then add one test to it (create `tests/components/<path>/<Name>.test.js` if none exists, mirroring the mocks of the nearest sibling test) asserting the lite header list vs the full header list, using the `headers(container)` helper from Task 3's test. If the component took no lite flags, the test asserts both lists are equal, as in Task 4's JobList test.
10. `npm run test:run` and `npm run build` green before each batch commit.

**Batch 1 — CRM** (one commit):

| file | headers today | notes |
|---|---|---|
| `components/contacts/ContactList.svelte` | Name, Email, Phone | `onSelect` button pattern as in JobList |
| `components/contacts/BusinessList.svelte` | Reference, Name, Phone | Reference → `lite: false` |
| `components/contacts/ContactDetail.svelte` (3 tables) | Jobs: Job #, Name, Status · Invoices: Invoice #, Job, Status, Total, Paid, Balance · POs: PO #, Status | rows are already the `visibleJobs`/`visibleInvoices`/`visiblePOs` `$derived`s — pass those; the "No open jobs." empty copy stays via `emptyText` |
| `components/contacts/BusinessDetail.svelte` (4 tables) | Contacts: Name, Email, Phone · Jobs/Invoices/POs as above | same |

Existing tests to keep green: `tests/components/contacts/ContactDetail.test.js`, `BusinessDetail.test.js`, `ContactDetailPage.test.js`, `ContactPicker.test.js`, `BusinessPicker.test.js` (pickers render the lists).

- [ ] Apply the recipe to the four files; add lite/full header tests; suite + build green.
- [ ] Commit: `refactor(contacts): CRM lists on DataTable` with the per-page lite sets in the body.

**Batch 2 — Jobs & money lists** (one commit):

| file | headers today | notes |
|---|---|---|
| `routes/invoices/InvoiceListPage.svelte` | Invoice #, Job, Customer, Status, Sent, Due, Amount, Paid, Balance | money columns `align: 'right'`; `is_late` row styling → `rowClass` |
| `components/purchaseorders/PurchaseOrderList.svelte` | PO #, Vendor, Status, Created, Requested, Total, (actions) | |
| `components/purchaseorders/POPanel.svelte` | PO #, Status, Vendor, Total | |
| `routes/expenses/ExpenseListPage.svelte` (2 tables) | Date, Who (purchased by), Description, Job, Task, Category, Amount, Paid, Status, Actions | inspect the second table; migrate only if it is a plain list |
| `components/qbo/QBOSyncFailures.svelte` | Entity, Op, Amount, (actions) | |
| `components/jobs/PmJobList.svelte` | — | renders `JobList` (already migrated); no change, verify only |

Existing tests: `InvoiceListPage.test.js`, `PurchaseOrderList.test.js`, `PurchaseOrderListPage.test.js`, `POPanel.test.js`, `QBOSyncFailures.test.js`, `PmJobList.test.js`, `JobListPage.test.js`.

- [ ] Apply the recipe; add header tests; suite + build green.
- [ ] Commit: `refactor(lists): invoices, POs, expenses, QBO failures on DataTable`.

**Batch 3 — Home panels & email** (one commit):

| file | headers today | notes |
|---|---|---|
| `components/home/CurrentTaskList.svelte` | Task, Job, Status, Start, Reorder | Start/Reorder are action cells |
| `components/home/ExpensesList.svelte` | Date, Description, Job, Task, Amount, Status, Reimbursed | |
| `components/home/MyChangeRequestsList.svelte` | Type, Requested, Status, Reason | Reason → `lite: false` |
| `components/home/RecentLoginsList.svelte` | Time, IP address | IP address → `lite: false` |
| `components/home/RecentTaskList.svelte` | Task, Job, Last worked | |
| `components/email/EmailList.svelte` | Date, From, Subject, Job, Attachments | |

Existing tests: all five `tests/components/home/*List.test.js`; EmailList is exercised through `email/EmailActionPanel.test.js` / inbox tests — check with `grep -rl EmailList frontend/tests`.

- [ ] Apply the recipe; add header tests; suite + build green.
- [ ] Commit: `refactor(home,email): panel lists on DataTable`.

**Batch 4 — Time & users** (one commit):

| file | headers today | notes |
|---|---|---|
| `components/time/BlepLogTable.svelte` | Worker, Task, Job, Start, End, Duration, (actions) | has a test harness `_BlepLogTableHarness.svelte` — keep it working |
| `components/time/ShiftLogTable.svelte` | Worker, Clock In, Clock Out, Duration, (actions) | harness `_ShiftLogTableHarness.svelte` |
| `components/tasks/BlepList.svelte` | Worker, Start, End, Elapsed, (actions) | |
| `components/users/PayrollReport.svelte` | Date, Shifts, Day total | |
| `components/users/ShiftRequestQueue.svelte` | Type, Worker, Record, Requested, Reason, Conflict, Actions | Reason → `lite: false` |
| `routes/users/UserListPage.svelte` | Username, Name, Email, Permissions, Status, Actions | |

Existing tests: `time/BlepLogTable.test.js`, `time/ShiftLogTable.test.js`, `tasks/BlepList.test.js`, `users/PayrollReport.test.js`, `users/ShiftRequestQueue.test.js`, `users/UserListPage.workSessions.test.js`.

- [ ] Apply the recipe; add header tests; suite + build green.
- [ ] Commit: `refactor(time,users): logs and queues on DataTable`.

**Batch 5 — Catalog, settings managers, decision dialogs** (one commit; includes the `header` growth):

`routes/catalog/CatalogEarmarksPage.svelte` has sortable headers (`<th><button class="sort" onclick={() => setSort('item_code')}>Code</button></th>`). This is the pre-authorised API growth: a column may carry `header` — a snippet `(col) => markup` rendered inside `<th>` instead of `label` text (the `label` is still required and is what the phone card `<dt>` shows).

- [ ] **Step 5.1: Add the `header` test to `DataTable.test.js`** — extend `_DataTableHarness.svelte` with a prop `sortable = false` that, when true, replaces the `name` column def with `{ id: 'name', label: 'Name', cell: nameCell, header: sortHeader }` and declares `{#snippet sortHeader(col)}<button type="button" class="sort">{col.label} ▲</button>{/snippet}`. Test:

```js
describe('DataTable — header snippet', () => {
  it('renders the header snippet inside <th> on desktop and the plain label in phone cards', async () => {
    const { container } = render(Harness, { props: { rows, sortable: true } });
    const th = container.querySelector('th[data-col="name"]');
    expect(th.querySelector('button.sort')).toBeTruthy();
    expect(th.textContent).toContain('Name ▲');
    layout.set('phone');
    await tick();
    const dt = container.querySelector('li.data-card dt');
    expect(dt.textContent.trim()).toBe('Name');
    expect(dt.querySelector('button')).toBeNull();
  });
});
```

- [ ] **Step 5.2: Implement** — in `DataTable.svelte`'s `<th>`: `{#if col.header}{@render col.header(col)}{:else}{header(col)}{/if}`. Cards keep `{header(col)}`. Document `header` in the component's header comment. Run `DataTable.test.js` → PASS, 17 tests.

- [ ] **Step 5.3: Apply the recipe to:**

| file | headers today | notes |
|---|---|---|
| `routes/catalog/CatalogInventoryPage.svelte` | Code, Description, Units, On hand, Earmarked, Available, On order, Status, Cost, Sell, Actions | numeric columns `align: 'right'`; Actions gated on `$canManageFinancials` via array construction |
| `routes/catalog/CatalogEarmarksPage.svelte` | Code, Description, Units, Job, Earmarked, On hand, On order, Shortfall, POs, (actions if `$canManageFinancials`) | sortable headers via `header` snippets calling the existing `setSort(...)`; **add the Review Focus test**: with `user.set({ id: 1, permissions: [] })` and `viewMode.set('full')`, the headers list contains no empty/Actions column |
| `components/RateSchemeManager.svelte` | Name, Type, Rate, Unit, Category, Modifiers, Active, (actions) | Modifiers → `lite: false` |
| `components/ServiceItemManager.svelte` | Name, Rate Scheme, Active, (actions) | |
| `components/settings/PaymentTermsManager.svelte` | Name, Days, (?), In use, (actions) | inspect the unlabeled third header |
| `components/UnitsManager.svelte` | Unit, Order, (actions) | not `data-table` today — adopt the house class via DataTable, check the visual |
| `components/purchaseorders/RatePromptDialog.svelte` | Task, Current Rate, Suggested Rate, Decision | Decision is a button cell; stays in lite |
| `components/purchaseorders/MaterialSeverDialog.svelte` | Job, Material, Qty, Decision | has two inputs in the table — if they are inside `<tbody>`, this is an editing grid: skip it and say so |

Existing tests: `catalog/CatalogInventoryPage.test.js`, `catalog/CatalogEarmarksPage.test.js`, `RateSchemeManager.test.js`, `ServiceItemManager.test.js`, `settings/PaymentTermsManager.test.js`, `UnitsManager.test.js`, `purchaseorders/RatePromptDialog.test.js`, `purchaseorders/MaterialSeverDialog.test.js`.

- [ ] **Step 5.4:** add to `docs/designs/LATER.md`: one line listing the eight layout-only tables as `<dl>` cleanup candidates, and (if Task 5 raised it) the "generic html-field column" idea.
- [ ] Suite + build green. Commit: `refactor(catalog,settings): managers on DataTable; DataTable gains header snippet`.

---

### Task 7: E2E — lite hides columns, FULL toggle restores them

**Files:**
- Create: `e2e/specs/contacts/lite-view-columns.spec.js`

**Interfaces:**
- Consumes: the converted contacts list (Task 3), the sidebar `LITE | FULL` toggle (`components/Sidebar.svelte`, a `<button>` named `FULL` when lite is active), persona `worker` from `e2e/fixtures/personas.js`.

There is no `docs/ui-flows/` doc for view mode yet, so test titles describe the behaviour directly instead of citing a § number.

- [ ] **Step 1: Write the spec**

```js
// View-mode column seam on the Contacts & Businesses list: lite density hides
// the Type and Tags columns; flipping the sidebar toggle to FULL brings them
// back without a reload (docs/plans/2026-10-08-view-mode-seams.md §4.3).
import { expect, test } from '@playwright/test';
import { personas } from '../../fixtures/personas.js';

test.use({ storageState: personas.worker.storageState });

test.beforeEach(async ({ page }) => {
  // Pin density to lite regardless of what the saved session carries.
  await page.addInitScript(() => localStorage.setItem('minibini_view_mode', 'lite'));
});

test('lite hides Type and Tags; FULL restores them', async ({ page }) => {
  await page.goto('/#/contacts');
  const table = page.locator('table.data-table');
  await expect(table).toBeVisible();

  await test.step('Lite: Name/Business/Email/Phone headers only', async () => {
    await expect(table.getByRole('columnheader', { name: 'Name' })).toBeVisible();
    await expect(table.getByRole('columnheader', { name: 'Email' })).toBeVisible();
    await expect(table.getByRole('columnheader', { name: 'Type' })).toHaveCount(0);
    await expect(table.getByRole('columnheader', { name: 'Tags' })).toHaveCount(0);
  });

  await test.step('Toggle FULL in the sidebar → Type and Tags appear', async () => {
    // The sidebar is a pull-out that animates on hover — dispatch the event
    // directly (same approach as specs/setup-status.spec.js).
    await page.locator('.sidebar').dispatchEvent('mouseenter');
    await page.getByRole('button', { name: 'FULL' }).click();
    await expect(table.getByRole('columnheader', { name: 'Type' })).toBeVisible();
    await expect(table.getByRole('columnheader', { name: 'Tags' })).toBeVisible();
    await expect(table.locator('tbody tr').first()).toBeVisible();
  });

  await test.step('Toggle LITE → they are gone again', async () => {
    await page.locator('.sidebar').dispatchEvent('mouseenter');
    await page.getByRole('button', { name: 'LITE' }).click();
    await expect(table.getByRole('columnheader', { name: 'Type' })).toHaveCount(0);
    await expect(table.getByRole('columnheader', { name: 'Tags' })).toHaveCount(0);
  });
});
```

- [ ] **Step 2: Run the spec**

Run from `e2e/`: `npx playwright test specs/contacts/lite-view-columns.spec.js`
Expected: 1 passed. If the `FULL` button is not found, the sidebar did not open — check `.sidebar` is the pull-out's root class and adjust the locator, not the app.

- [ ] **Step 3: Run the full e2e suite once**

Run from `e2e/`: `npx playwright test`
Expected: all passed. The migrated lists are behaviour-preserving in full density and the suite's existing specs assert on link/button names, which the snippets keep. Any failure here is a regression in a migration, not a test to loosen.

- [ ] **Step 4: Commit**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git add e2e/specs/contacts/lite-view-columns.spec.js
git commit -m "test(e2e): contacts list hides Type/Tags in lite, FULL toggle restores

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Documentation — two axes, four seams, migration state

**Files:**
- Modify: `docs/designs/architecture-and-conventions.md` — §6 "View mode (full / lite)" (lines ~1199–1256) and the "Lite-mode rollout" bullet in §10 (lines ~1917–1921)
- Modify: `frontend/README.md` — "### View Mode (Full / Lite)" section (lines ~424–430)
- Modify: `docs/designs/frontend-testing.md` — "## Coverage status" (append one line)
- Modify: `docs/plans/2026-10-08-view-mode-seams.md` — Status line

- [ ] **Step 1: Rewrite §6 of the architecture doc**

Replace everything from `## 6. View mode (full / lite)` up to (not including) `## 7. History and notes` with:

```markdown
## 6. View mode: density and layout

Two independent axes (design: `docs/plans/2026-10-08-view-mode-seams.md`,
2026-10-08):

- **Density** — `lite` / `full`. A *user preference* about how much data is
  in front of them: some people want everything, some want only what the
  task at hand needs. Most shop-floor workers are expected to stay in lite,
  but it is a working-style choice, not a role. It is **never** a permission
  mechanism: anything a user may not see is gated by the permission stores
  first (a page builds its column array from `$canManageX`), and density
  only trims what remains.
- **Layout** — `desktop` / `phone`. A *device fact*: is there room for a
  sidebar and a wide table? Derived from `matchMedia`, never from the
  density choice.

Nothing reads one axis to infer the other. A phone user may run full
density in a stacked layout; a desktop user may run lite in a tabular one.

### 6.1 Stores

`frontend/src/stores/viewMode.js` — writable `'lite' | 'full'`, default
`'lite'`, persisted to `localStorage` under `minibini_view_mode`;
`toggleViewMode()` flips it. Written only by the two toggle affordances
(sidebar `LITE | FULL`, profile panel). Server-side per-user persistence
remains future work.

`frontend/src/stores/layout.js` — readable `'desktop' | 'phone'` from
`window.matchMedia('(max-width: 720px)')`, following `change` events;
`'desktop'` when `matchMedia` is unavailable (jsdom). Exports
`PHONE_MAX_WIDTH = 720`; CSS uses the same number in `@media` rules.
Nothing writes it.

`main.js` mirrors both onto `<body>` as `data-view-mode` and `data-layout`
so plain CSS can key off either axis.

### 6.2 The four seams

All mode-dependent behaviour lives in exactly one of these. A template that
reads `$viewMode` or `$layout` anywhere else is a convention violation, and
`routes/*.svelte` never import either store.

1. **Sections — `<FullOnly>`** (`components/FullOnly.svelte`). Whole blocks
   lite doesn't show. Consumers: `contacts/ContactDetail.svelte`,
   `contacts/BusinessDetail.svelte`.
2. **Rows and labels — `$derived` view objects.** Which rows appear (closed
   items hidden), what a label says, whether a cell links out. One
   `$derived` (or a pure `lib/` helper) consults the store; the markup
   iterates the result and never branches on mode. Exemplar:
   `ContactDetail.svelte`'s `visibleJobs` / `visibleInvoices` / `visiblePOs`.
   `HistoryPanel.svelte` filters entries the same way.
3. **Columns — `components/DataTable.svelte`.** Every plain list table in
   the SPA (~40 tables, consolidated 2026-10) declares its columns as data:
   `{ id, label, liteLabel?, field?, cell?, header?, lite?, phone?, align? }`.
   `lite: false` hides a column in lite density; `phone: false` hides it in
   phone layout. `cell` is a Svelte 5 snippet `(row) => markup` for links,
   badges, buttons and `{@html}`; `field` renders `row[field]` as text;
   `header` is an optional snippet for the `<th>` (sortable headers).
   Permission-gated columns are added to the array conditionally by the
   page, never via a flag. On phone the same visible columns render as one
   `<dl>` card per row (`.data-cards` / `.data-card` in `app.css`) instead
   of a `<table>`. Props: `rows`, `columns`, `key` (`(row, i) => key`),
   `emptyText`, `class`, `rowClass` (`(row) => class`).
   **Not** on `DataTable`, deliberately: editing grids with per-row inputs
   (QBO import panels, receive/reconcile forms, deliverables editors,
   settings grids), document line tables with footers (`LineItemTable`,
   estimate/CO/invoice edit views, docsurface, portals, send pages), and
   the handful of tables used as key/value layout (LATER.md lists them for
   a `<dl>` cleanup).
4. **Shell — `App.svelte`.** The one place a *parallel component* is
   legitimate: on phone layout the shell may mount a drawer nav instead of
   `Sidebar.svelte` and make modals full-screen. Not built yet.

Anti-patterns: wrapping a single `<th>` in `<FullOnly>` (use a column
flag); wrapping a single row (use a `$derived` filter); hiding fetched,
data-heavy content with `display: none`; a `lite`/`phone` flag on a
permission-gated column.

### 6.3 Toggle location

The density toggle lives at the bottom of the sidebar
(`components/Sidebar.svelte`, `LITE | FULL`) and in the profile panel
(`home/ProfilePanel.svelte`). Consolidating to one home is an open
question. There is no layout toggle: layout is a device fact.

### 6.4 Rollout state

Done (2026-10, `feature/lite-view`): both stores, `DataTable`, all plain
list tables migrated. Lite flags are a conservative first cut (free text,
secondary identifiers, extra phones/addresses hidden); the per-page lite
inventory (spec §7) is RM's and will revise them. Remaining: the phone
shell, `phone: false` flags once the shell exists, toggle consolidation,
server-side density persistence.

---
```

- [ ] **Step 2: Replace the §10 "Lite-mode rollout" bullet**

Replace the bullet that begins `- **Lite-mode rollout** (deferred pending user feedback).` (four lines) with:

```markdown
- **View-mode rollout.** Plumbing and the list-table consolidation are in
  (§6). Remaining: build the phone shell, fill the per-page lite inventory
  (`docs/plans/2026-10-08-view-mode-seams.md` §7) and revise the column
  flags from it, consolidate the density toggle to one home, and persist
  density server-side per user.
```

- [ ] **Step 3: Update the frontend README view-mode section**

Replace the `### View Mode (Full / Lite)` section's five bullets with:

```markdown
### View mode: density and layout

- Two independent axes. **Density** (`stores/viewMode.js`, `'lite' | 'full'`)
  is a user preference, defaults to `'lite'`, persisted in `localStorage`.
  **Layout** (`stores/layout.js`, `'desktop' | 'phone'`) is a device fact
  from `matchMedia('(max-width: 720px)')`. Nothing infers one from the other.
- Mode-dependent behaviour lives in four seams only: `<FullOnly>` for
  sections, `$derived` filters for rows/labels, `components/DataTable.svelte`
  for columns (`lite: false` / `phone: false` flags; cards on phone), and the
  app shell. Routes never import either store.
- New list tables use `DataTable`. Editing grids and document line tables
  do not (see the architecture doc §6.2 for the list).
- Lite still fetches full data; toggling density re-renders without a refetch.
- Full reference: `docs/designs/architecture-and-conventions.md` §6.
```

- [ ] **Step 4: Note the new tests in the testing doc and close the spec's status**

Append to the "## Coverage status" section of `docs/designs/frontend-testing.md`:

```markdown
- View-mode seams (2026-10): `tests/stores/layout.test.js` (matchMedia
  fakes via `vi.resetModules` + dynamic import), `tests/components/DataTable.test.js`
  (snippet columns via `_DataTableHarness.svelte`; `layout` store mocked as
  a writable), and a lite-vs-full header assertion in every migrated list's
  test (pattern: `tests/components/contacts/ContactListPage.test.js`, QBO
  children stubbed with `_Noop.svelte`; `tests/routes/Search.test.js`).
```

In `docs/plans/2026-10-08-view-mode-seams.md`, replace the `Status:` paragraph with:

```markdown
Status: MECHANISM + CONSOLIDATION SHIPPED on `feature/lite-view` (2026-10,
plan: `docs/plans/2026-10-09-view-mode-seams-plan.md`) — §3–§6 steps 1–5
are built and documented in `docs/designs/architecture-and-conventions.md`
§6. §7 (lite-view inventory) is RM's to fill; it revises the conservative
first-cut lite flags recorded in the batch commit messages. §6 step 6 (phone
shell) is a separate spec.
```

- [ ] **Step 5: Check the docs read correctly**

```bash
grep -n "^## 6\|^### 6\.\|^## 7" docs/designs/architecture-and-conventions.md
grep -n "Lite-mode rollout" docs/designs/architecture-and-conventions.md
```

Expected: §6 with 6.1–6.4 followed directly by `## 7. History and notes`; the second grep prints nothing.

- [ ] **Step 6: Commit**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git add docs/designs/architecture-and-conventions.md frontend/README.md docs/designs/frontend-testing.md docs/plans/2026-10-08-view-mode-seams.md docs/designs/LATER.md
git commit -m "docs: view mode as two axes (density/layout) and four seams; list consolidation recorded

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Final verification (after Task 8)

- [ ] From `frontend/`: `npm run test:run` — read the summary line; all pass.
- [ ] From `frontend/`: `npm run build` — no errors, no unused-selector warnings introduced by a migration (a warning means a snippet lost its scoped style — investigate, don't delete the rule).
- [ ] From `e2e/`: `npx playwright test` — all pass (one run, serial).
- [ ] `grep -rn "viewMode\|stores/layout" frontend/src/routes` prints nothing (routes never import the stores).
- [ ] `grep -rln "<table" frontend/src` lists only the do-not-migrate files from Task 6 plus `DataTable.svelte`.
- [ ] `git log --oneline main..feature/lite-view` shows the spec + plan commits plus one commit per task/batch, all on `feature/lite-view`.
- [ ] Do **not** merge, push, or open a PR. Report done and ready for RM's browser review (RM reviews the running app and often adjusts before merging).
