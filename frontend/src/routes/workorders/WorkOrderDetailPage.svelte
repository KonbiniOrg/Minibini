<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import TaskTree from '../../components/TaskTree.svelte';
  import TaskModal from '../../components/TaskModal.svelte';
  import MaterialModal from '../../components/MaterialModal.svelte';
  import SubtaskModal from '../../components/SubtaskModal.svelte';

  let { params = {} } = $props();

  let workOrder = $state(null);
  let enrichedTasks = $state([]);
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

  let subtaskModalOpen = $state(false);
  let subtaskModalParentTaskId = $state(null);

  // Status action state
  let statusBusy = $state(false);
  let reasonText = $state('');

  const canManageJobs = $derived(
    $userStore?.permissions?.includes('can_manage_jobs') ?? false
  );

  async function loadWorkOrder() {
    loading = true;
    error = '';
    try {
      workOrder = await api.get(`/api/work-orders/${params.id}/`);
      await enrichTasks();
    } catch (e) {
      error = e.message || 'Could not load work order.';
    } finally {
      loading = false;
    }
  }

  async function enrichTasks() {
    if (!workOrder || !workOrder.tasks) {
      enrichedTasks = [];
      return;
    }
    // Only top-level tasks (subtasks are fetched and nested separately)
    const tasks = (workOrder.tasks || []).filter(t => !t.parent_task);
    const enriched = await Promise.all(tasks.map(async (task) => {
      const [materials, subtasks] = await Promise.all([
        fetchMaterials(task.task_id),
        fetchSubtasks(task.task_id),
      ]);
      // Enrich subtasks with their materials
      const enrichedSubs = await Promise.all(subtasks.map(async (sub) => {
        const subMaterials = await fetchMaterials(sub.task_id);
        return { ...sub, materials: subMaterials };
      }));
      return { ...task, materials, subtasks: enrichedSubs };
    }));
    enrichedTasks = enriched;
  }

  async function fetchMaterials(taskId) {
    try {
      return await api.get(`/api/tasks/${taskId}/materials/`);
    } catch (e) {
      return [];
    }
  }

  async function fetchSubtasks(taskId) {
    try {
      return await api.get(`/api/tasks/${taskId}/subtasks/`);
    } catch (e) {
      return [];
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
    await loadWorkOrder();
  }

  $effect(() => {
    if (params.id) {
      loadWorkOrder();
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
      await api.delete(`/api/work-orders/${workOrder.work_order_id}/tasks/${task.task_id}/`);
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
    materialModalTaskId = task.task_id;
    materialModalMode = 'create';
    materialModalOpen = true;
  }

  function openEditMaterial(material, task) {
    materialModalMaterial = material;
    materialModalTaskId = task.task_id;
    materialModalMode = 'edit';
    materialModalOpen = true;
  }

  async function handleDeleteMaterial(material, task) {
    if (!confirm('Delete this material?')) return;
    try {
      await api.delete(`/api/tasks/${task.task_id}/materials/${material.material_id}/`);
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

  // Subtask modal handlers
  function openAddSubtask(task) {
    subtaskModalParentTaskId = task.task_id;
    subtaskModalOpen = true;
  }

  function handleSubtaskSaved() {
    subtaskModalOpen = false;
    subtaskModalParentTaskId = null;
    reload();
  }

  // Reorder handler
  async function handleReorder(taskId, direction) {
    try {
      await api.post(`/api/work-orders/${workOrder.work_order_id}/reorder/`, {
        task_id: taskId,
        direction,
      });
      await reload();
    } catch (e) {
      alert(e.message || 'Could not reorder.');
    }
  }

  // Task click -> navigate to task detail
  function handleTaskClick(task) {
    if (workOrder && workOrder.job) {
      window.location.hash = `/jobs/${workOrder.job}/tasks/${task.task_id}`;
    }
  }

  // Status transitions
  async function handleStatusAction(actionName) {
    const reason = prompt('Reason (optional):');
    if (reason === null) return; // cancelled
    statusBusy = true;
    try {
      await api.post(`/api/work-orders/${workOrder.work_order_id}/${actionName}/`, {
        reason: reason || undefined,
      });
      await reload();
    } catch (e) {
      alert(e.message || `Could not ${actionName} work order.`);
    } finally {
      statusBusy = false;
    }
  }
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p class="error">{error}</p>
{:else if workOrder}
  <h2>Work Order #{workOrder.work_order_id}</h2>

  <p>
    <a href={`/jobs/${workOrder.job}`} use:link>&laquo; Back to Job</a>
  </p>

  <div class="status-line">
    <span class="status-badge status-{workOrder.status}">{workOrder.status}</span>
    {#if workOrder.template_name}
      <span class="meta">Template: {workOrder.template_name}</span>
    {/if}
  </div>

  {#if canManageJobs}
    <div class="action-bar">
      {#if workOrder.status === 'incomplete' || workOrder.status === 'blocked'}
        <button type="button" onclick={() => handleStatusAction('complete')} disabled={statusBusy}>Complete</button>
      {/if}
      {#if workOrder.status === 'incomplete'}
        <button type="button" onclick={() => handleStatusAction('block')} disabled={statusBusy}>Block</button>
      {/if}
      {#if workOrder.status === 'complete' || workOrder.status === 'blocked'}
        <button type="button" onclick={() => handleStatusAction('reopen')} disabled={statusBusy}>Reopen</button>
      {/if}
    </div>
  {/if}

  <div class="action-bar">
    <button type="button" onclick={openAddTask}>Add Task</button>
  </div>

  <TaskTree
    tasks={enrichedTasks}
    readonly={false}
    onEditTask={openEditTask}
    onDeleteTask={handleDeleteTask}
    onAddMaterial={openAddMaterial}
    onEditMaterial={openEditMaterial}
    onDeleteMaterial={handleDeleteMaterial}
    onAddSubtask={openAddSubtask}
    onReorder={handleReorder}
    onTaskClick={handleTaskClick}
  />

  <!-- Modals -->
  <TaskModal
    open={taskModalOpen}
    mode={taskModalMode}
    task={taskModalTask}
    workOrderId={workOrder.work_order_id}
    {templates}
    {categories}
    onSaved={handleTaskSaved}
    onClose={() => { taskModalOpen = false; }}
  />

  <MaterialModal
    open={materialModalOpen}
    mode={materialModalMode}
    material={materialModalMaterial}
    taskId={materialModalTaskId}
    {categories}
    onSaved={handleMaterialSaved}
    onClose={() => { materialModalOpen = false; }}
  />

  <SubtaskModal
    open={subtaskModalOpen}
    parentTaskId={subtaskModalParentTaskId}
    onSaved={handleSubtaskSaved}
    onClose={() => { subtaskModalOpen = false; }}
  />
{/if}

<style>
  .error { color: #a8071a; }
  .status-line { margin-bottom: 16px; display: flex; align-items: center; gap: 12px; }
  .status-badge {
    padding: 4px 12px; border-radius: 12px; font-size: 13px;
    font-weight: 600; text-transform: capitalize;
  }
  .status-incomplete { background: #f3f4f6; color: #374151; }
  .status-complete { background: #d1fae5; color: #065f46; }
  .status-blocked { background: #fee2e2; color: #991b1b; }
  .meta { color: #888; font-size: 13px; }
  .action-bar { display: flex; gap: 8px; margin-bottom: 16px; }
  .action-bar button {
    padding: 6px 14px; border: 1px solid #d1d5db; border-radius: 4px;
    background: #fff; cursor: pointer; font-size: 13px;
  }
  .action-bar button:hover { background: #f3f4f6; }
  .action-bar button:disabled { opacity: 0.5; cursor: default; }
</style>
