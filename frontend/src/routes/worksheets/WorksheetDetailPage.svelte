<script>
  import { link, push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import WorksheetTaskTable from '../../components/WorksheetTaskTable.svelte';
  import WorkItemForm from '../../components/WorkItemForm.svelte';
  import PlanMaterialModal from '../../components/PlanMaterialModal.svelte';
  import PriceListPicker from '../../components/PriceListPicker.svelte';
  import JobHeader from '../../components/jobs/JobHeader.svelte';
  import DeliverablesSection from '../../components/jobs/DeliverablesSection.svelte';
  import { formatQtyUnits } from '../../lib/format.js';

  let { params = {} } = $props();

  let worksheet = $state(null);
  let job = $state(null);
  let contact = $state(null);
  let templates = $state([]);
  let categories = $state([]);
  let loading = $state(true);
  let error = $state('');

  let taskModalOpen = $state(false);
  let taskModalMode = $state('manual');
  let taskModalTask = $state(null);

  let materialModalOpen = $state(false);
  let materialModalMode = $state('create');
  let materialModalMaterial = $state(null);
  let materialModalTaskId = $state(null);

  let materials = $state([]);
  let selectedTaskId = $state(null);

  let priceListPickerOpen = $state(false);
  let taskModalServiceItem = $state(null);
  let materialModalInventoryItem = $state(null);

  // Permission half is the server-computed per-object `can_manage` (atom-holder
  // OR this job's project_manager); state half is the estimate-driven
  // `editable` flag: editable while the estimate is draft/absent, frozen once
  // it's sent.
  const canEdit = $derived((worksheet?.can_manage ?? false) && (worksheet?.editable ?? false));

  async function loadWorksheet() {
    loading = true;
    error = '';
    try {
      worksheet = await api.get(`/api/est-worksheets/${params.id}/`);
      await loadMaterials();
      if (worksheet.job) {
        await loadJobContext(worksheet.job);
      }
    } catch (e) {
      error = e.message || 'Could not load worksheet.';
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

  function openAddTemplateTask() {
    taskModalTask = null;
    taskModalMode = 'template';
    taskModalOpen = true;
  }

  function openPriceListPicker() {
    priceListPickerOpen = true;
  }

  function handlePriceListSelect({ kind, item }) {
    priceListPickerOpen = false;
    if (kind === 'service') {
      taskModalTask = null;
      taskModalMode = 'manual';
      taskModalServiceItem = item;
      taskModalOpen = true;
    } else {
      // kind === 'material'
      materialModalMaterial = null;
      materialModalTaskId = null;
      materialModalMode = 'create';
      materialModalOpen = true;
      // inventoryItem pre-seed is passed via prop below
      // store it so the modal receives it
      materialModalInventoryItem = item;
    }
  }

  function handlePriceListFreeform() {
    priceListPickerOpen = false;
    materialModalMaterial = null;
    materialModalTaskId = null;
    materialModalMode = 'create';
    materialModalInventoryItem = null;
    materialModalOpen = true;
  }

  function openEditTask(task) {
    taskModalTask = task;
    taskModalMode = 'manual';
    taskModalServiceItem = null;
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
    taskModalServiceItem = null;
    reload();
  }

  function openEditMaterial(mat, task = null) {
    materialModalMaterial = mat;
    materialModalTaskId = task ? task.plan_task_id : null;
    materialModalMode = 'edit';
    materialModalInventoryItem = null;
    materialModalOpen = true;
  }

  function openAddTaskMaterial(task) {
    materialModalMaterial = null;
    materialModalTaskId = task.plan_task_id;
    materialModalMode = 'create';
    materialModalInventoryItem = null;
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
    materialModalInventoryItem = null;
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
    // No confirm: creates draft estimate lines, each deletable afterward.
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

  function handleTaskClick(task) {
    push(`/worksheets/${worksheet.est_worksheet_id}/plan-tasks/${task.plan_task_id}`);
  }

  async function openWizard() {
    try {
      const result = await api.post(
        `/api/est-worksheets/${params.id}/open-estimate/`
      );
      push(`/estimates/${result.estimate_id}/wizard`);
    } catch (e) {
      alert(e.message || 'Failed to open wizard');
    }
  }

  // Delete is offered only when the server would actually allow it: the user can
  // manage this job (atom-holder or its PM), the worksheet is editable, and no
  // atom is claimed by an estimate line item (`deletable` mirrors the backend
  // delete check).
  const canDelete = $derived(
    (worksheet?.can_manage ?? false) && (worksheet?.editable ?? false) && (worksheet?.deletable ?? false)
  );

  async function handleDeleteWorksheet() {
    if (!confirm('Delete this worksheet? Its plan tasks and materials will be removed.')) return;
    try {
      await api.delete(`/api/est-worksheets/${worksheet.est_worksheet_id}/`);
      push(`/jobs/${worksheet.job}`);
    } catch (e) {
      alert(e.data?.detail || e.message || 'Could not delete worksheet.');
    }
  }
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p class="error">{error}</p>
{:else if worksheet}
  {#if job}
    <JobHeader {job} {contact} onStatusChange={reload} />
  {/if}

  <div class="toolbar">
    <a href={`/jobs/${worksheet.job}`} use:link class="back-link">&laquo; back to overview</a>
    <span class="ws-title">Worksheet</span>
    {#if !canEdit}<span class="status-badge status-frozen">frozen</span>{/if}
    {#if canEdit}
      <button type="button" onclick={openAddTemplateTask}>Add from Template</button>
      <button type="button" onclick={openPriceListPicker}>Add from Price List</button>
      <button type="button" onclick={sendAllAtoms} disabled={sendingAll}>
        {sendingAll ? 'Sending…' : 'Send all atoms to estimate'}
      </button>
      <button type="button" onclick={openWizard}>Open wizard to group atoms</button>
    {/if}
    <span class="meta">Created {new Date(worksheet.created_date).toLocaleDateString()}</span>
  </div>

  <WorksheetTaskTable
    {worksheet}
    readonly={!canEdit}
    onTaskClick={handleTaskClick}
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
      <table class="mat-table">
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
              <td class="preserve-breaks">{mat.description || '(no description)'}</td>
              <td class="text-right">{formatQtyUnits(mat.quantity, mat.units)}</td>
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

  {#if canDelete}
    <p class="delete-row">
      <button type="button" class="delete-btn" onclick={handleDeleteWorksheet}>
        Delete worksheet
      </button>
    </p>
  {/if}

  {#if worksheet.job}
    <DeliverablesSection jobId={worksheet.job} canManage={worksheet.can_manage} />
  {/if}

  <PriceListPicker
    open={priceListPickerOpen}
    onselect={handlePriceListSelect}
    onfreeform={handlePriceListFreeform}
    onclose={() => { priceListPickerOpen = false; }}
  />

  <WorkItemForm
    open={taskModalOpen}
    mode={taskModalMode}
    context="worksheet"
    contextId={worksheet.est_worksheet_id}
    item={taskModalTask}
    isEdit={!!taskModalTask}
    {templates}
    serviceItem={taskModalServiceItem}
    onSaved={handleTaskSaved}
    onClose={() => { taskModalOpen = false; taskModalServiceItem = null; }}
  />

  <PlanMaterialModal
    open={materialModalOpen}
    mode={materialModalMode}
    material={materialModalMaterial}
    worksheetId={worksheet.est_worksheet_id}
    planTaskId={materialModalTaskId}
    {categories}
    inventoryItem={materialModalInventoryItem}
    onSaved={handleMaterialSaved}
    onClose={() => { materialModalOpen = false; materialModalInventoryItem = null; }}
  />
{/if}

<style>
  .error { color: #a8071a; }
  .toolbar {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
    padding: 8px 24px;
  }
  .back-link { font-size: 13px; }
  .ws-title { font-size: 18px; font-weight: 600; }
  .status-badge {
    padding: 4px 12px; border-radius: 12px; font-size: 13px;
    font-weight: 600; text-transform: capitalize;
  }
  .delete-row { padding: 16px 24px; }
  .delete-btn { color: #a8071a; }
  .status-frozen { background: #fef3c7; color: #92400e; }
  .meta { color: #888; font-size: 13px; margin-left: auto; }
  .toolbar button {
    padding: 6px 14px; border: 1px solid #d1d5db; border-radius: 4px;
    background: #fff; cursor: pointer; font-size: 13px;
  }
  .toolbar button:hover { background: #f3f4f6; }
  .toolbar button:disabled { opacity: 0.5; cursor: default; }

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
