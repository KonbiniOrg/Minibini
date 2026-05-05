<script>
  import { link, push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import WorksheetTaskTable from '../../components/WorksheetTaskTable.svelte';
  import PlanTaskModal from '../../components/PlanTaskModal.svelte';
  import PlanMaterialModal from '../../components/PlanMaterialModal.svelte';

  let { params = {} } = $props();

  let worksheet = $state(null);
  let templates = $state([]);
  let categories = $state([]);
  let loading = $state(true);
  let error = $state('');

  let taskModalOpen = $state(false);
  let taskModalMode = $state('create-freeform');
  let taskModalTask = $state(null);

  let materialModalOpen = $state(false);
  let materialModalMode = $state('create');
  let materialModalMaterial = $state(null);
  let materialModalTaskId = $state(null);

  let materials = $state([]);
  let selectedTaskId = $state(null);

  const canManageJobs = $derived(
    $userStore?.permissions?.includes('can_manage_jobs') ?? false
  );
  const isDraft = $derived(worksheet?.status === 'draft');
  const canEdit = $derived(canManageJobs && isDraft);

  async function loadWorksheet() {
    loading = true;
    error = '';
    try {
      worksheet = await api.get(`/api/est-worksheets/${params.id}/`);
      await loadMaterials();
    } catch (e) {
      error = e.message || 'Could not load worksheet.';
    } finally {
      loading = false;
    }
  }

  async function loadMaterials() {
    try {
      const all = await api.get(`/api/est-worksheets/${params.id}/plan-materials/`);
      materials = all.filter(m => !m.plan_task);
    } catch (e) {
      materials = [];
    }
  }

  async function loadTemplates() {
    try {
      const resp = await api.get('/api/task-templates/?page_size=100');
      templates = resp.results || resp;
    } catch (e) {
      templates = [];
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

  async function reload() {
    await loadWorksheet();
  }

  $effect(() => {
    if (params.id) {
      loadWorksheet();
      loadTemplates();
      loadCategories();
    }
  });

  function openAddTask() {
    taskModalTask = null;
    taskModalMode = 'create-freeform';
    taskModalOpen = true;
  }

  function openEditTask(task) {
    taskModalTask = task;
    taskModalMode = 'edit';
    taskModalOpen = true;
  }

  async function handleDeleteTask(task) {
    if (!confirm(`Delete task "${task.name}"?`)) return;
    try {
      await api.delete(`/api/est-worksheets/${worksheet.est_worksheet_id}/tasks/${task.plan_task_id}/`);
      await reload();
    } catch (e) {
      alert(e.message || 'Could not delete task.');
    }
  }

  function handleTaskSaved() {
    taskModalOpen = false;
    taskModalTask = null;
    reload();
  }

  function openAddMaterial() {
    materialModalMaterial = null;
    materialModalTaskId = null;
    materialModalMode = 'create';
    materialModalOpen = true;
  }

  function openEditMaterial(mat, task = null) {
    materialModalMaterial = mat;
    materialModalTaskId = task ? task.plan_task_id : null;
    materialModalMode = 'edit';
    materialModalOpen = true;
  }

  function openAddTaskMaterial(task) {
    materialModalMaterial = null;
    materialModalTaskId = task.plan_task_id;
    materialModalMode = 'create';
    materialModalOpen = true;
  }

  async function handleDeleteMaterial(mat, task = null) {
    if (!confirm(`Delete material "${mat.description || 'No description'}"?`)) return;
    try {
      if (task) {
        await api.delete(`/api/plan-tasks/${task.plan_task_id}/materials/${mat.plan_material_id}/`);
      } else {
        await api.delete(`/api/est-worksheets/${worksheet.est_worksheet_id}/plan-materials/${mat.plan_material_id}/`);
      }
      await reload();
    } catch (e) {
      alert(e.message || 'Could not delete material.');
    }
  }

  function handleMaterialSaved() {
    materialModalOpen = false;
    materialModalMaterial = null;
    materialModalTaskId = null;
    reload();
  }

  async function handleMoveMaterial(material, planTaskId) {
    try {
      await api.post(
        `/api/est-worksheets/${worksheet.est_worksheet_id}/plan-materials/${material.plan_material_id}/assign-task/`,
        { plan_task: planTaskId },
      );
      selectedTaskId = null;
      await reload();
    } catch (e) {
      alert(e.message || 'Could not move material.');
    }
  }

  async function handleReorder(taskId, direction) {
    try {
      await api.post(`/api/est-worksheets/${worksheet.est_worksheet_id}/reorder/`, {
        item_type: 'task',
        item_id: taskId,
        direction,
      });
      await reload();
    } catch (e) {
      alert(e.message || 'Could not reorder.');
    }
  }

  let sendingAll = $state(false);

  async function sendAllAtoms() {
    if (!confirm('Send all unclaimed atoms to the estimate as 1:1 line items?')) return;
    sendingAll = true;
    try {
      const result = await api.post(
        `/api/est-worksheets/${params.id}/send-all-atoms-to-estimate/`
      );
      push(`/estimates/${result.estimate_id}`);
    } catch (e) {
      alert(e.message || 'Failed to send atoms');
      sendingAll = false;
    }
  }

  async function openWizard() {
    try {
      const result = await api.post(
        `/api/est-worksheets/${params.id}/send-all-atoms-to-estimate/`
      );
      push(`/estimates/${result.estimate_id}/wizard`);
    } catch (e) {
      alert(e.message || 'Failed to open wizard');
    }
  }
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p class="error">{error}</p>
{:else if worksheet}
  <h2>Worksheet v{worksheet.version}</h2>

  <p>
    <a href={`/jobs/${worksheet.job}`} use:link>&laquo; Back to Job {worksheet.job_number}{worksheet.job_name ? ` - ${worksheet.job_name}` : ''}</a>
  </p>

  <div class="status-line">
    <span class="status-badge status-{worksheet.status}">{worksheet.status}</span>
    <span class="meta">
      Created {new Date(worksheet.created_date).toLocaleDateString()}
    </span>
  </div>

  {#if canEdit}
    <div class="action-bar">
      <button type="button" onclick={openAddTask}>Add Task</button>
      <button type="button" onclick={openAddMaterial}>Add Material</button>
      <button type="button" onclick={sendAllAtoms} disabled={sendingAll}>
        {sendingAll ? 'Sending…' : 'Send all atoms to estimate'}
      </button>
      <button type="button" onclick={openWizard}>Open wizard to group atoms</button>
    </div>
  {/if}

  <WorksheetTaskTable
    {worksheet}
    readonly={!canEdit}
    onEditTask={openEditTask}
    onDeleteTask={handleDeleteTask}
    onReorder={handleReorder}
    onAddMaterial={openAddTaskMaterial}
    onEditMaterial={openEditMaterial}
    onDeleteMaterial={handleDeleteMaterial}
    onMoveMaterial={handleMoveMaterial}
    bind:selectedTaskId
  />

  {#if materials.length > 0 || canEdit}
    <h3>Materials</h3>
    {#if materials.length === 0}
      <p class="empty-msg">No taskless materials.</p>
    {:else}
      <table border="1" class="mat-table">
        <thead>
          <tr>
            {#if canEdit}<th>Move target</th>{/if}
            <th>Description</th>
            <th class="text-right">Qty</th>
            <th class="text-right">Unit Cost</th>
            <th class="text-right">Sell Price</th>
            {#if canEdit}<th>Actions</th>{/if}
          </tr>
        </thead>
        <tbody>
          {#each materials as mat}
            <tr>
              {#if canEdit}
                <td class="move-cell">{#if selectedTaskId != null}<button type="button" class="small-btn" onclick={() => handleMoveMaterial(mat, selectedTaskId)}>Move</button>{/if}</td>
              {/if}
              <td>{mat.description || '(no description)'}</td>
              <td class="text-right">{mat.quantity ?? '-'}</td>
              <td class="text-right">{mat.unit_cost ? `$${Number(mat.unit_cost).toFixed(2)}` : '-'}</td>
              <td class="text-right">{mat.sell_price ? `$${Number(mat.sell_price).toFixed(2)}` : '-'}</td>
              {#if canEdit}
                <td class="actions-cell">
                  <button type="button" onclick={() => openEditMaterial(mat)}>edit</button>
                  <button type="button" onclick={() => handleDeleteMaterial(mat)}>del</button>
                </td>
              {/if}
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  {/if}

  <PlanTaskModal
    open={taskModalOpen}
    mode={taskModalMode}
    task={taskModalTask}
    worksheetId={worksheet.est_worksheet_id}
    {templates}
    {categories}
    onSaved={handleTaskSaved}
    onClose={() => { taskModalOpen = false; }}
  />

  <PlanMaterialModal
    open={materialModalOpen}
    mode={materialModalMode}
    material={materialModalMaterial}
    worksheetId={worksheet.est_worksheet_id}
    planTaskId={materialModalTaskId}
    {categories}
    onSaved={handleMaterialSaved}
    onClose={() => { materialModalOpen = false; }}
  />
{/if}

<style>
  .error { color: #a8071a; }
  .status-line { margin-bottom: 16px; display: flex; align-items: center; gap: 12px; }
  .status-badge {
    padding: 4px 12px; border-radius: 12px; font-size: 13px;
    font-weight: 600; text-transform: capitalize;
  }
  .status-draft { background: #f3f4f6; color: #374151; }
  .status-final { background: #e0e7ff; color: #4338ca; }
  .status-superseded { background: #fef3c7; color: #92400e; }
  .meta { color: #888; font-size: 13px; }
  .action-bar { display: flex; gap: 8px; margin-bottom: 16px; }
  .action-bar button {
    padding: 6px 14px; border: 1px solid #d1d5db; border-radius: 4px;
    background: #fff; cursor: pointer; font-size: 13px;
  }
  .action-bar button:hover { background: #f3f4f6; }
  .action-bar button:disabled { opacity: 0.5; cursor: default; }

  .mat-table { width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 8px; }
  .mat-table th { padding: 8px 10px; text-align: left; background: #fef3c7; color: #78350f; }
  .mat-table td { padding: 6px 10px; vertical-align: top; }
  .mat-table .text-right { text-align: right; }
  .mat-table .actions-cell button {
    font-size: 11px; padding: 2px 6px; margin-right: 2px;
    cursor: pointer; border: 1px solid #ccc; background: #fff; border-radius: 3px;
  }
  .mat-table .actions-cell button:hover { background: #f0f0f0; }
  .mat-table .move-cell { text-align: center; width: 90px; }
  .small-btn {
    font-size: 11px; padding: 2px 6px;
    cursor: pointer; border: 1px solid #ccc; background: #fff; border-radius: 3px;
  }
  .small-btn:hover { background: #f0f0f0; }
  .empty-msg { color: #888; }
</style>
