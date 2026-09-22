<script>
  // Optional cost→sell attribution picker for a PO line (outsourced-work
  // port, spec §7 rule 1): pick a job, then pick one of that job's tasks
  // to link. Subtasks no longer exist, so every task returned by the job's
  // task list is eligible — the filtering below is purely a type-ahead
  // narrowing UX, not an eligibility rule.
  //
  // `value` is the task id (or null — the link is always optional).
  //
  // `job`: PO Job/Task consolidation (RM 2026-09-21). Two modes:
  //   - omitted (undefined) — UNCONTROLLED: this component owns its own
  //     cascading JobPicker (ReconciliationSection's appended-lines table
  //     uses this — those lines never submit a `job` field at all, so the
  //     job here is transient, narrowing-only UI state).
  //   - passed (even null) — CONTROLLED: the caller owns the job (a single
  //     shared Job picker feeds both material attribution and this task
  //     cascade, LineItemForm's consolidated flow) — the internal JobPicker
  //     is hidden and the task list cascades off the prop instead.
  //
  // Fix 3 (RM browser-testing): the task field was a plain <select> of
  // every one of the picked job's tasks — unusable once a job has more
  // than a handful. Converted to the same filter-as-you-type SearchPicker
  // composition JobPicker uses just above it: `search` filters the
  // already-fetched `tasks` list client-side (no new endpoint — the whole
  // list was already being pulled down for the <select>). `resolveLabel`
  // mirrors JobPicker's own resolveLabel exactly — check the local list
  // first, else fetch the task directly — rather than depending on a
  // parent-seeded `selectedItem` prop: the edit-mode resolve effect below
  // sets `jobId`/`jobRow` asynchronously, and by the time it would seed a
  // task prefill object, this SearchPicker's own resolve effect may have
  // already run (and latched `labelForValue`) against a still-empty
  // `tasks` list — a real race, not a hypothetical one. The direct fetch
  // fallback sidesteps it: whichever value SearchPicker resolves against,
  // it gets a real answer, same guarantee JobPicker relies on.
  import { api } from '../lib/api.js';
  import JobPicker from './JobPicker.svelte';
  import SearchPicker from './SearchPicker.svelte';

  let { value = $bindable(null), job = undefined, disabled = false } = $props();

  const controlled = $derived(job !== undefined);

  let jobId = $state(null);
  let jobRow = $state(null);
  let tasks = $state([]);
  let loadingTasks = $state(false);
  let lastFetchedJob = undefined; // sentinel distinct from null (no job picked)
  let resolvedFromValue = false;

  const effectiveJobId = $derived(controlled ? job : jobId);

  const taskRowLabel = (t) => t.name;
  const searchTasks = (q) => {
    const needle = q.trim().toLowerCase();
    const rows = tasks.filter((t) => t.name.toLowerCase().includes(needle));
    return { rows, total: rows.length };
  };
  const resolveTaskLabel = (id) => {
    const local = tasks.find((t) => t.task_id === id);
    if (local) return Promise.resolve(local.name);
    return api.get(`/api/tasks/${id}/`).then((t) => t.name).catch(() => null);
  };

  async function loadTasks(id) {
    if (!id) { tasks = []; return; }
    loadingTasks = true;
    try {
      const data = await api.get(`/api/jobs/${id}/tasks/`);
      tasks = Array.isArray(data) ? data : [];
    } catch {
      tasks = [];
    } finally {
      loadingTasks = false;
    }
  }

  $effect(() => {
    const id = effectiveJobId;
    if (id === lastFetchedJob) return;
    const isFirstRun = lastFetchedJob === undefined;
    lastFetchedJob = id;
    loadTasks(id);
    // Controlled mode only: a job change from the caller invalidates a
    // previously-picked task from the old job. Skipped on the very first
    // run (mount, e.g. a defaultJob prop already carrying `job`) so a
    // caller-seeded job doesn't wipe out a value it just seeded alongside
    // it. In uncontrolled mode this clearing is handleJobSelect's job
    // (below) — it fires only on a genuine user click, never on the
    // resolve-from-value effect's programmatic `jobId` set just below,
    // which this effect must NOT treat as a "job changed" event.
    if (controlled && !isFirstRun) {
      value = null;
    }
  });

  // Uncontrolled edit-mode entry only: a task id was passed in before the
  // job was ever picked locally (e.g. editing an existing line/appended
  // entry). Resolve its job once so the cascading select has something to
  // show — this is the only place `value` drives `jobId` instead of the
  // reverse. Not applicable in controlled mode — the caller owns `job` and
  // is expected to supply it itself.
  $effect(() => {
    if (controlled || resolvedFromValue || value == null || jobId != null) return;
    resolvedFromValue = true;
    api.get(`/api/tasks/${value}/`)
      .then((t) => {
        jobId = t.job.id;
        jobRow = { job_id: t.job.id, job_number: t.job.job_number, name: t.job.name };
      })
      .catch(() => {});
  });

  function handleJobSelect(j) {
    jobRow = j;
    // A new job invalidates a previously-picked task from the old one —
    // only on a genuine user-driven change, never during the resolve-from-
    // value seed above (that flow sets jobId directly, not via onSelect).
    value = null;
  }
</script>

<div class="task-link-picker">
  {#if !controlled}
    <JobPicker bind:value={jobId} selectedItem={jobRow} onSelect={handleJobSelect} openOnly {disabled} />
  {/if}
  <SearchPicker bind:value
    search={searchTasks} resolveLabel={resolveTaskLabel} rowLabel={taskRowLabel}
    onPick={(t) => { value = t.task_id; }}
    onClear={() => { value = null; }}
    disabled={disabled || !effectiveJobId || loadingTasks}
    placeholder="Search tasks…" />
</div>

<style>
  .task-link-picker { display: flex; flex-direction: column; gap: 4px; }
</style>
