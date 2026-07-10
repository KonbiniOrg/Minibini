<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { showError, showSuccess } from '../../stores/messages.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { orderPrefillQty } from '../../lib/materials.js';
  import { canMarkWorkComplete } from '../../lib/jobActions.js';
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

  // Order flow — draft-PO chooser dialog
  let orderDialogOpen = $state(false);
  let orderMaterial = $state(null);
  let orderDrafts = $state([]);
  let orderBusy = $state(false);

  // Receipt qty prompt — shared by "Mark on-hand" (quiet) and "Mark received"
  // (customer-supplied), both hitting the mark-on-hand endpoint.
  let receiptDialogOpen = $state(false);
  let receiptMaterial = $state(null);
  let receiptQty = $state('');
  let receiptBusy = $state(false);

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

  async function handleConsumeMaterial(material, _task) {
    // No confirm: reversible via the sibling Restock action.
    try {
      await api.post(`/api/materials/${material.material_id}/consume/`, {});
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not consume.'));
    }
  }

  async function handleRestockMaterial(material, _task) {
    // Same predicate as TaskTree.restockLabel: with stock on hand this reads
    // as returning it; otherwise it's a release of the planned quantity.
    const verb = material.inventory_item != null && Number(material.qty_on_hand) > 0
      ? 'Restock' : 'Release';
    const raw = window.prompt(`${verb} quantity (max ${material.quantity}):`, material.quantity);
    if (raw === null) return;
    const quantity = raw.trim();
    if (!quantity) return;
    try {
      await api.post(`/api/materials/${material.material_id}/restock/`, { quantity });
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not restock.'));
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
      showError(errorMessage(e, 'Could not draw more.'));
    }
  }

  async function handleMoveMaterial(material, taskId) {
    try {
      await api.post(`/api/materials/${material.material_id}/assign-task/`, { task: taskId });
      selectedTaskId = null;
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not move material.'));
    }
  }

  // Order flow. Zero open drafts → POST immediately (starts a new PO). One or
  // more → open the chooser so the user can append to an existing draft or
  // start a new one. Reversible process step: no confirm() dialog.
  async function startOrder(material) {
    try {
      const resp = await api.get('/api/purchase-orders/?status=draft&page_size=100');
      const drafts = resp.results || resp;
      if (!drafts.length) {
        await submitOrder(material, null);
        return;
      }
      orderMaterial = material;
      orderDrafts = drafts;
      orderDialogOpen = true;
    } catch (e) {
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not load draft purchase orders.');
    }
  }

  async function submitOrder(material, poId) {
    orderBusy = true;
    try {
      const resp = await api.post(`/api/materials/${material.material_id}/order/`,
        poId ? { po_id: poId } : {});
      orderDialogOpen = false;
      orderMaterial = null;
      if (resp.po_id && resp.po_number) {
        showSuccess('Added to', {
          href: `#/purchase-orders/${resp.po_id}`, label: resp.po_number,
        });
      } else {
        showSuccess(`Added to ${resp.po_number || 'a new purchase order'}.`);
      }
      await reload();
    } catch (e) {
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not order material.');
    } finally {
      orderBusy = false;
    }
  }

  function closeOrderDialog() {
    orderDialogOpen = false;
    orderMaterial = null;
  }

  // Receipt prompt (Mark on-hand / Mark received) — quantity input, not a
  // confirmation. Defaults to the outstanding shortfall.
  function startReceipt(material) {
    receiptMaterial = material;
    receiptQty = orderPrefillQty(material);
    receiptDialogOpen = true;
  }

  async function submitReceipt() {
    const quantity = String(receiptQty).trim();
    if (!quantity) return;
    receiptBusy = true;
    try {
      await api.post(`/api/materials/${receiptMaterial.material_id}/mark-on-hand/`, { quantity });
      receiptDialogOpen = false;
      receiptMaterial = null;
      await reload();
    } catch (e) {
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not mark received.');
    } finally {
      receiptBusy = false;
    }
  }

  function closeReceiptDialog() {
    receiptDialogOpen = false;
    receiptMaterial = null;
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

  // Mark all work complete
  async function handleWorkComplete() {
    if (!confirm('Mark all work complete on this job?')) return;
    statusBusy = true;
    try {
      await api.post(`/api/jobs/${job.job_id}/work-complete/`, {});
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
      <button type="button" onclick={() => { pickerOpen = true; }}>Add Work</button>
      <button type="button" onclick={() => { editingExpense = null; expenseModalOpen = true; }}>Add Expense</button>
    {/if}
    {#if job?.can_manage && canMarkWorkComplete(job.status)}
      <button type="button" onclick={handleWorkComplete} disabled={statusBusy}>Mark Work Complete</button>
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
    onOrderMaterial={startOrder}
    onMarkOnHand={startReceipt}
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

  <!-- Order chooser: Esc-only (no onSave) — with drafts present, Enter has no
       unambiguous primary action; the user picks a draft or "Start new PO". -->
  <Modal open={orderDialogOpen} onCancel={closeOrderDialog} busy={orderBusy} maxWidth="480px" label="Order material">
    <h3>Order — {orderMaterial?.description || '(material)'}</h3>
    <p class="dialog-hint">Add this material to an open draft purchase order, or start a new one.</p>
    <ul class="draft-list">
      {#each orderDrafts as po (po.po_id)}
        <li>
          <button type="button" disabled={orderBusy} onclick={() => submitOrder(orderMaterial, po.po_id)}>
            {po.po_number} — {po.business_name || 'no vendor'}
          </button>
        </li>
      {/each}
    </ul>
    <p class="dialog-actions">
      <button type="button" disabled={orderBusy} onclick={() => submitOrder(orderMaterial, null)}>Start new PO</button>
      <button type="button" disabled={orderBusy} onclick={closeOrderDialog}>Cancel</button>
    </p>
  </Modal>

  <!-- Receipt qty prompt: native <form> owns Enter (Modal omits onSave). -->
  <Modal open={receiptDialogOpen} onCancel={closeReceiptDialog} busy={receiptBusy} maxWidth="420px" label="Mark received">
    <form onsubmit={(e) => { e.preventDefault(); submitReceipt(); }}>
      <h3>Mark received — {receiptMaterial?.description || '(material)'}</h3>
      <p>
        <label for="receipt-qty"><strong>Quantity received</strong></label><br>
        <input id="receipt-qty" type="number" step="0.01" min="0" bind:value={receiptQty} required>
      </p>
      <p class="dialog-actions">
        <button type="submit" disabled={receiptBusy}>Mark received</button>
        <button type="button" disabled={receiptBusy} onclick={closeReceiptDialog}>Cancel</button>
      </p>
    </form>
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
  .draft-list { list-style: none; padding: 0; margin: 8px 0; max-height: 40vh; overflow-y: auto; }
  .draft-list li { margin: 0 0 4px; }
  .draft-list button {
    width: 100%; text-align: left; padding: 8px 10px;
    border: 1px solid #d1d5db; border-radius: 4px; background: #fff; cursor: pointer;
  }
  .draft-list button:hover { background: #f3f4f6; }
  .dialog-actions { display: flex; gap: 8px; margin-top: 12px; }
  .dialog-actions button {
    padding: 6px 14px; border: 1px solid #d1d5db; border-radius: 4px;
    background: #fff; cursor: pointer; font-size: 13px;
  }
  .dialog-actions button:hover { background: #f3f4f6; }
  .dialog-actions button:disabled { opacity: 0.5; cursor: default; }
</style>
