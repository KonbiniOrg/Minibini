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

  // Modal state
  let taskModalOpen = $state(false);
  let taskModalMode = $state('create-freeform');
  let taskModalTask = $state(null);

  let materialModalOpen = $state(false);
  let materialModalMode = $state('create');
  let materialModalMaterial = $state(null);
  let materialModalTaskId = $state(null);

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
    } catch (e) {
      error = e.message || 'Could not load worksheet.';
    } finally {
      loading = false;
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

  // Task modal handlers
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

  // Material modal handlers
  function openAddMaterial(task) {
    materialModalMaterial = null;
    materialModalTaskId = task.plan_task_id;
    materialModalMode = 'create';
    materialModalOpen = true;
  }

  function openEditMaterial(material, task) {
    materialModalMaterial = material;
    materialModalTaskId = task.plan_task_id;
    materialModalMode = 'edit';
    materialModalOpen = true;
  }

  async function handleDeleteMaterial(material, task) {
    if (!confirm('Delete this material?')) return;
    try {
      await api.delete(`/api/plan-tasks/${task.plan_task_id}/materials/${material.plan_material_id}/`);
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

  // Reorder handlers
  async function handleReorder(itemType, itemId, direction) {
    try {
      await api.post(`/api/est-worksheets/${worksheet.est_worksheet_id}/reorder/`, {
        item_type: itemType,
        item_id: itemId,
        direction,
      });
      await reload();
    } catch (e) {
      alert(e.message || 'Could not reorder.');
    }
  }

  // Send all atoms / open wizard
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
    } finally {
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
    <a href={`/jobs/${worksheet.job}`} use:link>&laquo; Back to Job</a>
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
    onAddMaterial={openAddMaterial}
    onEditMaterial={openEditMaterial}
    onDeleteMaterial={handleDeleteMaterial}
    onReorder={handleReorder}
  />

  <!-- Modals -->
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
</style>
