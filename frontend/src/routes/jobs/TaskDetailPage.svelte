<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import { currentBlep } from '../../stores/currentBlep.js';
  import TaskActions from '../../components/tasks/TaskActions.svelte';
  import StartWorkConflictModal from '../../components/tasks/StartWorkConflictModal.svelte';
  import BlepList from '../../components/tasks/BlepList.svelte';
  import BlepEditModal from '../../components/tasks/BlepEditModal.svelte';

  let { params = {} } = $props();

  let task = $state(null);
  let loading = $state(true);
  let error = $state('');
  let conflict = $state(null);
  let bleps = $state([]);
  let editingBlep = $state(null);
  let modalMode = $state('edit'); // 'edit' | 'create-open'
  const modalOpen = $derived(editingBlep !== null || modalMode === 'create-open');

  function openEdit(blep) { editingBlep = blep; modalMode = 'edit'; }
  function openCreate() { editingBlep = null; modalMode = 'create-open'; }
  function closeModal() { editingBlep = null; modalMode = 'edit'; }
  async function handleSaved() { closeModal(); await loadBleps(); }

  function handleConflict(c) { conflict = c; }
  function handleResolved() { conflict = null; refresh(); }
  function handleCancel() { conflict = null; }

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

  async function loadBleps() {
    try {
      const resp = await api.get(`/api/bleps/?task=${params.taskId}`);
      bleps = resp.results || resp;
    } catch (e) {
      // ignore; surfaced via task error if any
    }
  }

  async function refresh() {
    await loadTask();
    await loadBleps();
  }

  $effect(() => {
    if (params.taskId) {
      loadTask();
      loadBleps();
    }
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
    onConflict={handleConflict}
  />

  <StartWorkConflictModal
    {conflict}
    taskId={task?.task_id}
    onResolved={handleResolved}
    onCancel={handleCancel}
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

  <BlepList
    {bleps}
    currentUser={$userStore}
    {userPermissions}
    onEdit={openEdit}
    onDelete={(b) => { editingBlep = b; modalMode = 'edit'; }}
    onAdd={openCreate}
  />

  <BlepEditModal
    open={modalOpen}
    mode={modalMode === 'create-open' ? 'create' : 'edit'}
    blep={editingBlep}
    taskId={task?.task_id}
    currentUser={$userStore}
    {userPermissions}
    onSaved={handleSaved}
    onClose={closeModal}
  />
{/if}

<style>
  .error { color: #a8071a; }
</style>
