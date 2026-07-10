# Job Workspace Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the job pages from hub-and-spoke to a workspace: a shared job shell (header + collapsible context band + nav rail) hosting one section panel per page, with URL-per-document subnavigation and wizard-as-mode — per `docs/plans/2026-07-08-job-workspace-restructure-design.md` (steps 1–3; the overview rework, step 4, is a separate later design conversation).

**Architecture:** Extract each route page's guts into a section panel component that owns its own data loading; route pages collapse to glue (resolve job → shell → panel). A single localStorage store remembers per-job position (selected document, per-document mode, band state); URLs stay the source of truth for what's displayed. Old document routes become redirect shims.

**Tech Stack:** Svelte 5 (runes), svelte-spa-router (hash routing), Vitest + testing-library, Django/DRF backend (one small serializer removal at the end).

## Global Constraints

- **Branch: `feature/job-overview`** — all commits land here. Never merge/push/PR.
- **NEVER write to the dev DB** (no `migrate`, no ORM writes outside `manage.py test`, no loaddata). Read-only SQL is OK.
- Frontend tests: run from `frontend/` ONLY (`npm run test:run`, or `npx vitest run <path>`); running from repo root creates a stray `node_modules/`.
- Backend tests: only one runner at a time; never judge by piped exit codes — read the `OK` / `FAILED (…)` summary line.
- TDD: failing test first for every behavior change. Svelte 5 strict mode: `<tr>` must sit inside `<tbody>`/`<thead>`.
- Permission gating: always `job.can_manage` / `doc.can_manage` (per-object), never the global atom store, except where a page already uses `$canManageFinancials` (invoices) — preserve existing gating exactly during extraction.
- Errors: `triageError`/`errorMessage` venues per the error contract; DELETEs return 200 JSON.
- Shared chrome goes in `app.css` — never copy CSS between components (architecture doc §5.5).
- Band default: **expanded**; collapses on click; state persists per job. Collapsed band fetches nothing.
- Email section v1 = existing `EmailPanel` surface at full width. NO thread-view redesign.
- The overview keeps its pillars/midband untouched (step 4 later); it only gains the rail.
- ChangeOrderDetailPage stays a standalone route this pass (reached from the estimate subnav).
- After every task: `npm run test:run` green (from `frontend/`), then commit with the given message + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Verified current facts (2026-07-08, feature/job-overview @ f2ee3845)

- Routes (`frontend/src/App.svelte:76-122`): `/jobs/:id`, `/jobs/:id/edit`, `/jobs/:id/duplicate`, `/jobs/:id/tasklist`, `/jobs/:id/history`, `/jobs/:jobId/shipments`, `/jobs/:jobId/tasks/:taskId`, `/estimates/:id[/wizard|/send]`, `/invoices/:id[/wizard|/send]`, `/change-orders/:id[/send]`, `/purchase-orders/…`.
- `?job=` list filters exist for estimates, invoices, purchase-orders, emails, expenses (JobDetailPage already calls all of them — `routes/jobs/JobDetailPage.svelte:21-28`).
- `JobNavRail.svelte` (77 ln): `{ job, current }` props, `job.nav_targets`-driven hrefs, `‹ Overview` chevron, dimmed empties. Test: `frontend/tests/components/jobs/JobNavRail.test.js`.
- `JobHeader.svelte` (382 ln): fixed 110px; Actions ▾ menu (Edit/Duplicate…/History links); trigger status pill (`__hold`/`__release_hold`); hold modal is a `Modal.svelte` dialog inside the component; `onStatusChange` callback prop.
- `nav_targets`: `apps/api/jobs/serializers.py:63,76,126`; tests `tests/test_api_job_nav_targets.py`; query pin **18** in `tests/test_api_jobs.py::test_job_detail_invoice_claims_single_query`.
- Persistence pattern: `stores/viewMode.js` (writable + localStorage).
- Existing name collision: `components/HistoryPanel.svelte` is the generic timeline — the job section component must be named `JobHistorySection`.
- Wizard pages: `EstimateWizardPage.svelte` (224 ln), `InvoiceWizardPage.svelte` (243 ln) — near-parallel structure (WizardSourcePool + WizardLineItemCard + WizardActions).

---

### Task 1: `jobWorkspace` store (per-job persisted position)

**Files:**
- Create: `frontend/src/stores/jobWorkspace.js`
- Test: `frontend/tests/stores/jobWorkspace.test.js`

**Interfaces (Produces):**
```js
// All jobId/docId coerced to String internally.
export function getJobWs(jobId)
// -> { band: 'expanded'|'collapsed', sections: {estimate?, invoice?}, modes: {[docId]: 'lines'|'reconcile'} }
export function rememberSection(jobId, section, docId)   // section: 'estimate'|'invoice'
export function rememberMode(jobId, docId, mode)         // 'lines'|'reconcile'
export function rememberBand(jobId, state)               // 'expanded'|'collapsed'
export const JOB_WS_KEY = 'minibini_job_ws';             // single localStorage key
```
LRU-capped at 50 jobs: the stored value is `{ order: [jobId…most-recent-last], jobs: { [jobId]: state } }`; every write moves the job to the end of `order` and evicts from the front past 50.

