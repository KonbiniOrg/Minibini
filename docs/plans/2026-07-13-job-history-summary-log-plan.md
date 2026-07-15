# Job History Summary-Log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Job History page's Summary tab with a day-grouped, newest-first milestone log (`time | actor | action`) derived client-side from the already-fetched history feed.

**Architecture:** A new pure lib module `frontend/src/lib/historyLog.js` does all derivation (row filtering, verb table, day grouping, label formatting) so it's unit-testable without rendering; `JobHistorySection.svelte` loses its old per-object rollup and renders the module's output as a table. Timeline tab, note box, and all backend code are untouched.

**Tech Stack:** Svelte 5 (runes), Vitest + @testing-library/svelte.

**Spec:** `docs/plans/2026-07-13-job-history-summary-log.md` — the verb table and row-derivation rules there are normative.

## Global Constraints

- Frontend only. No backend, serializer, or API changes.
- All frontend commands run from `frontend/`: single file `npx vitest run tests/...` (never watch mode), full suite `npm run test:run`.
- Svelte strict mode: every `<tr>` must sit inside `<tbody>`/`<thead>`/`<tfoot>` or the build fails.
- Date formatting is hand-rolled with `DOW`/`MONTHS` arrays (the `format.js` house style) — no `toLocaleDateString`, so tests are deterministic. Test timestamps carry no `Z` suffix (local time) to stay timezone-stable.
- Work on branch `feature/history`. Commit after each task; never merge/push/PR.

---

### Task 1: `historyLog.js` derivation module

**Files:**
- Create: `frontend/src/lib/historyLog.js`
- Test: `frontend/tests/lib/historyLog.test.js`

