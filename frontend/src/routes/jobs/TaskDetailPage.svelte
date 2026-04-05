<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import { currentBlep } from '../../stores/currentBlep.js';
  import TaskActions from '../../components/tasks/TaskActions.svelte';

  let { params = {} } = $props();

  let task = $state(null);
  let loading = $state(true);
  let error = $state('');

  const activeBlepOnThisTask = $derived.by(() => {
    const cb = $currentBlep;
    if (!cb || !task) return null;
    return cb.task && cb.task.id === task.task_id ? cb : null;
  });

  const userPermissions = $derived($userStore?.permissions || []);

  async function loadTask() {
    loading = true;
    error = '';
    try {
      task = await api.get(`/api/tasks/${params.taskId}/`);
    } catch (e) {
      error = e.message || 'Could not load task.';
    } finally {
      loading = false;
    }
  }

  async function refresh() {
    await loadTask();
  }

  $effect(() => {
    if (params.taskId) loadTask();
  });
</script>

{#if loading}
  <p>Loading…</p>
{:else if error}
  <p class="error">{error}</p>
{:else if task}
  <h2>Task: {task.name}</h2>
  {#if task.work_order}
    <p>
      <a href={`/jobs/${task.work_order.job.id}`} use:link>
        &laquo; {task.work_order.job.job_number} {task.work_order.job.name}
      </a>
    </p>
  {/if}

  <TaskActions
    {task}
    user={$userStore}
    {userPermissions}
    {activeBlepOnThisTask}
    onChanged={refresh}
    onConflict={() => { /* wired in Task 14 */ }}
  />

  <table border="1">
    <tbody>
      <tr><td>Status</td><td>{task.status}</td></tr>
      <tr><td>Description</td><td>{task.description || '-'}</td></tr>
      <tr><td>Assignee</td><td>{task.assignee_name || 'Unassigned'}</td></tr>
      <tr><td>Est. quantity</td><td>{task.est_qty || '-'} {task.units || ''}</td></tr>
      <tr><td>Rate</td><td>{task.rate ? `$${task.rate}` : '-'}</td></tr>
      <tr><td>Accounting category</td><td>{task.accounting_category || '-'}</td></tr>
    </tbody>
  </table>
{/if}

<style>
  .error { color: #a8071a; }
</style>
