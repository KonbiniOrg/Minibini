<script>
  // Optional cost→sell attribution picker for a PO line (task-owned-money
  // Phase 5, spec §7 rule 1): pick a job, then pick one of that job's
  // TOP-LEVEL tasks to link. The API 400s a subtask link
  // (PurchaseOrderLineItem.clean()) — this picker filters client-side to
  // `parent_task == null` tasks as a courtesy; the server stays the
  // backstop for anything that slips past (e.g. a stale list).
  //
  // `value` is the task id (or null — the link is always optional).
  import { api } from '../lib/api.js';
  import JobPicker from './JobPicker.svelte';

  let { value = $bindable(null), disabled = false } = $props();

  let jobId = $state(null);
  let jobRow = $state(null);
  let tasks = $state([]);
  let loadingTasks = $state(false);
  let lastFetchedJob = undefined; // sentinel distinct from null (no job picked)
  let resolvedFromValue = false;

  async function loadTasks(id) {
    if (!id) { tasks = []; return; }
    loadingTasks = true;
    try {
      const data = await api.get(`/api/jobs/${id}/tasks/`);
      tasks = (Array.isArray(data) ? data : []).filter((t) => t.parent_task == null);
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
  <select bind:value disabled={disabled || !jobId || loadingTasks} aria-label="Task">
    <option value={null}>-- No task link --</option>
    {#each tasks as t}
      <option value={t.task_id}>{t.name}</option>
    {/each}
  </select>
</div>

<style>
  .task-link-picker { display: flex; flex-direction: column; gap: 4px; }
</style>
