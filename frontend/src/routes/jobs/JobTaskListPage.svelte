<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import TaskTree from '../../components/TaskTree.svelte';
  import WorkItemForm from '../../components/WorkItemForm.svelte';
  import MaterialModal from '../../components/MaterialModal.svelte';
  import AssignModal from '../../components/AssignModal.svelte';
  import JobHeader from '../../components/jobs/JobHeader.svelte';

  let { params = {} } = $props();

  let job = $state(null);
  let contact = $state(null);
  let enrichedTasks = $state([]);
  let jobMaterials = $state([]);
  let templates = $state([]);
  let categories = $state([]);
  let loading = $state(true);
  let error = $state('');

  // Modal state
  let taskModalOpen = $state(false);
  let taskModalMode = $state('manual');
  let taskModalTask = $state(null);

  let materialModalOpen = $state(false);
  let materialModalMode = $state('create');
  let materialModalMaterial = $state(null);
  let materialModalTaskId = $state(null);
  let materialModalJobId = $state(null);

  let selectedTaskId = $state(null);

  let subtaskModalOpen = $state(false);
  let subtaskModalParentTaskId = $state(null);

  let assignModalOpen = $state(false);
  let assignModalTask = $state(null);

  // Status action state
  let statusBusy = $state(false);

  const canManageJobs = $derived(
    $userStore?.permissions?.includes('can_manage_jobs') ?? false
  );
  const jobLocked = $derived(
    job && ['completed', 'cancelled', 'rejected'].includes(job.status)
  );

  async function loadJob() {
    loading = true;
    error = '';
    try {
      job = await api.get(`/api/jobs/${params.id}/`);
      jobMaterials = (job.materials || []).filter(m => !m.task);
      await enrichTasks();
      if (job.contact) {
        try {
          contact = await api.get(`/api/contacts/${job.contact}/`);
        } catch (e) {
          contact = null;
        }
      }
    } catch (e) {
      error = e.message || 'Could not load job.';
    } finally {
      loading = false;
    }
  }

  async function enrichTasks() {
    if (!job || !job.tasks) {
      enrichedTasks = [];
      return;
    }
    // Only top-level tasks (subtasks are fetched and nested separately)
    const tasks = (job.tasks || []).filter(t => !t.parent_task);
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
    await loadJob();
  }

  $effect(() => {
    if (params.id) {
      loadJob();
      loadTemplates();
      loadCategories();
    }
  });

  // Task modal handlers
  function openAddManualTask() {
    taskModalTask = null;
    taskModalMode = 'manual';
    taskModalOpen = true;
  }

  function openAddTemplateTask() {
    taskModalTask = null;
    taskModalMode = 'template';
    taskModalOpen = true;
  }

  function openEditTask(task) {
    taskModalTask = task;
    taskModalMode = 'manual';
    taskModalOpen = true;
  }

  async function handleDeleteTask(task) {
    if (!confirm(`Delete task "${task.name}"?`)) return;
    try {
      await api.delete(`/api/jobs/${job.job_id}/tasks/${task.task_id}/`);
      await reload();
    } catch (e) {
      alert(e.message || 'Could not delete task.');
    }
  }

  async function handleCancelTask(task) {
    if (!confirm(`Cancel task "${task.name}"?`)) return;
    try {
      await api.post(`/api/tasks/${task.task_id}/cancel/`);
      await reload();
    } catch (e) {
      alert(e.message || 'Could not cancel task.');
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
    materialModalJobId = null;
    materialModalMode = 'create';
    materialModalOpen = true;
  }

  function openAddJobMaterial() {
    materialModalMaterial = null;
    materialModalTaskId = null;
    materialModalJobId = job.job_id;
    materialModalMode = 'create';
    materialModalOpen = true;
  }

  function openEditMaterial(material, task) {
    materialModalMaterial = material;
    materialModalTaskId = task ? task.task_id : null;
    materialModalJobId = task ? null : job.job_id;
    materialModalMode = 'edit';
    materialModalOpen = true;
  }

  async function handleConsumeMaterial(material, _task) {
    // No confirm: reversible via the sibling Restock action.
    try {
      await api.post(`/api/materials/${material.material_id}/consume/`, {});
      await reload();
    } catch (e) {
      alert(e.message || 'Could not consume.');
    }
  }

  async function handleRestockMaterial(material, _task) {
    const raw = window.prompt(`Restock quantity (max ${material.quantity}):`, material.quantity);
    if (raw === null) return;
    const quantity = raw.trim();
    if (!quantity) return;
    try {
      await api.post(`/api/materials/${material.material_id}/restock/`, { quantity });
      await reload();
    } catch (e) {
      alert(e.message || 'Could not restock.');
    }
  }

  async function handleDrawMoreMaterial(material, _task) {
    const raw = window.prompt('Draw more quantity:', '1');
    if (raw === null) return;
    const quantity = raw.trim();
    if (!quantity) return;
    try {
      await api.post(`/api/materials/${material.material_id}/draw-more/`, { quantity });
      await reload();
    } catch (e) {
      alert(e.message || 'Could not draw more.');
    }
  }

  async function handleMoveMaterial(material, taskId) {
    try {
      await api.post(`/api/materials/${material.material_id}/assign-task/`, { task: taskId });
      selectedTaskId = null;
      await reload();
    } catch (e) {
      alert(e.message || 'Could not move material.');
    }
  }

  function handleMaterialSaved() {
    materialModalOpen = false;
    materialModalMaterial = null;
    materialModalTaskId = null;
    materialModalJobId = null;
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
      await api.post(`/api/jobs/${job.job_id}/reorder-tasks/`, {
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
    if (job) {
      window.location.hash = `/jobs/${job.job_id}/tasks/${task.task_id}`;
    }
  }

  // Mark all work complete
  async function handleWorkComplete() {
    if (!confirm('Mark all work complete on this job?')) return;
    statusBusy = true;
    try {
      await api.post(`/api/jobs/${job.job_id}/work-complete/`, {});
      await reload();
    } catch (e) {
      alert(e.message || 'Could not mark work complete.');
    } finally {
      statusBusy = false;
    }
  }
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p class="error">{error}</p>
{:else if job}
  <JobHeader {job} {contact} onStatusChange={reload} />

  <div class="toolbar">
    <a href={`/jobs/${job.job_id}`} use:link class="back-link">&laquo; back to overview</a>
    {#if !jobLocked}
      <button type="button" onclick={openAddTemplateTask}>Add Task From Template</button>
      <button type="button" onclick={openAddManualTask}>Add Manual Task</button>
      <button type="button" onclick={openAddJobMaterial}>Add Material</button>
    {/if}
    {#if canManageJobs}
      <button type="button" onclick={handleWorkComplete} disabled={statusBusy}>Mark Work Complete</button>
    {/if}
  </div>

  <TaskTree
    tasks={enrichedTasks}
    {jobMaterials}
    readonly={false}
    {jobLocked}
    onEditTask={openEditTask}
    onDeleteTask={handleDeleteTask}
    onAddMaterial={openAddMaterial}
    onEditMaterial={openEditMaterial}
    onConsumeMaterial={handleConsumeMaterial}
    onRestockMaterial={handleRestockMaterial}
    onDrawMoreMaterial={handleDrawMoreMaterial}
    onAddSubtask={openAddSubtask}
    onReorder={handleReorder}
    onTaskClick={handleTaskClick}
    onAssignTask={(task) => { assignModalTask = task; assignModalOpen = true; }}
    onCancelTask={handleCancelTask}
    onMoveMaterial={handleMoveMaterial}
    bind:selectedTaskId
  />

  <!-- Modals -->
  <WorkItemForm
    open={taskModalOpen}
    mode={taskModalMode}
    context="job"
    contextId={job.job_id}
    item={taskModalTask}
    isEdit={!!taskModalTask}
    {templates}
    onSaved={handleTaskSaved}
    onClose={() => { taskModalOpen = false; }}
  />

  <MaterialModal
    open={materialModalOpen}
    mode={materialModalMode}
    material={materialModalMaterial}
    taskId={materialModalTaskId}
    jobId={materialModalJobId}
    {categories}
    onSaved={handleMaterialSaved}
    onClose={() => { materialModalOpen = false; }}
  />

  <WorkItemForm
    open={subtaskModalOpen}
    mode="manual"
    context="subtask"
    contextId={subtaskModalParentTaskId}
    templates={[]}
    onSaved={handleSubtaskSaved}
    onClose={() => { subtaskModalOpen = false; }}
  />

  <AssignModal
    open={assignModalOpen}
    task={assignModalTask}
    onSaved={() => { assignModalOpen = false; assignModalTask = null; reload(); }}
    onClose={() => { assignModalOpen = false; assignModalTask = null; }}
  />
{/if}

<style>
  .error { color: #a8071a; }
  .toolbar {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
    padding: 8px 24px;
  }
  .back-link { font-size: 13px; }
  .toolbar button {
    padding: 6px 14px; border: 1px solid #d1d5db; border-radius: 4px;
    background: #fff; cursor: pointer; font-size: 13px;
  }
  .toolbar button:hover { background: #f3f4f6; }
  .toolbar button:disabled { opacity: 0.5; cursor: default; }
</style>