- [ ] **Step 1: Write the failing tests**

```js
// frontend/tests/stores/jobWorkspace.test.js
import { describe, it, expect, beforeEach } from 'vitest';
import {
  getJobWs, rememberSection, rememberMode, rememberBand, JOB_WS_KEY,
} from '@/stores/jobWorkspace.js';

beforeEach(() => localStorage.removeItem(JOB_WS_KEY));

describe('jobWorkspace store', () => {
  it('returns defaults for an unknown job: expanded band, no selections', () => {
    expect(getJobWs(7)).toEqual({ band: 'expanded', sections: {}, modes: {} });
  });

  it('remembers the selected document per section per job', () => {
    rememberSection(7, 'estimate', 31);
    rememberSection(7, 'invoice', 12);
    rememberSection(8, 'estimate', 99);
    expect(getJobWs(7).sections).toEqual({ estimate: '31', invoice: '12' });
    expect(getJobWs(8).sections).toEqual({ estimate: '99' });
  });

  it('remembers per-DOCUMENT mode, not per-section', () => {
    rememberMode(7, 31, 'reconcile');
    rememberMode(7, 32, 'lines');
    expect(getJobWs(7).modes['31']).toBe('reconcile');
    expect(getJobWs(7).modes['32']).toBe('lines');
  });

  it('remembers band collapse per job and survives a reload (re-read from storage)', () => {
    rememberBand(7, 'collapsed');
    const raw = JSON.parse(localStorage.getItem(JOB_WS_KEY));
    expect(raw.jobs['7'].band).toBe('collapsed');
    expect(getJobWs(7).band).toBe('collapsed');
  });

  it('evicts least-recently-used jobs past 50', () => {
    for (let i = 1; i <= 51; i++) rememberBand(i, 'collapsed');
    expect(getJobWs(1)).toEqual({ band: 'expanded', sections: {}, modes: {} }); // evicted
    expect(getJobWs(51).band).toBe('collapsed');
    const raw = JSON.parse(localStorage.getItem(JOB_WS_KEY));
    expect(raw.order).toHaveLength(50);
  });

  it('touching an old job refreshes its LRU position', () => {
    for (let i = 1; i <= 50; i++) rememberBand(i, 'collapsed');
    rememberSection(1, 'estimate', 5); // touch job 1
    rememberBand(51, 'collapsed');     // evicts job 2, not job 1
    expect(getJobWs(1).sections.estimate).toBe('5');
    expect(getJobWs(2)).toEqual({ band: 'expanded', sections: {}, modes: {} });
  });

  it('tolerates corrupt storage', () => {
    localStorage.setItem(JOB_WS_KEY, '{not json');
    expect(getJobWs(7)).toEqual({ band: 'expanded', sections: {}, modes: {} });
  });
});
```

- [ ] **Step 2: Run to verify failure** — `cd frontend && npx vitest run tests/stores/jobWorkspace.test.js` → FAIL (module not found).

- [ ] **Step 3: Implement**

```js
// frontend/src/stores/jobWorkspace.js
// Per-job workspace position: which document each section last showed, each
// document's lines/reconcile mode, and the context band's collapse state.
// ONE localStorage key holding an LRU-capped map (retention stays trivial).
// URLs are the source of truth for what's displayed; this store only answers
// "where did I leave off?" when a bare section route or the band mounts.
export const JOB_WS_KEY = 'minibini_job_ws';
const MAX_JOBS = 50;
const DEFAULTS = () => ({ band: 'expanded', sections: {}, modes: {} });

function readAll() {
  try {
    const raw = JSON.parse(localStorage.getItem(JOB_WS_KEY));
    if (raw && Array.isArray(raw.order) && raw.jobs) return raw;
  } catch (e) { /* corrupt → start over */ }
  return { order: [], jobs: {} };
}

function writeJob(jobId, patch) {
  const id = String(jobId);
  const all = readAll();
  const state = { ...DEFAULTS(), ...(all.jobs[id] || {}) };
  const next = { ...state, ...patch };
  all.jobs[id] = next;
  all.order = all.order.filter((j) => j !== id);
  all.order.push(id);
  while (all.order.length > MAX_JOBS) {
    delete all.jobs[all.order.shift()];
  }
  localStorage.setItem(JOB_WS_KEY, JSON.stringify(all));
}

export function getJobWs(jobId) {
  const entry = readAll().jobs[String(jobId)];
  return { ...DEFAULTS(), ...(entry || {}) };
}

export function rememberSection(jobId, section, docId) {
  const { sections } = getJobWs(jobId);
  writeJob(jobId, { sections: { ...sections, [section]: String(docId) } });
}

export function rememberMode(jobId, docId, mode) {
  const { modes } = getJobWs(jobId);
  writeJob(jobId, { modes: { ...modes, [String(docId)]: mode } });
}

export function rememberBand(jobId, state) {
  writeJob(jobId, { band: state });
}
```

