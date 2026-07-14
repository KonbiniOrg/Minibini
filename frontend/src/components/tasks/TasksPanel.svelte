<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import { canMarkWorkComplete } from '../../lib/jobActions.js';
  import { consumeMaterial, restockMaterial, drawMoreMaterial, moveMaterial }
    from '../../lib/materialOps.js';
  import MaterialFulfillmentModals from '../materials/MaterialFulfillmentModals.svelte';
  import TaskTree from '../TaskTree.svelte';
  import WorkItemForm from '../WorkItemForm.svelte';
  import MaterialModal from '../MaterialModal.svelte';
  import FeeModal from '../FeeModal.svelte';
  import ExpenseModal from '../expenses/ExpenseModal.svelte';
  import AssignModal from '../AssignModal.svelte';
  import PriceListPicker from '../PriceListPicker.svelte';
  import Modal from '../Modal.svelte';

  let { job, onJobChange = () => {} } = $props();

  let enrichedTasks = $state([]);
  let jobMaterials = $state([]);
  let jobExpenses = $state([]);
  let templates = $state([]);
  let categories = $state([]);
  let loading = $state(true);

  // Modal state
  let taskModalOpen = $state(false);
  let taskModalMode = $state('manual');
  let taskModalTask = $state(null);

  let materialModalOpen = $state(false);
  let expenseModalOpen = $state(false);
  let editingExpense = $state(null);
  function openEditExpense(exp) {
    editingExpense = exp;
    expenseModalOpen = true;
  }
  let materialModalMode = $state('create');
  let materialModalMaterial = $state(null);
  let materialModalTaskId = $state(null);
  let materialModalJobId = $state(null);

  let feeModalOpen = $state(false);
  let feeModalMode = $state('create');
  let feeModalFee = $state(null);

  let selectedTaskId = $state(null);

  let subtaskModalOpen = $state(false);
  let subtaskModalParentTaskId = $state(null);

  let assignModalOpen = $state(false);
  let assignModalTask = $state(null);

  // Picker state
  let pickerOpen = $state(false);
  let taskPresetTemplateId = $state(null);
  let taskPresetName = $state('');
  let materialPresetPli = $state(null);
  let materialPresetDescription = $state('');
  let feePresetDescription = $state('');
  let defaultMaterialCategoryId = $state(null);

  // Status action state
  let statusBusy = $state(false);
  // Blocker list returned by a Check Complete post (B4) — non-null opens
  // the "resolve these first" modal.
  let wcBlockers = $state(null);

  // Anything not final blocks work-complete: a non-terminal task, or a
  // pending material (on a task or loose). Drives the button label —
  // "Check Complete" (produces the list) vs "Mark Work Complete".
  const TERMINAL_TASK_STATUSES = ['complete', 'cancelled'];
  const hasWcBlockers = $derived.by(() => {
    const allTasks = [];
    for (const t of enrichedTasks) {
      allTasks.push(t);
      for (const s of (t.subtasks || [])) allTasks.push(s);
    }
    if (allTasks.some((t) => !TERMINAL_TASK_STATUSES.includes(t.status))) return true;
    const mats = [...jobMaterials];
    for (const t of allTasks) mats.push(...(t.materials || []));
    return mats.some(
      (m) => m.consumption_state === 'pending' && Number(m.quantity) > 0);
  });

  // Order + Mark-received flows live in the shared MaterialFulfillmentModals
  // component (bind:this exposes startOrder/startReceipt).
  let fulfillModals = $state(null);

  // Attach-expense against an existing pending material
  let attachExpenseMaterial = $state(null);

  const jobLocked = $derived(
    job && ['completed', 'cancelled', 'rejected'].includes(job.status)
  );

  // Job-derived data (materials/expenses/enriched task tree) is recomputed
  // whenever `job` changes identity — including after a parent-driven reload
  // triggered by onJobChange(), which is how a mutation's "refresh the job"
  // effect now reaches this panel (the panel no longer owns the job fetch).
  async function loadPanelData() {
    loading = true;
    try {
      jobMaterials = (job.materials || []).filter(m => !m.task);
      try {
        const expData = await api.get(`/api/expenses/?job=${job.job_id}`);
        // Material-less expenses surface at the job level (material-linked ones
        // are represented by their material in the tree).
        jobExpenses = (expData.results ?? expData);
      } catch (e) {
        jobExpenses = [];
      }
      await enrichTasks();
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
      const resp = await api.get('/api/service-items/?page_size=100');
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

  async function loadSettings() {
    try {
      const s = await api.get('/api/settings/');
      defaultMaterialCategoryId = s.default_material_accounting_category != null
        ? Number(s.default_material_accounting_category)
        : null;
    } catch (e) {
      defaultMaterialCategoryId = null;
    }
  }

  async function reload() {
    // Job-derived state (jobMaterials/jobExpenses/enrichedTasks) refreshes via
    // the effect below once the parent hands back an updated `job` prop.
    await onJobChange();
  }

  $effect(() => {
    if (job) {
      loadPanelData();
    }
  });

  // Templates/categories/settings don't depend on job identity — load once,
  // not on every mutation-triggered reload (matches the old page's behavior:
  // these only loaded on the params.id mount effect, never from reload()).
  $effect(() => {
    loadTemplates();
    loadCategories();
    loadSettings();
  });

  // Picker surface handler
  function handleChoose(choice) {
    pickerOpen = false;
    if (choice.type === 'service') {
      taskModalTask = null;
      taskModalMode = 'template';
      taskPresetTemplateId = choice.serviceItem.template_id;
      taskPresetName = '';
      taskModalOpen = true;
    } else if (choice.type === 'freeform-task') {
      // Manual/freeform task — WorkItemForm's manual mode; user picks the rate
      // scheme there. Typed text seeds the name.
      taskModalTask = null;
      taskModalMode = 'manual';
      taskPresetTemplateId = null;
      taskPresetName = choice.typed;
      taskModalOpen = true;
    } else if (choice.type === 'inventory') {
      materialModalMaterial = null;
      materialModalTaskId = null;
      materialModalJobId = job.job_id;
      materialModalMode = 'create';
      materialPresetPli = choice.inventoryItem;
      materialPresetDescription = '';
      materialModalOpen = true;
    } else if (choice.isMaterial) {
      materialModalMaterial = null;
      materialModalTaskId = null;
      materialModalJobId = job.job_id;
      materialModalMode = 'create';
      materialPresetPli = null;
      materialPresetDescription = choice.typed;
      materialModalOpen = true;
    } else {
      feeModalFee = null;
      feeModalMode = 'create';
      feePresetDescription = choice.typed;
      feeModalOpen = true;
    }
  }

  // Task modal handlers
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
      showError(errorMessage(e, 'Could not delete task.'));
    }
  }

  async function handleCancelTask(task) {
    if (!confirm(`Cancel task "${task.name}"?`)) return;
    try {
      await api.post(`/api/tasks/${task.task_id}/cancel/`);
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not cancel task.'));
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

  function openEditMaterial(material, task) {
    materialModalMaterial = material;
    materialModalTaskId = task ? task.task_id : null;
    materialModalJobId = task ? null : job.job_id;
    materialModalMode = 'edit';
    materialModalOpen = true;
  }

  // Per-material handlers — shared lib functions (lib/materialOps.js).
  const handleConsumeMaterial = (material) => consumeMaterial(material, reload);
  const handleRestockMaterial = (material) => restockMaterial(material, reload);
  const handleDrawMoreMaterial = (material) => drawMoreMaterial(material, reload);
  async function handleMoveMaterial(material, taskId) {
    await moveMaterial(material, taskId, reload);
    selectedTaskId = null;
  }

  function openAttachExpense(material) {
    attachExpenseMaterial = material;
  }

  function handleMaterialSaved() {
    materialModalOpen = false;
    materialModalMaterial = null;
    materialModalTaskId = null;
    materialModalJobId = null;
    reload();
  }

  // Fee modal handlers
  function openEditFee(fee) {
    feeModalFee = fee;
    feeModalMode = 'edit';
    feeModalOpen = true;
  }

  function handleFeeSaved() {
    feeModalOpen = false;
    feeModalFee = null;
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
      showError(errorMessage(e, 'Could not reorder.'));
    }
  }

  // Task click -> navigate to task detail
  function handleTaskClick(task) {
    if (job) {
      window.location.hash = `/jobs/${job.job_id}/tasks/${task.task_id}`;
    }
  }

  // Mark all work complete — or, with blockers, fetch the list of what
  // still needs attention (the server mutates nothing and answers with
  // `blockers`; the client-side label is a hint, the server is the truth).
  async function handleWorkComplete() {
    if (!hasWcBlockers && !confirm('Mark all work complete on this job?')) return;
    statusBusy = true;
    try {
      const resp = await api.post(`/api/jobs/${job.job_id}/work-complete/`, {});
      if (resp && resp.blockers) {
        wcBlockers = resp.blockers;
        return;
      }
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not mark work complete.'));
    } finally {
      statusBusy = false;
    }
  }
</script>

{#if loading}
  <p>Loading...</p>
{:else}
  <div class="page-body">
  <div class="toolbar">
    {#if !jobLocked}
      {#if !job?.on_hold}
        <button type="button" onclick={() => { pickerOpen = true; }}>Add Work</button>
      {/if}
      <button type="button" onclick={() => { editingExpense = null; expenseModalOpen = true; }}>Add Expense</button>
    {/if}
    {#if job?.can_manage && canMarkWorkComplete(job)}
      <button type="button" onclick={handleWorkComplete} disabled={statusBusy}>
        {hasWcBlockers ? 'Check Complete' : 'Mark Work Complete'}
      </button>
    {/if}
  </div>

  <TaskTree
    tasks={enrichedTasks}
    {jobMaterials}
    readonly={false}
    {jobLocked}
    jobOnHold={job?.on_hold ?? false}
    canManage={job?.can_manage}
    onEditTask={openEditTask}
    onDeleteTask={handleDeleteTask}
    onAddMaterial={openAddMaterial}
    onEditMaterial={openEditMaterial}
    onConsumeMaterial={handleConsumeMaterial}
    onRestockMaterial={handleRestockMaterial}
    onDrawMoreMaterial={handleDrawMoreMaterial}
    onOrderMaterial={(m) => fulfillModals?.startOrder(m)}
    onMarkOnHand={(m) => fulfillModals?.startReceipt(m)}
    onAttachExpense={openAttachExpense}
    onAddSubtask={openAddSubtask}
    onReorder={handleReorder}
    onTaskClick={handleTaskClick}
    onAssignTask={(task) => { assignModalTask = task; assignModalOpen = true; }}
    onCancelTask={handleCancelTask}
    onMoveMaterial={handleMoveMaterial}
    expenses={jobExpenses}
    onEditExpense={openEditExpense}
    fees={job.fees || []}
    onEditFee={openEditFee}
    bind:selectedTaskId
  />

  <!-- Fees now render inside the TaskTree table (above), included in the grand total. -->

  <!-- Modals -->
  <WorkItemForm
    open={taskModalOpen}
    mode={taskModalMode}
    context="job"
    contextId={job.job_id}
    item={taskModalTask}
    isEdit={!!taskModalTask}
    {templates}
    presetTemplateId={taskPresetTemplateId}
    presetName={taskPresetName}
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
    presetDescription={materialPresetDescription}
    presetPli={materialPresetPli}
    {defaultMaterialCategoryId}
    onSaved={handleMaterialSaved}
    onClose={() => { materialModalOpen = false; }}
  />

  <FeeModal
    open={feeModalOpen}
    mode={feeModalMode}
    fee={feeModalFee}
    jobId={job.job_id}
    {categories}
    presetDescription={feePresetDescription}
    onSaved={handleFeeSaved}
    onClose={() => { feeModalOpen = false; }}
  />

  <PriceListPicker open={pickerOpen} onChoose={handleChoose} onclose={() => { pickerOpen = false; }} taskSurface={true} />

  <ExpenseModal
    open={expenseModalOpen}
    expense={editingExpense}
    initialJob={job ? { job_id: job.job_id, job_number: job.job_number } : null}
    onSaved={() => { expenseModalOpen = false; editingExpense = null; reload(); }}
    onClose={() => { expenseModalOpen = false; editingExpense = null; }}
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

  <!-- Order chooser + Mark-received receipt dialogs (shared component). -->
  <MaterialFulfillmentModals bind:this={fulfillModals} onDone={reload} />

  <!-- Work-complete blockers (B4): informational list, no bulk actions —
       each task/material resolves through its normal flow. -->
  <Modal open={wcBlockers != null} onCancel={() => { wcBlockers = null; }} maxWidth="480px" label="Not ready to complete">
    <h3>Not ready to complete</h3>
    <p class="dialog-hint">
      Resolve these first — complete or cancel the open tasks, and consume
      or release the pending materials.
    </p>
    {#if wcBlockers?.tasks?.length}
      <h4>Open tasks</h4>
      <ul class="blocker-list">
        {#each wcBlockers.tasks as t (t.task_id)}
          <li>{t.name} <small class="blocker-status">({t.status})</small></li>
        {/each}
      </ul>
    {/if}
    {#if wcBlockers?.materials?.length}
      <h4>Pending materials</h4>
      <ul class="blocker-list">
        {#each wcBlockers.materials as m (m.material_id)}
          <li>{m.description || `Material ${m.material_id}`}</li>
        {/each}
      </ul>
    {/if}
    <p class="dialog-actions">
      <button type="button" onclick={() => { wcBlockers = null; }}>Close</button>
    </p>
  </Modal>

  <ExpenseModal
    open={attachExpenseMaterial != null}
    initialJob={job ? { job_id: job.job_id, job_number: job.job_number } : null}
    initialMaterial={attachExpenseMaterial}
    onSaved={() => { attachExpenseMaterial = null; reload(); }}
    onClose={() => { attachExpenseMaterial = null; }}
  />
  </div>
{/if}

<style>
  /* .toolbar (and its buttons) come from app.css. */

  .dialog-hint { color: #555; font-size: 13px; }
  .blocker-list { margin: 4px 0 12px; padding-left: 20px; }
  .blocker-list li { margin: 2px 0; }
  .blocker-status { color: #888; }
  .dialog-actions { display: flex; gap: 8px; margin-top: 12px; }
  .dialog-actions button {
    padding: 6px 14px; border: 1px solid #d1d5db; border-radius: 4px;
    background: #fff; cursor: pointer; font-size: 13px;
  }
  .dialog-actions button:hover { background: #f3f4f6; }
  .dialog-actions button:disabled { opacity: 0.5; cursor: default; }
</style>
