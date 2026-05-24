<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import { currentBlep } from '../../stores/currentBlep.js';
  import TaskActions from '../../components/tasks/TaskActions.svelte';
  import StartWorkConflictModal from '../../components/tasks/StartWorkConflictModal.svelte';
  import BlepList from '../../components/tasks/BlepList.svelte';
  import BlepEditModal from '../../components/tasks/BlepEditModal.svelte';
  import TaskTree from '../../components/TaskTree.svelte';
  import LinkifiedText from '../../components/LinkifiedText.svelte';
  import MaterialModal from '../../components/MaterialModal.svelte';
  import WorkItemForm from '../../components/WorkItemForm.svelte';
  import AssignModal from '../../components/AssignModal.svelte';
  import JobHeader from '../../components/jobs/JobHeader.svelte';
  import { formatQtyUnits, formatDuration } from '../../lib/format.js';

  let { params = {} } = $props();

  let task = $state(null);
  let job = $state(null);
  let contact = $state(null);
  let loading = $state(true);
  let error = $state('');
  let conflict = $state(null);
  let bleps = $state([]);
  let editingBlep = $state(null);
  let modalMode = $state('edit'); // 'edit' | 'create-open'
  const modalOpen = $derived(editingBlep !== null || modalMode === 'create-open');

  // Materials state
  let materials = $state([]);
  let categories = $state([]);
  let matModalOpen = $state(false);
  let matModalMode = $state('create');
  let matModalMaterial = $state(null);

  // Subtasks state
  let subtasks = $state([]);
  let subtaskModalOpen = $state(false);
  let assignModalOpen = $state(false);
  let actualQtyError = $state('');
  let actualQtyInput = $state('');
  let actualQtySaving = $state(false);
  let actualQtySaved = $state(false);

  // Keep the local input in sync when the task reloads (e.g., after a save
  // round-trip), but don't fight the user while they're typing.
  $effect(() => {
    if (task && !actualQtySaving) {
      actualQtyInput = task.actual_qty ?? '';
    }
  });

  // Edit-task modal
  let editTaskOpen = $state(false);
  let templates = $state([]);

  async function loadTemplates() {
    try {
      const resp = await api.get('/api/task-templates/?page_size=100');
      templates = resp.results || resp;
    } catch (e) {
      templates = [];
    }
  }

  function openEdit(blep) { editingBlep = blep; modalMode = 'edit'; }
  function openCreate() { editingBlep = null; modalMode = 'create-open'; }
  function closeModal() { editingBlep = null; modalMode = 'edit'; }
  async function handleSaved() { closeModal(); await loadBleps(); }

  const taskIsTerminal = $derived(
    task?.status === 'complete' || task?.status === 'cancelled'
  );

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
      if (task?.job?.id) {
        await loadJobContext(task.job.id);
      }
    } catch (e) {
      error = e.message || 'Could not load task.';
    } finally {
      loading = false;
    }
  }

  async function loadJobContext(jobId) {
    try {
      job = await api.get(`/api/jobs/${jobId}/`);
      if (job.contact) {
        try {
          contact = await api.get(`/api/contacts/${job.contact}/`);
        } catch (e) {
          contact = null;
        }
      }
    } catch (e) {
      job = null;
      contact = null;
    }
  }

  async function saveActualQty(value) {
    if (!task) return;
    actualQtyError = '';
    actualQtySaved = false;
    actualQtySaving = true;
    try {
      await api.patch(`/api/tasks/${task.task_id}/actual-qty/`, { actual_qty: value });
      await loadTask();
      actualQtySaved = true;
      setTimeout(() => { actualQtySaved = false; }, 1500);
    } catch (e) {
      actualQtyError = e.message || 'Could not save actual qty';
    } finally {
      actualQtySaving = false;
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

  async function loadMaterials() {
    try {
      materials = await api.get(`/api/tasks/${params.taskId}/materials/`);
    } catch (e) {
      materials = [];
    }
  }

  async function loadCategories() {
    try {
      const resp = await api.get('/api/accounting-categories/?page_size=100');
      categories = resp.results || resp;
    } catch (e) {
      categories = [];
    }
  }

  async function loadSubtasks() {
    try {
      const rawSubs = await api.get(`/api/tasks/${params.taskId}/subtasks/`);
      // Enrich each subtask with its materials
      subtasks = await Promise.all(rawSubs.map(async (sub) => {
        try {
          const subMats = await api.get(`/api/tasks/${sub.task_id}/materials/`);
          return { ...sub, materials: subMats };
        } catch (e) {
          return { ...sub, materials: [] };
        }
      }));
    } catch (e) {
      subtasks = [];
    }
  }

  async function refresh() {
    await loadTask();
    await loadBleps();
    await loadMaterials();
    await loadSubtasks();
  }

  $effect(() => {
    if (params.taskId) {
      loadTask();
      loadBleps();
      loadMaterials();
      loadSubtasks();
      loadCategories();
      loadTemplates();
    }
  });

  // Material modal handlers
  function openAddMaterial() {
    matModalMaterial = null;
    matModalMode = 'create';
    matModalOpen = true;
  }

  function openEditMaterial(material) {
    matModalMaterial = material;
    matModalMode = 'edit';
    matModalOpen = true;
  }

  async function handleDeleteMaterial(material) {
    if (!confirm('Delete this material?')) return;
    try {
      await api.delete(`/api/tasks/${params.taskId}/materials/${material.material_id}/`);
      await loadMaterials();
    } catch (e) {
      alert(e.message || 'Could not delete material.');
    }
  }

  function handleMaterialSaved() {
    matModalOpen = false;
    matModalMaterial = null;
    loadMaterials();
  }

  // Subtask modal handlers
  function openAddSubtask() {
    subtaskModalOpen = true;
  }

  function handleSubtaskSaved() {
    subtaskModalOpen = false;
    loadSubtasks();
  }

  // Subtask tree callbacks
  function handleSubtaskTaskClick(sub) {
    if (task && task.job) {
      window.location.hash = `/jobs/${task.job.id}/tasks/${sub.task_id}`;
    }
  }

  function handleSubtaskEditMaterial(material, parentTask) {
    matModalMaterial = material;
    matModalMode = 'edit';
    // Use the subtask's task_id for the material modal
    matModalOpen = true;
    // Override taskId to the subtask
    subtaskMatTaskId = parentTask.task_id;
  }

  async function handleSubtaskDeleteMaterial(material, parentTask) {
    if (!confirm('Delete this material?')) return;
    try {
      await api.delete(`/api/tasks/${parentTask.task_id}/materials/${material.material_id}/`);
      await loadSubtasks();
    } catch (e) {
      alert(e.message || 'Could not delete material.');
    }
  }

  // Track which task the material modal targets (for subtask materials)
  let subtaskMatTaskId = $state(null);
  const effectiveMatTaskId = $derived(subtaskMatTaskId || params.taskId);

  // Reset subtaskMatTaskId when modal closes
  function handleMatModalClose() {
    matModalOpen = false;
    subtaskMatTaskId = null;
  }

  function handleSubtaskAddMaterial(parentTask) {
    matModalMaterial = null;
    matModalMode = 'create';
    subtaskMatTaskId = parentTask.task_id;
    matModalOpen = true;
  }

  function handleMaterialSavedForSubtask() {
    matModalOpen = false;
    matModalMaterial = null;
    subtaskMatTaskId = null;
    loadSubtasks();
  }
</script>

{#if loading}
  <p>Loading…</p>
{:else if error}
  <p class="error">{error}</p>
{:else if task}
  {#if job}
    <JobHeader {job} {contact} onStatusChange={refresh} />
  {/if}
  {#if task.job}
    <div class="toolbar">
      <a href={`/jobs/${task.job.id}`} use:link class="back-link">&laquo; back to overview</a>
      <a href={`/jobs/${task.job.id}/tasklist`} use:link class="back-link">task list</a>
      {#if !taskIsTerminal}
        <button type="button" onclick={() => { editTaskOpen = true; }}>edit task</button>
      {/if}
      <h2 class="task-title">Task: {task.name}</h2>
    </div>
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
      <tr><td>Status</td><td>{task.status}{#if task.status === 'blocked' && task.blocked_reason} — {task.blocked_reason}{/if}</td></tr>
      <tr><td>Description</td><td class="preserve-breaks"><LinkifiedText text={task.description || '-'} /></td></tr>
      <tr><td>Assignee</td><td>{task.assignee_name || 'Unassigned'} <button type="button" onclick={() => { assignModalOpen = true; }}>assign</button></td></tr>
      <tr><td>Est. quantity</td><td>{task.est_qty || '-'} {task.scheme_unit_label || ''}</td></tr>
      <tr><td>Est. worker time</td><td>{formatDuration(task.est_worker_time)}</td></tr>
      <tr><td>Rate</td><td>{task.effective_rate ? `$${task.effective_rate}` : '-'}</td></tr>
    </tbody>
  </table>

  <!-- Charge section -->
  {#if task && task.scheme_name}
    <h3>Charge</h3>
    <table border="1"><tbody>
      <tr><td><strong>Scheme</strong></td><td>{task.scheme_name}</td></tr>
      <tr><td><strong>Rate</strong></td><td>${task.effective_rate}/{task.scheme_unit_label}</td></tr>
      {#if Array.isArray(task.active_modifiers) && task.active_modifiers.length > 0}
        <tr><td><strong>Modifiers</strong></td>
          <td>{task.active_modifiers.join(', ')}</td></tr>
      {/if}
      {#if task.scheme_algorithm === 'entered_qty'}
        <tr><td><strong>Actual {task.scheme_unit_label}s</strong></td>
          <td>
            <input
              type="number" step="0.01"
              bind:value={actualQtyInput}
              onkeydown={(e) => { if (e.key === 'Enter') saveActualQty(actualQtyInput); }}>
            <button type="button" onclick={() => saveActualQty(actualQtyInput)} disabled={actualQtySaving}>
              {actualQtySaving ? 'Saving…' : 'Save'}
            </button>
            {#if actualQtySaved}<span class="saved-flash">saved</span>{/if}
            {#if actualQtyError}<span class="field-error">{actualQtyError}</span>{/if}
          </td></tr>
      {:else if task.scheme_algorithm === 'elapsed_time'}
        <tr><td><strong>Actual {task.scheme_unit_label || 'hour'}s</strong></td>
          <td>{Number(task.actual_hours) || 0}</td></tr>
      {:else if task.scheme_algorithm === 'flat_fee'}
        <tr><td><strong>Quantity</strong></td>
          <td>{Number(task.est_qty ?? 1)} {task.scheme_unit_label || ''}</td></tr>
      {/if}
      {#if task.computed_charge}
        <tr><td><strong>Charge</strong></td><td>${task.computed_charge}</td></tr>
      {/if}
    </tbody></table>
  {/if}

  <!-- Materials section -->
  <h3>Materials</h3>
  {#if materials.length > 0}
    <table border="1" class="materials-table">
      <thead>
        <tr>
          <th>Description</th>
          <th class="text-right">Qty</th>
          <th class="text-right">Unit Cost</th>
          <th class="text-right">Sell Price</th>
          <th class="text-right">Total</th>
          {#if !taskIsTerminal}<th>Actions</th>{/if}
        </tr>
      </thead>
      <tbody>
        {#each materials as mat}
          <tr>
            <td class="preserve-breaks">{mat.description || '(no description)'}</td>
            <td class="text-right">{formatQtyUnits(mat.quantity, mat.units)}</td>
            <td class="text-right">{mat.unit_cost ? `$${Number(mat.unit_cost).toFixed(2)}` : '-'}</td>
            <td class="text-right">{mat.sell_price ? `$${Number(mat.sell_price).toFixed(2)}` : '-'}</td>
            <td class="text-right">{(Number(mat.quantity) && Number(mat.sell_price)) ? `$${(Number(mat.quantity) * Number(mat.sell_price)).toFixed(2)}` : '-'}</td>
            {#if !taskIsTerminal}
              <td>
                <button type="button" onclick={() => openEditMaterial(mat)}>edit</button>
                <button type="button" onclick={() => handleDeleteMaterial(mat)}>del</button>
              </td>
            {:else}
              <td></td>
            {/if}
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p>No materials.</p>
  {/if}
  {#if !taskIsTerminal}
    <p><button type="button" onclick={openAddMaterial}>Add Material</button></p>
  {/if}

  <MaterialModal
    open={matModalOpen}
    mode={matModalMode}
    material={matModalMaterial}
    taskId={effectiveMatTaskId}
    {categories}
    onSaved={subtaskMatTaskId ? handleMaterialSavedForSubtask : handleMaterialSaved}
    onClose={handleMatModalClose}
  />

  <!-- Subtasks section -->
  <h3>Subtasks</h3>
  {#if subtasks.length > 0}
      <TaskTree
        tasks={subtasks}
        readonly={taskIsTerminal}
        showStatus={true}
        showAssignee={true}
        onTaskClick={handleSubtaskTaskClick}
        onEditTask={(sub) => {}}
        onDeleteTask={(sub) => {}}
        onAddMaterial={handleSubtaskAddMaterial}
        onEditMaterial={handleSubtaskEditMaterial}
        onDeleteMaterial={handleSubtaskDeleteMaterial}
        onAddSubtask={() => {}}
        onReorder={() => {}}
      />
    {:else}
      <p>No subtasks.</p>
    {/if}
  {#if !taskIsTerminal}
    <p><button type="button" onclick={openAddSubtask}>Add Subtask</button></p>
  {/if}

  <WorkItemForm
    open={subtaskModalOpen}
    mode="manual"
    context="subtask"
    contextId={task?.task_id}
    templates={[]}
    onSaved={handleSubtaskSaved}
    onClose={() => { subtaskModalOpen = false; }}
  />

  <WorkItemForm
    open={editTaskOpen}
    mode="manual"
    context="job"
    contextId={task.job?.id}
    item={task}
    isEdit={true}
    {templates}
    onSaved={() => { editTaskOpen = false; refresh(); }}
    onClose={() => { editTaskOpen = false; }}
  />

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

  <AssignModal
    open={assignModalOpen}
    {task}
    onSaved={() => { assignModalOpen = false; refresh(); }}
    onClose={() => { assignModalOpen = false; }}
  />
{/if}

<style>
  .error { color: #a8071a; }
  .field-error { color: #a8071a; font-size: 13px; margin-left: 6px; }
  .saved-flash { color: #166534; font-size: 12px; margin-left: 6px; }
  .toolbar {
    display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px;
    padding: 8px 24px;
  }
  .back-link { font-size: 13px; }
  .task-title { font-size: 18px; margin: 0; margin-left: auto; }
  .materials-table { width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 8px; }
  .materials-table th { padding: 6px 10px; text-align: left; background: #fefce8; }
  .materials-table td { padding: 6px 10px; }
  .text-right { text-align: right; }
  .materials-table button {
    font-size: 11px; padding: 2px 6px; margin-right: 2px;
    cursor: pointer; border: 1px solid #ccc; background: #fff; border-radius: 3px;
  }
  .materials-table button:hover { background: #f0f0f0; }
</style>