- [ ] **Step 4: Run to verify pass** — same command → 7 passed.
- [ ] **Step 5: Commit** — `feat(ui): jobWorkspace store — per-job persisted position (LRU, one key)`

---

### Task 2: `JobContextBand` — collapsible description/deliverables/email band

**Files:**
- Create: `frontend/src/components/jobs/JobContextBand.svelte`
- Test: `frontend/tests/components/jobs/JobContextBand.test.js`

**Interfaces:**
- Consumes: `getJobWs`/`rememberBand` (Task 1); existing `DeliverablesSection.svelte`, `EmailPanel.svelte` (props `{ emails }`).
- Produces: `<JobContextBand {job} />` — self-contained: reads/persists its own collapse state; **fetches deliverables/emails only while expanded** (`/api/emails/?job=`; DeliverablesSection loads its own data given `jobId`). Description comes from the `job` payload (no fetch).

Markup shape (all styles via new `app.css` additions under the banner-page kit — `.context-band`, `.context-band-grid`, `.context-band-toggle`; promote, don't scope):

```svelte
<script>
  import { api } from '../../lib/api.js';
  import { getJobWs, rememberBand } from '../../stores/jobWorkspace.js';
  import DeliverablesSection from './DeliverablesSection.svelte';
  import EmailPanel from '../EmailPanel.svelte';

  let { job } = $props();
  let expanded = $state(getJobWs(job.job_id).band === 'expanded');
  let emails = $state(null);

  // Collapsed band fetches NOTHING (design review note 2). Load on expand.
  $effect(() => {
    if (expanded && emails === null && job?.job_id) {
      api.get(`/api/emails/?job=${job.job_id}`)
        .then((r) => { emails = r; })
        .catch(() => { emails = { results: [] }; });
    }
  });

  function toggle() {
    expanded = !expanded;
    rememberBand(job.job_id, expanded ? 'expanded' : 'collapsed');
  }
</script>

<div class="context-band" class:collapsed={!expanded}>
  <button type="button" class="context-band-toggle" onclick={toggle}
          aria-expanded={expanded}>
    {expanded ? '▾ Hide job context' : '▸ Job context'}
  </button>
  {#if expanded}
    <div class="context-band-grid">
      <div class="panel">
        <div class="panel-head">Description</div>
        <div class="panel-scroll preserve-breaks">{job.description || '—'}</div>
      </div>
      <DeliverablesSection jobId={job.job_id} canManage={job.can_manage} />
      <EmailPanel {emails} />
    </div>
  {/if}
</div>
```
(Check `DeliverablesSection`'s actual props before wiring — it currently mounts on JobDetail; match its real signature. If it takes preloaded data instead of `jobId`, keep its loading where it is today and pass through.)

- [ ] **Step 1: Failing tests** — render with `{ job: { job_id: 3, description: 'Big build', can_manage: false } }`, mock `api.get`:
```js
// frontend/tests/components/jobs/JobContextBand.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn().mockResolvedValue({ results: [] }) },
  errorMessage: (e, f) => f }));
import { api } from '@/lib/api.js';
import { JOB_WS_KEY } from '@/stores/jobWorkspace.js';
import JobContextBand from '@/components/jobs/JobContextBand.svelte';

beforeEach(() => { localStorage.removeItem(JOB_WS_KEY); api.get.mockClear(); });

const job = { job_id: 3, description: 'Big build', can_manage: false };

describe('JobContextBand', () => {
  it('starts expanded by default and shows the description', async () => {
    const { getByText } = render(JobContextBand, { props: { job } });
    expect(getByText('Big build')).toBeInTheDocument();
  });

  it('fetches emails only while expanded', async () => {
    render(JobContextBand, { props: { job } });
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/emails/?job=3'));
  });

  it('collapse hides content, persists, and a fresh mount stays collapsed without fetching', async () => {
    const first = render(JobContextBand, { props: { job } });
    await fireEvent.click(first.getByRole('button', { name: /hide job context/i }));
    expect(first.queryByText('Big build')).toBeNull();
    first.unmount();
    api.get.mockClear();
    const second = render(JobContextBand, { props: { job } });
    expect(second.queryByText('Big build')).toBeNull();
    expect(api.get).not.toHaveBeenCalled();
  });
});
```
- [ ] **Step 2: Verify FAIL** (component missing).
- [ ] **Step 3: Implement** component (above) + `app.css` additions (banner-page kit section): `.context-band` (background `#fafafa`, border-bottom `1px solid var(--border-subtle)`), `.context-band-toggle` (quiet small button, no border, `padding: 4px 20px`, `color:#475569`), `.context-band-grid { display:grid; grid-template-columns: 1fr 1fr 320px; gap: 12px; padding: 0 20px 12px; }`.
- [ ] **Step 4: Verify PASS**, run full suite.
- [ ] **Step 5: Commit** — `feat(ui): JobContextBand — collapsible, persisted, lazy-loading job context`

---

### Task 3: `JobShell` — one layout for every job page

**Files:**
- Create: `frontend/src/components/jobs/JobShell.svelte`
- Test: `frontend/tests/components/jobs/JobShell.test.js`

**Interfaces:**
- Consumes: `JobHeader` (`{ job, contact, onStatusChange }`), `JobNavRail` (`{ job, current }`), `JobContextBand` (`{ job }`).
- Produces: `<JobShell {job} {contact} current="shipments" onJobChange={fn} showBand={true}>{panel snippet}</JobShell>`. `showBand={false}` is for the overview (keeps its own midband until step 4). Children render below the rail, full width (panels wrap themselves in `.page-body` as needed).

```svelte
<script>
  import JobHeader from './JobHeader.svelte';
  import JobNavRail from './JobNavRail.svelte';
  import JobContextBand from './JobContextBand.svelte';
  let { job, contact = null, current = null, onJobChange = () => {}, showBand = true, children } = $props();
</script>

{#if job}
  <JobHeader {job} {contact} onStatusChange={onJobChange} />
  <JobNavRail {job} {current} />
  {#if showBand}<JobContextBand {job} />{/if}
{/if}
{@render children?.()}
```

- [ ] **Step 1: Failing test** — renders header title, rail, band, and the child snippet; `showBand={false}` omits the band:
```js
// frontend/tests/components/jobs/JobShell.test.js
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn().mockResolvedValue({ results: [] }) },
  errorMessage: (e, f) => f }));
import JobShell from '@/components/jobs/JobShell.svelte';

const job = { job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress', description: 'D' };
const body = createRawSnippet(() => ({ render: () => '<p>PANEL BODY</p>' }));

describe('JobShell', () => {
  it('stacks header, rail, band, and the hosted panel', () => {
    const { getByText, container } = render(JobShell, { props: { job, current: 'shipments', children: body } });
    expect(getByText(/JOB #3/)).toBeInTheDocument();
    expect(container.querySelector('.job-nav-rail')).toBeInTheDocument();
    expect(container.querySelector('.context-band')).toBeInTheDocument();
    expect(getByText('PANEL BODY')).toBeInTheDocument();
  });

  it('showBand={false} omits the context band (overview keeps its midband)', () => {
    const { container } = render(JobShell, { props: { job, showBand: false, children: body } });
    expect(container.querySelector('.context-band')).toBeNull();
  });
});
```
- [ ] **Step 2: FAIL** → **Step 3: implement** → **Step 4: PASS + full suite** → **Step 5: Commit** — `feat(ui): JobShell — header + rail + context band layout for job pages`

---

### Task 4: ShipmentsPanel (pattern prover) + section route through the shell

**Files:**
- Create: `frontend/src/components/shipments/ShipmentsPanel.svelte` (move the guts of `routes/jobs/JobShipmentsPage.svelte` — everything below its JobHeader mount: matrix, drafts, actions, modals, styles)
- Modify: `frontend/src/routes/jobs/JobShipmentsPage.svelte` → glue (fetch job+contact, render `JobShell` + panel)
- Test: move/adapt `frontend/tests/components/jobs/JobShipmentsPage.test.js` assertions to `frontend/tests/components/shipments/ShipmentsPanel.test.js`; keep a thin route test that the page mounts shell + panel.

**Interfaces:**
- Produces: `<ShipmentsPanel {job} onJobChange={fn} />` — owns all shipment/deliverable fetching it does today (everything keyed off `job.job_id`); calls `onJobChange()` after mutations that alter job-level rollups.
- Glue page pattern **every later section task copies**:

```svelte
<!-- routes/jobs/JobShipmentsPage.svelte (after) -->
<script>
  import { api } from '../../lib/api.js';
  import JobShell from '../../components/jobs/JobShell.svelte';
  import ShipmentsPanel from '../../components/shipments/ShipmentsPanel.svelte';
  let { params = {} } = $props();
  let job = $state(null);
  let contact = $state(null);
  let error = $state('');
  async function loadJob() {
    try {
      job = await api.get(`/api/jobs/${params.jobId}/`);
      contact = job?.contact ? await api.get(`/api/contacts/${job.contact}/`).catch(() => null) : null;
    } catch (e) { error = e.message || 'Could not load job.'; }
  }
  $effect(() => { if (params.jobId) loadJob(); });
</script>

{#if error}<p class="error">{error}</p>
{:else if job}
  <JobShell {job} {contact} current="shipments" onJobChange={loadJob}>
    <ShipmentsPanel {job} onJobChange={loadJob} />
  </JobShell>
{:else}<p>Loading…</p>{/if}
```

- [ ] **Step 1:** Write the panel test first (adapt the page test's existing assertions to mount `ShipmentsPanel` with a `job` prop and the same api mocks; the behaviors under test are unchanged). Run → FAIL (component missing).
- [ ] **Step 2:** Move the page's content into the panel: the `<script>` block minus job/contact loading (panel receives `job`), the markup minus JobHeader, all styles. The panel's own data loads key off `job.job_id` in an `$effect`.
- [ ] **Step 3:** Rewrite the route page as the glue above. Route path is unchanged (`/jobs/:jobId/shipments`).
- [ ] **Step 4:** Update the old page test to assert glue behavior only (shell renders, panel present). Run both tests + full suite → PASS.
- [ ] **Step 5: Commit** — `refactor(ui): extract ShipmentsPanel; shipments page becomes shell glue`

---

### Task 5: TasksPanel + `/jobs/:jobId/tasks` (+ tasklist shim) + task detail through the shell

**Files:**
- Create: `frontend/src/components/tasks/TasksPanel.svelte` (guts of `JobTaskListPage.svelte`)
- Modify: `routes/jobs/JobTaskListPage.svelte` → glue; `App.svelte` route table; `routes/jobs/TaskDetailPage.svelte` (swap its `JobHeader` mount for `JobShell current="tasks"`, keep EVERYTHING else — it is on the §5.5a skip-list)
- Test: adapt `JobTaskListPage.test.js` → `frontend/tests/components/tasks/TasksPanel.test.js`; TaskDetailPage tests must keep passing unmodified except the mount context.

**Route changes in `App.svelte`:**
```js
'/jobs/:jobId/tasks': JobTaskListPage,        // new canonical (register BEFORE the :taskId route)
'/jobs/:jobId/tasks/:taskId': TaskDetailPage, // unchanged
'/jobs/:id/tasklist': JobTaskListPage,        // legacy alias — keep, cheap
```
(The glue must read `params.jobId ?? params.id` so both routes work.)

**Interfaces:** `<TasksPanel {job} onJobChange={fn} />`.

- [ ] Steps mirror Task 4 exactly (panel test first → move → glue → route additions → suite green).
- [ ] TaskDetailPage: replace its `{#if job}<JobHeader …/>{/if}` block with `JobShell` (`showBand` default true; `current="tasks"`). Its `loading` gate and all loaders stay byte-identical. Its regression tests ("no page blank on broadcast", "fetch count stabilizes") must pass untouched.
- [ ] **Commit** — `refactor(ui): TasksPanel + /jobs/:id/tasks; task detail renders through the shell`

---

### Task 6: DocSubnav (shared) — the panel's document strip

**Files:**
- Create: `frontend/src/components/jobs/DocSubnav.svelte`
- Test: `frontend/tests/components/jobs/DocSubnav.test.js`

**Interfaces:**
- Produces: `<DocSubnav items={[{id, label, status, href, current}]} />` — pure presentational strip of document links (URL-per-document: items are `<a href>`, never buttons). `current` item gets the active underline. Renders a `status-badge status-{status}`-classed mini pill per item when `status` given.

```svelte
<script>
  let { items = [] } = $props();
</script>
<nav class="doc-subnav" aria-label="Documents">
  {#each items as it (it.id)}
    <a href={it.href} class="doc-subnav-link" class:active={it.current}>
      {it.label}
      {#if it.status}<span class="status-badge doc-subnav-pill status-{it.status}">{it.status}</span>{/if}
    </a>
  {/each}
</nav>
```
`app.css` (banner-page kit): `.doc-subnav { display:flex; gap:14px; padding:6px 0; flex-wrap:wrap; }`, `.doc-subnav-link { font-size:13px; color:#475569; text-decoration:none; border-bottom:2px solid transparent; }`, `.doc-subnav-link.active { color:#111827; border-bottom-color:#111827; }`, `.doc-subnav-pill { font-size:10px; padding:1px 8px; margin-left:4px; }`.

- [ ] **Step 1: Failing test** (renders links with hrefs, marks active, shows status pills) → **Step 2: FAIL** → **Step 3: implement** → **Step 4: PASS** → **Step 5: Commit** — `feat(ui): DocSubnav — shared document strip for section panels`

---

### Task 7: EstimatePanel + `/jobs/:jobId/estimate[/:docId]` + `/estimates/:id` shim

**Files:**
- Create: `frontend/src/components/estimates/EstimatePanel.svelte` (guts of `EstimateDetailPage.svelte`: everything below JobHeader/JobNavRail — toolbar, status select, line items, modals, styles)
- Create: `frontend/src/routes/jobs/JobEstimatePage.svelte` (glue + document resolution)
- Modify: `routes/estimates/EstimateDetailPage.svelte` → **redirect shim**; `App.svelte`
- Test: adapt existing estimate page tests → `frontend/tests/components/estimates/EstimatePanel.test.js`; new `frontend/tests/routes/JobEstimatePage.test.js`

**Interfaces:**
- `<EstimatePanel {job} estimateId onJobChange />` — fetches its own estimate by id; renders `DocSubnav` at top built from `/api/estimates/?job=` (all versions, `label: 'v' + version`, `status`) **plus the job's COs** (from the estimates' `change_orders`/CO list the page already knows how to fetch — CO items link to `#/change-orders/{id}`, unchanged this pass).
- Document resolution in the glue page:

```js
// JobEstimatePage.svelte — inside <script>
import { getJobWs, rememberSection } from '../../stores/jobWorkspace.js';
// docId precedence: URL param → remembered → latest version.
const docId = $derived.by(() => {
  if (params.docId) return String(params.docId);
  const remembered = getJobWs(params.jobId).sections.estimate;
  if (remembered && estimates.some((e) => String(e.estimate_id) === remembered)) return remembered;
  return estimates.length ? String(estimates[estimates.length - 1].estimate_id) : null;
});
// Whenever a document renders, remember it AND normalize the URL (replace, no reload):
$effect(() => {
  if (docId && params.jobId) {
    rememberSection(params.jobId, 'estimate', docId);
    const want = `#/jobs/${params.jobId}/estimate/${docId}`;
    if (window.location.hash !== want) window.history.replaceState(null, '', want);
  }
});
```
- **Empty state:** no estimates → panel frame with a `can_manage`-gated "Start Estimate" button (`POST /api/estimates/ {job}` then navigate to the new doc URL — reuse JobDetail's `startEstimate` logic verbatim).
- **Shim** (`EstimateDetailPage.svelte` becomes ~15 lines):

```svelte
<script>
  import { api } from '../../lib/api.js';
  let { params = {} } = $props();
  $effect(() => {
    if (params.id) {
      api.get(`/api/estimates/${params.id}/`)
        .then((est) => window.location.replace(`#/jobs/${est.job}/estimate/${est.estimate_id}`))
        .catch(() => { window.location.replace('#/jobs'); });
    }
  });
