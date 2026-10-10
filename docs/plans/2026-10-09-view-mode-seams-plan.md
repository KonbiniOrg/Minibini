# View-mode Seams Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the lite/full density and desktop/phone layout plumbing in place (a `layout` store, a declarative `DataTable`, one converted list page, docs) so UI work can proceed on both tracks without parallel pages or scattered `{#if}`s.

**Architecture:** Two independent Svelte stores (`viewMode` exists; `layout` is new, from `matchMedia`) are consumed only at four seams: `<FullOnly>` for sections (exists), `$derived` filters for rows, a new `components/DataTable.svelte` for columns, and the app shell (out of scope here). `DataTable` takes columns as data with `lite`/`phone` flags and renders a `<table>` on desktop or stacked cards on phone. The contacts & businesses list is the pilot conversion.

**Tech Stack:** Svelte 5 (runes + snippets), Vitest + @testing-library/svelte (jsdom), Playwright e2e, plain CSS in `frontend/src/css/app.css`.

**Spec:** `docs/plans/2026-10-08-view-mode-seams.md` (§3 two axes, §4 four seams, §5 conventions, §6 rollout steps 1–4). This plan implements rollout steps 1–4; steps 5–6 are later work.

**Branch:** all commits go on `feature/lite-view` (already checked out). Do not create a new branch.

## Global Constraints

- Density store values are exactly `'lite'` and `'full'` (spec §3); layout store values are exactly `'desktop'` and `'phone'`.
- Phone breakpoint: `max-width: 720px`, one exported constant `PHONE_MAX_WIDTH = 720` (spec §3).
- Nothing reads `layout` to infer density or `viewMode` to infer layout (spec §3).
- `routes/*.svelte` never import `viewMode` or `layout` (spec §5).
- Density hides noise, never rights: permission gating stays on the permission stores and is applied before density filtering (spec §5).
- Every `<tr>` lives inside `<thead>`/`<tbody>` (CLAUDE.md "Table markup").
- Front-end tests: Vitest in `frontend/tests/`, run `npm run test:run` from `frontend/` — never watch mode. E2E: `npx playwright test` from `e2e/`. No Django tests are involved in this plan (no backend changes).
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Never push, merge, or open a PR.
- The dev DB is never written to. This plan has no DB-touching steps; the e2e suite uses its own `minibini_e2e` DB.

## Review Focus

1. **`matchMedia` missing** (jsdom, very old browsers): `layout` must stay `'desktop'` and must not throw at import or subscribe. → Task 1 test "stays desktop when matchMedia is unavailable".
2. **Media query flips at runtime** (rotate a tablet, resize a window): the store must follow the `change` event in both directions. → Task 1 test "follows change events".
3. **Axes are independent**: phone + full must hide `phone: false` columns while showing `lite: false` ones. → Task 2 test "phone layout in full density".
4. **Toggle while mounted**: switching density after the table rendered must add/remove columns reactively, not only on mount. → Task 2 test "reacts to a density change after mount".
5. **Row key collisions in the pilot**: contacts and businesses share numeric ids (a contact 1 and a business 1 are both real). The pilot's `key` must combine type and id. → Task 3 test "renders a contact and a business that share an id".

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

