<script>
  // Optional cost→sell attribution picker for a PO line (outsourced-work
  // port, spec §7 rule 1): pick a job, then pick one of that job's tasks
  // to link. Subtasks no longer exist, so every task returned by the job's
  // task list is eligible — the filtering below is purely a type-ahead
  // narrowing UX, not an eligibility rule.
  //
  // `value` is the task id (or null — the link is always optional).
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

  let { value = $bindable(null), disabled = false } = $props();

  let jobId = $state(null);
  let jobRow = $state(null);
  let tasks = $state([]);
  let loadingTasks = $state(false);
  let lastFetchedJob = undefined; // sentinel distinct from null (no job picked)
  let resolvedFromValue = false;

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
    const id = jobId;
    if (id === lastFetchedJob) return;
    lastFetchedJob = id;
    loadTasks(id);
  });

  // Edit-mode entry: a task id was passed in before the job was ever
  // picked locally (e.g. editing an existing line/appended entry). Resolve
  // its job once so the cascading select has something to show — this is
  // the only place `value` drives `jobId` instead of the reverse.
  $effect(() => {
    if (resolvedFromValue || value == null || jobId != null) return;
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
  <JobPicker bind:value={jobId} selectedItem={jobRow} onSelect={handleJobSelect} openOnly {disabled} />
  <SearchPicker bind:value
    search={searchTasks} resolveLabel={resolveTaskLabel} rowLabel={taskRowLabel}
    onPick={(t) => { value = t.task_id; }}
    onClear={() => { value = null; }}
    disabled={disabled || !jobId || loadingTasks}
    placeholder="Search tasks…" />
</div>

<style>
  .task-link-picker { display: flex; flex-direction: column; gap: 4px; }
</style>