</script>
<p>Loading…</p>
```
- Routes: `'/jobs/:jobId/estimate': JobEstimatePage,` `'/jobs/:jobId/estimate/:docId': JobEstimatePage,` (shim keeps `/estimates/:id`).

- [ ] **Step 1:** Panel tests first (adapted from current page tests + new subnav assertions: renders one link per version with hrefs `#/jobs/3/estimate/<id>`, active on the shown doc). FAIL.
- [ ] **Step 2:** Extract panel; glue page with resolution logic above; shim; routes.
- [ ] **Step 3:** Glue-page tests: bare route restores remembered doc; falls back to latest; URL normalizes via replaceState; empty job shows gated Start Estimate. PASS + full suite.
- [ ] **Step 4: Commit** — `feat(ui): EstimatePanel with version subnav; job-scoped estimate routes + shim`

---

### Task 8: InvoicePanel + `/jobs/:jobId/invoice[/:docId]` + `/invoices/:id` shim

Mirror of Task 7 exactly, with:
- Create: `frontend/src/components/invoices/InvoicePanel.svelte`, `frontend/src/routes/jobs/JobInvoicePage.svelte`
- Subnav items: the job's invoices from `/api/invoices/?job=` (`label: invoice_number`, `status`); remembered key `'invoice'`.
- Empty state: `can_manage`-gated "Start Invoice" (`POST /api/invoices/ {job}` — JobDetail's existing logic).
- Gating inside the panel stays `$canManageFinancials` where it is today (constraint: preserve existing gating exactly).
- Shim `InvoiceDetailPage.svelte` → redirect via `est.job` equivalent (`inv.job`).
- [ ] Same step structure; **Commit** — `feat(ui): InvoicePanel with invoice subnav; job-scoped invoice routes + shim`

---

### Task 9: POPanel + `/jobs/:jobId/pos`; Email + History sections

**Files:**
- Create: `frontend/src/components/purchaseorders/POPanel.svelte` — job-filtered PO list: fetch `/api/purchase-orders/?job=${job.job_id}`, render a `.data-table` (PO number → link `#/purchase-orders/{id}`, status pill, vendor, total). Empty state: "No purchase orders touch this job yet." (POs aren't job-owned: no create affordance here — creation stays on the global PO page.)
- Create: `frontend/src/routes/jobs/JobPOsPage.svelte`, `frontend/src/routes/jobs/JobEmailsPage.svelte` (glue pages)
- Create: `frontend/src/components/jobs/JobHistorySection.svelte` (guts of `JobHistoryPage.svelte` — the name avoids the `HistoryPanel.svelte` collision); modify `routes/jobs/JobHistoryPage.svelte` → glue through the shell (route `/jobs/:id/history` unchanged)
- JobEmailsPage: glue + `EmailPanel` full width, fed by `/api/emails/?job=` (v1 scope — no redesign; give it `.page-body` and let it breathe).
- Routes: `'/jobs/:jobId/pos': JobPOsPage,` `'/jobs/:jobId/emails': JobEmailsPage,`
- Tests: `POPanel.test.js` (lists POs, links through, empty state), `JobEmailsPage.test.js` (mounts shell + EmailPanel), adapted history tests.
- [ ] TDD each; **Commit** — `feat(ui): PO, Emails, History sections through the job shell`

---

### Task 10: Rail rework — eight always-valid links

**Files:**
- Modify: `frontend/src/components/jobs/JobNavRail.svelte`, `frontend/src/routes/jobs/JobDetailPage.svelte`
- Test: rewrite `frontend/tests/components/jobs/JobNavRail.test.js`

New sections array (no `nav_targets`, no nulls, no dimming; the chevron dies; Overview is item #1 with an active state and its wider gap; hairline divider before Emails):

```js
let sections = $derived([
  { key: 'overview',  label: 'Overview',  href: `#/jobs/${job.job_id}` },
  { key: 'estimate',  label: 'Estimates', href: `#/jobs/${job.job_id}/estimate` },
  { key: 'tasks',     label: 'Tasks',     href: `#/jobs/${job.job_id}/tasks` },
  { key: 'invoice',   label: 'Invoices',  href: `#/jobs/${job.job_id}/invoice` },
  { key: 'shipments', label: 'Shipments', href: `#/jobs/${job.job_id}/shipments` },
  { key: 'pos',       label: 'POs',       href: `#/jobs/${job.job_id}/pos` },
  { key: 'emails',    label: 'Emails',    href: `#/jobs/${job.job_id}/emails`, seam: true },
  { key: 'history',   label: 'History',   href: `#/jobs/${job.job_id}/history` },
]);
```
Markup: one `{#each}`; `class:active={current === s.key}`; `class:seam` adds `border-left: 1px solid #d1d5db; padding-left: 18px; margin-left: 18px;` (the paper-trail divider); keep Overview visually set apart with `margin-right: 32px` on the first item instead of the old `.rail-overview` block. Delete the `.empty` branch and `nav_targets` read.

- JobDetailPage (overview): render `<JobNavRail {job} current="overview" />` directly under its JobHeader (NOT the shell — overview keeps its midband; `showBand={false}` shell is equivalent but the overview's layout is bespoke Category I; touch it minimally).
- [ ] Rewrite rail tests first (eight links by href, active states, no dimmed spans even on an empty job) → FAIL → implement → PASS → **Commit** — `feat(ui): rail becomes eight always-valid section links; overview joins it`

---

### Task 11: JobHeader — History leaves, Actions dissolves, Edit/Duplicate become modals

**Files:**
- Create: `frontend/src/components/jobs/JobEditModal.svelte` (form extracted from `routes/jobs/JobEditPage.svelte`, hosted in `Modal.svelte`; on save → `onSaved()`), `frontend/src/components/jobs/DuplicateJobModal.svelte` (from `DuplicateJobPage.svelte`)
- Modify: `JobHeader.svelte` (menu → two quiet links opening the modals; History link removed), `App.svelte` (`/jobs/:id/edit` and `/jobs/:id/duplicate` routes → redirect shims to `#/jobs/:id`), delete route page files after extraction
- Test: `JobHeader.test.js` additions (Edit opens modal; no History item), `JobEditModal.test.js` (prefills, PATCHes `/api/jobs/{id}/`, calls `onSaved`)

Header replacement for the menu block:
```svelte
{#if canManageJobs}
  <button type="button" class="edit-link header-action" onclick={() => { editOpen = true; }}>Edit</button>
  <button type="button" class="edit-link header-action" onclick={() => { dupOpen = true; }}>Duplicate…</button>
{/if}
```
(`.header-action` in app.css: `background:none; border:none; cursor:pointer;` so the shared `.edit-link` look applies to buttons. Modals mount as siblings of the hold modal.)

- [ ] TDD: header tests first (History absent; Edit button opens a dialog), modal tests (JobEditPage's existing test assertions move over). Old `/jobs/:id/edit` deep links redirect to the overview. Full suite. **Commit** — `feat(ui): header Edit/Duplicate modals; Actions menu and History link retire`

---

### Task 12: Wizard-as-mode — one ReconcileMode, panel toggle, persistence

**Files:**
- Create: `frontend/src/components/wizards/ReconcileMode.svelte` — parameterized merge of `EstimateWizardPage`/`InvoiceWizardPage` guts. Config-block pattern mirroring backend `BaseWizardService`:

```js
const CONFIGS = {
  estimate: {
    docApi: (id) => `/api/estimates/${id}/`,
    wizardApi: (id, action) => `/api/estimates/${id}/wizard/${action}/`,
    poolComponent: EstimateSourcePool,   // components/estimates/WizardSourcePool.svelte
    label: 'Estimate',
  },
  invoice: {
    docApi: (id) => `/api/invoices/${id}/`,
    wizardApi: (id, action) => `/api/invoices/${id}/wizard/${action}/`,
    poolComponent: InvoiceSourcePool,    // components/invoices/WizardSourcePool.svelte
    extraPanels: [AgreementAdjustmentsPanel],
    label: 'Invoice',
  },
};
```
(Verify the two pages' actual API calls during extraction and encode the *real* differences in the config — the block above is the shape, the values must come from the pages. Both pools stay separate components; the config picks one.)
- Modify: `EstimatePanel.svelte` / `InvoicePanel.svelte` — mode toggle:
  - Toolbar gains `Reconcile` / `Back to lines` button (visible only while the document is **draft** and the user can edit — same gating each wizard page enforces today).
  - `mode` state: initial = `getJobWs(jobId).modes[docId] ?? 'lines'`, **validated: if the doc is not draft, force `'lines'`** (review note 1); every flip calls `rememberMode(jobId, docId, mode)`.
  - `{#if mode === 'reconcile'}<ReconcileMode docType="estimate" docId={estimateId} onChanged={reload} />{:else}…lines view…{/if}`
- Modify: `App.svelte` — `/estimates/:id/wizard` and `/invoices/:id/wizard` become shims: fetch doc → `rememberMode(doc.job, id, 'reconcile')` → `location.replace('#/jobs/{job}/estimate/{id}')`. Delete the two wizard page files after their tests move.
- Test: `ReconcileMode.test.js` (both configs: pool loads, pull/remove calls hit the right endpoints, 409 `atoms_already_claimed` renders per contract — port the existing wizard-page tests), panel-mode tests (toggle persists per doc; sent doc restores to lines even with 'reconcile' remembered).

- [ ] Port wizard tests → FAIL → extract → panels toggle → shims → PASS + full suite.
- [ ] **Commit** — `feat(ui): reconcile mode lives inside the document panels; wizard routes shim in`

---

### Task 13: Retire `nav_targets` (backend)

**Files:**
- Modify: `apps/api/jobs/serializers.py` (drop field lines 63, 76 and `get_nav_targets` at 126), `tests/test_api_jobs.py` (re-pin `test_job_detail_invoice_claims_single_query` from **18** to the new measured count — expected 15; update the pin comment), delete `tests/test_api_job_nav_targets.py`
- Test-first: run the pin test, watch it fail at 18 after the removal, re-pin to the measured number.

- [ ] Remove field → run `python manage.py test tests.test_api_jobs tests.test_api_job_nav_targets` (expect the nav_targets module to error → delete it; pin test fails → re-pin) → full backend suite once, read the summary line.
- [ ] **Commit** — `refactor(api): retire Job.nav_targets — the rail links to sections now`

---

### Task 14: Docs + LATER closures + final verification

**Files:**
- Modify: `docs/designs/jobs-tasks-and-worksheets.md` (§9 overview description: pillars still present but the workspace shell/rail/band are the navigation story now; §9.1 JobHeader: band, dissolved Actions, modals; task-detail section: mounts through JobShell), `docs/designs/architecture-and-conventions.md` (§5.5a: job area grouping = header+rail+band; shell pattern; skip-list unchanged), `frontend/README.md` (routes list, workspace state store), `docs/designs/LATER.md`:
  - CLOSE: "Merge the source-pull view into the detail page as an in-place toggle" (2026-06-02); "Make the Estimate and Invoice atom-pull UIs consistent" (2026-06-03); "Should a superseded estimate's tab navigate to the current estimate?" (2026-06-03); trim the oversized-pages list entries this pass extracted (JobTaskListPage, JobShipmentsPage).
  - The design doc gets a "shipped through step 3" status note; step 4 (overview rework) remains open.
- [ ] Full verification: `cd frontend && npm run test:run` (summary line), `npm run build` (no new warnings), backend `python manage.py test` in background → read `OK`/`FAILED` from the output file. Click-path sanity list for RM's browser review: rail from overview → each section; share a `/estimate/:docId` URL; collapse band on tasks, reload, still collapsed; old `/estimates/:id` bookmark redirects; wizard bookmark lands in reconcile mode; blocked/hold flows unchanged.
- [ ] **Commit** — `docs: job workspace steps 1-3 recorded; LATER closures`

---

## Self-review notes

- Spec coverage: design items 2 (band) → T2/T3; 3 (rail everywhere) → T10; 4+wizards → T12; 6 (section pages + subnav + persistence) → T6-T9; 7 (empty sections) → T7/T8/T9; 8 (eight-item rail) → T10; 9 (edit/dup modals) → T11; 10 (email v1) → T9; route family + shims → T7/T8/T12; nav_targets retirement → T13; review notes 1-7 → T12 (mode validation), T2 (lazy band), CO-last (not extracted at all this pass), T14 (docs/LATER), T1 (LRU), T7-9 (gated affordances).
- Deliberately NOT in this pass: overview pillar removal (step 4), CO panel extraction, combo views, email thread view, Notes.
- Type consistency: `getJobWs/rememberSection/rememberMode/rememberBand` used in T2/T7/T8/T12 match T1's exports; `JobShell` props in T4/T5/T7-9 match T3; `DocSubnav` items shape in T7/T8 matches T6.