### Task 3: Pilot — convert the Contacts & Businesses list to `DataTable`

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
Expected: the two "shares an id" / "links the name" tests may pass against the old table; the lite/full header tests FAIL (headers are always all six, and `data-col` attributes don't exist yet). Confirm at least "in lite density hides the Type and Tags columns" fails.

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

Note the `{:else if filteredItems.length === 0}` branch is removed on purpose: when `filteredItems` is empty so is `pageItems`, and `DataTable` renders the same "No results found." text.

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

Pilot conversion for the view-mode column seam. Column flags are a
starting point pending the lite-view inventory (spec §7).

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: E2E — lite hides columns, FULL toggle restores them

**Files:**
- Create: `e2e/specs/contacts/lite-view-columns.spec.js`

**Interfaces:**
- Consumes: the converted contacts list (Task 3), the sidebar `LITE | FULL` toggle (`components/Sidebar.svelte`, a `<button>` named `FULL` when lite is active), persona `worker` from `e2e/fixtures/personas.js`.
- Produces: nothing.

There is no `docs/ui-flows/` doc for view mode yet, so test titles describe the behaviour directly instead of citing a § number.

- [ ] **Step 1: Write the spec**

`e2e/specs/contacts/lite-view-columns.spec.js`:

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
    // Rows are still there (no refetch / no flash to empty).
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
Expected: 1 passed. (The suite starts its own servers on 8100/9100 and rebuilds `minibini_e2e`; the dev stack can stay up. If it fails on the `FULL` button not being found, the sidebar did not open — check that `.sidebar` is the pull-out's root class in `Sidebar.svelte` and adjust the locator, not the app.)

- [ ] **Step 3: Run the full e2e suite once**

Run from `e2e/`: `npx playwright test`
Expected: all passed. In particular `specs/contacts/import-skip-report.spec.js` still passes — it looks up `getByRole('link', { name: 'Zenith Imports E2E' })` in the list, which the `nameCell` snippet still renders as a link.

- [ ] **Step 4: Commit**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git add e2e/specs/contacts/lite-view-columns.spec.js
git commit -m "test(e2e): contacts list hides Type/Tags in lite, FULL toggle restores

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Documentation — two axes, four seams

**Files:**
- Modify: `docs/designs/architecture-and-conventions.md` — §6 "View mode (full / lite)" (lines ~1199–1256) and the "Lite-mode rollout" bullet in §10 (lines ~1917–1921)
- Modify: `frontend/README.md` — "### View Mode (Full / Lite)" section (lines ~424–430)
- Modify: `docs/designs/frontend-testing.md` — "## Coverage status" (append one line)
- Modify: `docs/plans/2026-10-08-view-mode-seams.md` — Status line

**Interfaces:** none (prose only).

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
  first, and density only trims what remains.
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
3. **Columns — `components/DataTable.svelte`.** Columns are declared as
   data: `{ id, label, liteLabel?, field?, cell?, lite?, phone?, align? }`.
   `lite: false` hides a column in lite density; `phone: false` hides it in
   phone layout. `cell` is a Svelte 5 snippet `(row) => markup` for links,
   badges and buttons; `field` renders `row[field]` as text. On phone the
   same visible columns render as one `<dl>` card per row
   (`.data-cards` / `.data-card` in `app.css`) instead of a `<table>`.
   Props: `rows`, `columns`, `key` (`(row, i) => key`), `emptyText`,
   `class`. Pilot consumer: `routes/contacts/ContactListPage.svelte`.
   `LineItemTable.svelte` is deliberately not on `DataTable` (footers,
   adjustments, edit affordances).
4. **Shell — `App.svelte`.** The one place a *parallel component* is
   legitimate: on phone layout the shell may mount a drawer nav instead of
   `Sidebar.svelte` and make modals full-screen. Not built yet.

Anti-patterns: wrapping a single `<th>` in `<FullOnly>` (use a column
flag); wrapping a single row (use a `$derived` filter); hiding fetched,
data-heavy content with `display: none`.

### 6.3 Toggle location

The density toggle lives at the bottom of the sidebar
(`components/Sidebar.svelte`, `LITE | FULL`) and in the profile panel
(`home/ProfilePanel.svelte`). Consolidating to one home is an open
question. There is no layout toggle: layout is a device fact.

### 6.4 Rollout state

Done (2026-10, `feature/lite-view`): both stores, `DataTable`, the
contacts list pilot. Remaining: migrate list tables as pages are touched
(`JobList`, `InvoiceListPage`, `PurchaseOrderList`, `ExpenseListPage`,
`CatalogInventoryPage`, `UserListPage`, `Search`, then detail-page tables),
the phone shell, and the per-page lite inventory (spec §7) that decides
which columns and sections lite actually hides.

---
```

- [ ] **Step 2: Replace the §10 "Lite-mode rollout" bullet**

Replace the bullet that begins `- **Lite-mode rollout** (deferred pending user feedback).` (four lines) with:

```markdown
- **View-mode rollout.** Plumbing is in (§6). Remaining: migrate the other
  list tables onto `DataTable` as pages are touched, build the phone shell,
  fill the per-page lite inventory (`docs/plans/2026-10-08-view-mode-seams.md`
  §7), consolidate the density toggle to one home, and persist density
  server-side per user.
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
- Lite still fetches full data; toggling density re-renders without a refetch.
- Full reference: `docs/designs/architecture-and-conventions.md` §6.
```

- [ ] **Step 4: Note the new tests in the testing doc and close the spec's status**

Append to the "## Coverage status" section of `docs/designs/frontend-testing.md`:

```markdown
- View-mode seams (2026-10): `tests/stores/layout.test.js` (matchMedia
  fakes via `vi.resetModules` + dynamic import), `tests/components/DataTable.test.js`
  (snippet columns via `_DataTableHarness.svelte`; `layout` store mocked as
  a writable), `tests/components/contacts/ContactListPage.test.js` (QBO
  children stubbed with `_Noop.svelte`).
```

In `docs/plans/2026-10-08-view-mode-seams.md`, replace the `Status:` paragraph with:

```markdown
Status: MECHANISM SHIPPED on `feature/lite-view` (2026-10, plan:
`docs/plans/2026-10-09-view-mode-seams-plan.md`) — §3–§6 steps 1–4 are
built and documented in `docs/designs/architecture-and-conventions.md` §6.
§7 (lite-view inventory) is RM's to fill; it drives the remaining rollout
(spec §6 steps 5–6) and may revise the pilot's column flags.
```

- [ ] **Step 5: Check the docs read correctly**

Run from the repo root:

```bash
grep -n "^## 6\|^### 6\.\|^## 7" docs/designs/architecture-and-conventions.md
grep -n "Lite-mode rollout" docs/designs/architecture-and-conventions.md
```

Expected: §6 with 6.1–6.4 followed directly by `## 7. History and notes`; the second grep prints nothing.

- [ ] **Step 6: Commit**

```bash
cd /Users/drshiny/Documents/konbini/Minibini
git add docs/designs/architecture-and-conventions.md frontend/README.md docs/designs/frontend-testing.md docs/plans/2026-10-08-view-mode-seams.md
git commit -m "docs: view mode as two axes (density/layout) and four seams

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Final verification (after Task 5)

- [ ] From `frontend/`: `npm run test:run` — read the summary line; all pass.
- [ ] From `frontend/`: `npm run build` — no errors.
- [ ] From `e2e/`: `npx playwright test` — all pass (one run, serial).
- [ ] `git log --oneline main..feature/lite-view` shows the spec commit plus five task commits, all on `feature/lite-view`.
- [ ] Do **not** merge, push, or open a PR. Report done and ready for RM's browser review (RM reviews the running app and often adjusts before merging).