**Interfaces:**
- Consumes: serialized history entries as the API returns them — `{ id, entry_type, object_type, object_id, username, timestamp (ISO string), changes (object|null), text, source_label, source_link }`.
- Produces (used by Task 2):
  - `statusVerb(objectType: string, status: string): string`
  - `milestoneRows(entries: object[]): Row[]` where `Row = { id, when: Date, actor: string|null, label: string, link: string|null, text: string }`
  - `groupRowsByDay(rows: Row[], today?: Date): { key: string, label: string, rows: Row[] }[]`
  - `dayLabel(d: Date, today?: Date): string` (e.g. `"Monday, January 5"`, year appended when ≠ today's year)
  - `timeLabel(d: Date): string` (e.g. `"2:05 PM"`)

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/lib/historyLog.test.js`:

```js
import { describe, it, expect } from 'vitest';
import {
  statusVerb, milestoneRows, groupRowsByDay, dayLabel, timeLabel,
} from '@/lib/historyLog.js';

function entry(over = {}) {
  return {
    id: 1, entry_type: 'audit', object_type: 'task', object_id: 7,
    username: 'rae', timestamp: '2026-01-05T09:00:00',
    changes: null, text: '',
    source_label: 'Task: Cutting', source_link: '#/jobs/5/tasks/7',
    ...over,
  };
}

describe('statusVerb', () => {
  it('maps every status through the verb table, not just the surprising ones', () => {
    expect(statusVerb('estimate', 'open')).toBe('sent');
    expect(statusVerb('changeorder', 'open')).toBe('sent');
    expect(statusVerb('invoice', 'partly-paid')).toBe('partly paid');
    expect(statusVerb('invoice', 'paid')).toBe('paid');
    expect(statusVerb('task', 'in_progress')).toBe('started');
    expect(statusVerb('task', 'pending')).toBe('reopened');
    expect(statusVerb('job', 'work_complete')).toBe('work completed');
    expect(statusVerb('job', 'draft')).toBe('reverted to draft');
    expect(statusVerb('shipment', 'picked_up')).toBe('picked up');
    expect(statusVerb('material', 'consumed')).toBe('consumed');
  });

  it('humanizes unknown statuses instead of dropping them', () => {
    expect(statusVerb('job', 'some_new_status')).toBe('some new status');
  });
});

describe('milestoneRows', () => {
  it('turns creations into created/added rows by object type', () => {
    const rows = milestoneRows([
      entry({ id: 1, object_type: 'job', changes: { _created: true }, source_label: 'Job J' }),
      entry({ id: 2, object_type: 'estimate', changes: { _created: true }, source_label: 'Estimate E1' }),
      entry({ id: 3, object_type: 'task', changes: { _created: true } }),
      entry({ id: 4, object_type: 'material', changes: { _created: true }, source_label: 'Material: plywood' }),
    ]);
    expect(rows.map((r) => r.text)).toEqual(['created', 'created', 'added', 'added']);
  });

  it('turns status diffs into verb rows carrying actor, label, link, and time', () => {
    const rows = milestoneRows([
      entry({ changes: { status: { old: 'pending', new: 'complete' } } }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      text: 'completed', actor: 'rae',
      label: 'Task: Cutting', link: '#/jobs/5/tasks/7',
    });
    expect(rows[0].when).toEqual(new Date('2026-01-05T09:00:00'));
  });

  it('prefers the richer _action text when it accompanies a status diff', () => {
    const rows = milestoneRows([
      entry({
        object_type: 'estimate',
        changes: { status: { old: 'open', new: 'expired' }, _action: 'Auto-expired (valid 30 days)' },
      }),
    ]);
    expect(rows[0].text).toBe('Auto-expired (valid 30 days)');
  });

  it('rows consumption_state transitions', () => {
    const rows = milestoneRows([
      entry({ object_type: 'material', changes: { consumption_state: { old: 'pending', new: 'consumed' } } }),
    ]);
    expect(rows[0].text).toBe('consumed');
  });

  it('skips field edits, notes, and standalone actions', () => {
    const rows = milestoneRows([
      entry({ id: 1, changes: { name: { old: 'a', new: 'b' } } }),
      entry({ id: 2, entry_type: 'note', changes: null, text: 'Customer called' }),
      entry({ id: 3, entry_type: 'action', changes: { _action: 'PO emailed to x@y.z' } }),
    ]);
    expect(rows).toEqual([]);
  });

  it('nulls the actor for system entries', () => {
    const rows = milestoneRows([entry({ username: null, changes: { _created: true } })]);
    expect(rows[0].actor).toBeNull();
  });
});

describe('dayLabel', () => {
  const today = new Date('2026-07-13T12:00:00');

  it('renders weekday, month, day', () => {
    expect(dayLabel(new Date('2026-01-05T09:00:00'), today)).toBe('Monday, January 5');
  });

  it('appends the year when it is not the current year', () => {
    expect(dayLabel(new Date('2025-12-30T09:00:00'), today)).toBe('Tuesday, December 30 2025');
  });
});

describe('timeLabel', () => {
  it('formats a 12-hour clock time', () => {
    expect(timeLabel(new Date('2026-01-05T14:05:00'))).toBe('2:05 PM');
    expect(timeLabel(new Date('2026-01-05T00:30:00'))).toBe('12:30 AM');
  });
});

describe('groupRowsByDay', () => {
  const today = new Date('2026-07-13T12:00:00');

  it('splits newest-first rows on local calendar-day boundaries', () => {
    const rows = milestoneRows([
      entry({ id: 3, timestamp: '2026-01-06T09:30:00', changes: { _created: true } }),
      entry({ id: 2, timestamp: '2026-01-05T14:00:00', changes: { _created: true } }),
      entry({ id: 1, timestamp: '2026-01-05T09:00:00', changes: { _created: true } }),
    ]);
    const days = groupRowsByDay(rows, today);
    expect(days.map((d) => d.label)).toEqual(['Tuesday, January 6', 'Monday, January 5']);
    expect(days[0].rows).toHaveLength(1);
    expect(days[1].rows).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run tests/lib/historyLog.test.js`
Expected: FAIL — cannot resolve `@/lib/historyLog.js` (module doesn't exist).

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/historyLog.js`:

```js
// Milestone-log derivation for the Job History page's Summary tab: filters
// the serialized history feed down to creations + status transitions and
// groups them into day buckets. Pure functions — no API calls, no Svelte.
// Spec: docs/plans/2026-07-13-job-history-summary-log.md

const DOW = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December'];

// Full verb table keyed `${object_type}:${status}` — every status mapped
// explicitly (even identity mappings) so either side can change without
// surprising the other. Unknown statuses fall back to the humanized raw
// value; a missing mapping must never drop a row.
const VERBS = {
  'job:draft': 'reverted to draft',
  'job:submitted': 'submitted',
  'job:approved': 'approved',
  'job:in_progress': 'started',
  'job:work_complete': 'work completed',
  'job:rejected': 'rejected',
  'job:completed': 'completed',
  'job:cancelled': 'cancelled',
  'task:pending': 'reopened',
  'task:in_progress': 'started',
  'task:blocked': 'blocked',
  'task:complete': 'completed',
  'task:cancelled': 'cancelled',
  'estimate:draft': 'reverted to draft',
  'estimate:open': 'sent',
  'estimate:accepted': 'accepted',
  'estimate:rejected': 'rejected',
  'estimate:expired': 'expired',
  'estimate:superseded': 'superseded',
  'changeorder:draft': 'reverted to draft',
  'changeorder:open': 'sent',
  'changeorder:accepted': 'accepted',
  'changeorder:rejected': 'rejected',
  'changeorder:expired': 'expired',
  'changeorder:superseded': 'superseded',
  'invoice:draft': 'reverted to draft',
  'invoice:open': 'sent',
  'invoice:partly-paid': 'partly paid',
  'invoice:paid': 'paid',
  'invoice:defaulted': 'defaulted',
  'invoice:cancelled': 'cancelled',
  'invoice:superseded': 'superseded',
  'material:pending': 'reset to pending',
  'material:consumed': 'consumed',
  'material:released': 'released',
  'shipment:prepared': 'prepared',
  'shipment:picked_up': 'picked up',
};

// Object types whose creation reads "created"; the rest read "added".
const CREATED_TYPES = new Set(['job', 'estimate', 'changeorder', 'invoice']);

export function statusVerb(objectType, status) {
  return VERBS[`${objectType}:${status}`] ?? String(status).replace(/_/g, ' ');
}

// One log row per creation or status transition; null for everything else
// (field edits, notes, standalone actions).
function milestoneRow(entry) {
  const c = entry.changes || {};
  const base = {
    id: entry.id,
    when: new Date(entry.timestamp),
    actor: entry.username || null,
    label: entry.source_label || entry.object_type,
    link: entry.source_link || null,
  };
  if (c._created) {
    return { ...base, text: CREATED_TYPES.has(entry.object_type) ? 'created' : 'added' };
  }
  const status = c.status?.new ?? c.consumption_state?.new;
  if (status != null) {
    return { ...base, text: c._action || statusVerb(entry.object_type, status) };
  }
  return null;
}

export function milestoneRows(entries) {
  return (entries || []).map(milestoneRow).filter(Boolean);
}

export function dayLabel(d, today = new Date()) {
  const year = d.getFullYear() === today.getFullYear() ? '' : ` ${d.getFullYear()}`;
  return `${DOW[d.getDay()]}, ${MONTHS[d.getMonth()]} ${d.getDate()}${year}`;
}

export function timeLabel(d) {
  let h = d.getHours();
  const ampm = h >= 12 ? 'PM' : 'AM';
  h = h % 12 || 12;
  return `${h}:${String(d.getMinutes()).padStart(2, '0')} ${ampm}`;
}

// rows (already newest-first) -> [{ key, label, rows }] split on local
// calendar day.
export function groupRowsByDay(rows, today = new Date()) {
  const out = [];
  for (const row of rows) {
    const d = row.when;
    const key = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    const last = out[out.length - 1];
    if (last && last.key === key) last.rows.push(row);
    else out.push({ key, label: dayLabel(d, today), rows: [row] });
  }
  return out;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npx vitest run tests/lib/historyLog.test.js`
Expected: PASS, all tests green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/historyLog.js frontend/tests/lib/historyLog.test.js
git commit -m "feat(history): milestone-log derivation module for job history summary

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Rewire the Summary tab in `JobHistorySection.svelte`

**Files:**
- Modify: `frontend/src/components/jobs/JobHistorySection.svelte`
- Test: `frontend/tests/components/jobs/JobHistorySection.test.js`

**Interfaces:**
- Consumes from Task 1: `milestoneRows(entries)`, `groupRowsByDay(rows)`, `timeLabel(when)` from `frontend/src/lib/historyLog.js` (exact signatures in Task 1's Produces block).
- Produces: no downstream consumers; `JobHistorySection` keeps its existing props (`job`, `onJobChange`) unchanged.

- [ ] **Step 1: Replace the old Summary component test with milestone-log tests**

In `frontend/tests/components/jobs/JobHistorySection.test.js`, DELETE the entire test `it('rolls events up per object on the Summary tab', ...)` (it exercises the removed rollup) and add these two tests in its place:

```js
  it('renders the Summary tab as a day-grouped milestone log', async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith('/api/jobs/5/history/')) return Promise.resolve({ results: [
        { id: 4, entry_type: 'action', object_type: 'job', object_id: 5,
          username: null, timestamp: '2026-01-06T09:30:00',
          changes: { status: { old: 'submitted', new: 'approved' }, _action: 'Approved via customer link' },
          source_label: 'Job JOB-2025-0005', source_link: '#/jobs/5' },
        { id: 3, entry_type: 'audit', object_type: 'estimate', object_id: 9,
          username: 'rae', timestamp: '2026-01-05T14:00:00',
          changes: { status: { old: 'draft', new: 'open' } },
          source_label: 'Estimate EST-2025-0001', source_link: null },
        { id: 2, entry_type: 'audit', object_type: 'job', object_id: 5,
          username: 'rae', timestamp: '2026-01-05T10:00:00',
          changes: { name: { old: 'a', new: 'b' } },
          source_label: 'Job JOB-2025-0005', source_link: '#/jobs/5' },
        { id: 1, entry_type: 'audit', object_type: 'estimate', object_id: 9,
          username: 'rae', timestamp: '2026-01-05T09:00:00',
          changes: { _created: true },
          source_label: 'Estimate EST-2025-0001', source_link: null },
      ] });
      return Promise.resolve({ results: [] });
    });
    const { container, findByRole, getByRole, getByText, queryByText } =
      render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(getByRole('button', { name: 'Summary' }));
    // three milestone rows; the name edit contributes none
    expect(container.querySelectorAll('tr.log-row').length).toBe(3);
    expect(queryByText('name')).toBeNull();
    // day-break rows (regex so a future non-current-year suffix still matches)
    expect(getByText(/Tuesday, January 6/)).toBeInTheDocument();
    expect(getByText(/Monday, January 5/)).toBeInTheDocument();
    // verb table ("sent"), _action preference, and a creation row
    expect(getByText('sent')).toBeInTheDocument();
    expect(getByText('Approved via customer link')).toBeInTheDocument();
    expect(getByText('created')).toBeInTheDocument();
    // system entry renders an em-dash actor
    expect(getByText('—')).toBeInTheDocument();
  });

  it('shows an empty state on the Summary tab when no milestones exist', async () => {
    api.get.mockResolvedValue({ results: [
      { id: 1, entry_type: 'note', object_type: 'job', object_id: 5,
        username: 'rae', timestamp: '2026-01-05T09:00:00', text: 'Customer called',
        changes: null, source_label: 'Job JOB-2025-0005', source_link: null },
    ] });
    const { findByRole, getByRole, getByText } =
      render(JobHistorySection, { props: { job: JOB } });
    await findByRole('heading', { name: 'History' });
    await fireEvent.click(getByRole('button', { name: 'Summary' }));
    expect(getByText('No milestones yet.')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the component tests to verify the new ones fail**

Run (from `frontend/`): `npx vitest run tests/components/jobs/JobHistorySection.test.js`
Expected: the two new tests FAIL (no `tr.log-row`, no "No milestones yet."); every other test in the file still PASSES.

- [ ] **Step 3: Rewrite the Summary tab in the component**

All edits in `frontend/src/components/jobs/JobHistorySection.svelte`:

**(a) Add the import** after the existing `import FormMessage from '../FormMessage.svelte';` line:

```js
  import { milestoneRows, groupRowsByDay, timeLabel } from '../../lib/historyLog.js';
```

**(b) Delete the old rollup script block** — everything from the comment `// --- Summary tab: roll the same events up per object ---` through the end of the `let summary = $derived.by(() => { ... });` statement (the functions `dateStr`, `milestones`, `taskExtra` and the `summary` derived). Replace that whole block with:

```js
  // --- Summary tab: milestone log (creations + status changes only) ---
  let logDays = $derived(groupRowsByDay(milestoneRows(history?.results || [])));
```

**(c) Replace the Summary tab markup** — the entire block

```svelte
      {#if activeTab === 'summary'}
      <div class="summary">
        ...
      </div>
      {/if}
```

(from `{#if activeTab === 'summary'}` down to its matching `{/if}`) becomes:

```svelte
      {#if activeTab === 'summary'}
        {#if logDays.length > 0}
          <table class="log">
            {#each logDays as day (day.key)}
              <tbody>
                <tr class="day-break"><th colspan="3">{day.label}</th></tr>
                {#each day.rows as row (row.id)}
                  <tr class="log-row">
                    <td class="log-time">{timeLabel(row.when)}</td>
                    <td class="log-actor">{row.actor ?? '—'}</td>
                    <td class="log-action">
                      {#if row.link}<a href={row.link}>{row.label}</a>{:else}<span>{row.label}</span>{/if}
                      {row.text}
                    </td>
                  </tr>
                {/each}
              </tbody>
            {/each}
          </table>
        {:else}
          <p>No milestones yet.</p>
        {/if}
      {/if}
```

(One `<tbody>` per day group keeps every `<tr>` legally wrapped — Svelte strict mode requires it.)

**(d) Replace the Summary styles** — delete these four rules:

```css
  .summary .sum-sec { margin: 0 0 18px; }
  .summary h3 { font-size: 14px; margin: 0 0 4px; color: #1f2937; }
  .summary p { margin: 2px 0; }
  .summary .muted { color: #6b7280; font-size: 13px; }
```

and add in their place:

```css
  .log { border-collapse: collapse; width: 100%; }
  .log td, .log th { padding: 3px 12px 3px 0; text-align: left; font-size: 14px; vertical-align: baseline; }
  .log .day-break th { padding-top: 16px; padding-bottom: 4px; border-bottom: 1px solid #d1d5db; color: #374151; font-size: 13px; }
  .log-time { white-space: nowrap; color: #6b7280; width: 1%; }
  .log-actor { white-space: nowrap; color: #374151; width: 1%; }
```

- [ ] **Step 4: Run the component tests to verify they pass**

Run (from `frontend/`): `npx vitest run tests/components/jobs/JobHistorySection.test.js`
Expected: PASS — the two new tests and all pre-existing Timeline/note tests.

- [ ] **Step 5: Run the full frontend suite**

Run (from `frontend/`): `npm run test:run`
Expected: PASS. Read the summary line — do not judge by a piped exit code.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/jobs/JobHistorySection.svelte frontend/tests/components/jobs/JobHistorySection.test.js
git commit -m "feat(history): summary tab becomes a day-grouped milestone log

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Update the durable design doc

**Files:**
- Modify: `docs/designs/jobs-tasks-and-worksheets.md` (the job-pages table row for History, currently line ~1394)

**Interfaces:**
- Consumes: nothing from other tasks (text-only).
- Produces: nothing — documentation.

- [ ] **Step 1: Update the History row**

In the job-pages table, the History row currently ends:

```
`JobHistorySection.svelte` (named to avoid colliding with the existing contact/business/PO `HistoryPanel.svelte`) — the job history timeline + note-adding, previously its own standalone page |
```

Replace that trailing description (after the em dash) so the row ends:

```
`JobHistorySection.svelte` (named to avoid colliding with the existing contact/business/PO `HistoryPanel.svelte`) — two tabs: **Timeline** (the forensic feed: minute-bundled field diffs, notes + note-adding, long-value popovers, per-type tints) and **Summary** (a day-grouped, newest-first milestone log — `time | actor | action` — showing only creations and status transitions, derived client-side by `frontend/src/lib/historyLog.js`; the full status→verb table lives there, with humanized-raw fallback so unknown statuses never drop a row; `_action` text is preferred over the verb when both exist; system/customer-link rows show an em-dash actor) |
```

- [ ] **Step 2: Commit**

```bash
git add docs/designs/jobs-tasks-and-worksheets.md
git commit -m "docs: describe the job history Summary milestone log

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
