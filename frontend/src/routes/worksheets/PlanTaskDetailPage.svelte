<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import PlanMaterialModal from '../../components/PlanMaterialModal.svelte';
  import WorkItemForm from '../../components/WorkItemForm.svelte';
  import JobHeader from '../../components/jobs/JobHeader.svelte';
  import { formatQtyUnits } from '../../lib/format.js';

  let { params = {} } = $props();

  let task = $state(null);
  let worksheet = $state(null);
  let job = $state(null);
  let contact = $state(null);
  let loading = $state(true);
  let error = $state('');

  // Materials state
  let materials = $state([]);
  let categories = $state([]);
  let matModalOpen = $state(false);
  let matModalMode = $state('create');
  let matModalMaterial = $state(null);

  // Edit task modal state
  let templates = $state([]);
  let editModalOpen = $state(false);

  const canManageJobs = $derived(
    $userStore?.permissions?.includes('can_manage_jobs') ?? false
  );
  const canEdit = $derived(canManageJobs && worksheet?.status === 'draft');

  async function loadTask() {
    loading = true;
    error = '';
    try {
      task = await api.get(`/api/plan-tasks/${params.planTaskId}/`);
      worksheet = task.est_worksheet || null;
      if (task?.est_worksheet?.job?.id) {
        await loadJobContext(task.est_worksheet.job.id);
      }
    } catch (e) {
      error = e.message || 'Could not load plan task.';
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
      materials = await api.get(`/api/plan-tasks/${params.planTaskId}/materials/`);
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

  async function refresh() {
    await loadTask();
    await loadMaterials();
  }

  $effect(() => {
    if (params.planTaskId) {
      loadTask();
      loadMaterials();
      loadTemplates();
      loadCategories();
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
      await api.delete(`/api/plan-tasks/${params.planTaskId}/materials/${material.plan_material_id}/`);
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

  function handleEditTaskSaved() {
    editModalOpen = false;
    refresh();
  }

  function formatWorkerTime(dur) {
    if (!dur) return '-';
    // DRF returns duration as HH:MM:SS string
    const match = dur.match(/^(\d+):(\d{2}):(\d{2})/);
    if (!match) return dur;
    const h = parseInt(match[1], 10);
    const m = parseInt(match[2], 10);
    const s = parseInt(match[3], 10);
    const parts = [];
    if (h) parts.push(`${h}h`);
    if (m) parts.push(`${m}m`);
    if (!h && !m && s) parts.push(`${s}s`);
    return parts.length ? parts.join(' ') : '0m';
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

  <div class="toolbar">
    {#if task.est_worksheet?.job?.id}
      <a href={`/jobs/${task.est_worksheet.job.id}`} use:link class="back-link">&laquo; back to overview</a>
    {/if}
    {#if params.wsId}
      <a href={`/worksheets/${params.wsId}`} use:link class="back-link">back to worksheet</a>
    {:else if task.est_worksheet?.est_worksheet_id}
      <a href={`/worksheets/${task.est_worksheet.est_worksheet_id}`} use:link class="back-link">back to worksheet</a>
    {/if}
    <h2 class="task-title">PlanTask: {task.name}</h2>
  </div>

  <table border="1">
    <tbody>
      <tr><td>Description</td><td class="preserve-breaks">{task.description || '-'}</td></tr>
      <tr>
        <td>Est. quantity</td>
        <td>{task.est_qty ?? '-'}{#if task.scheme_unit_label} {task.scheme_unit_label}{/if}</td>
      </tr>
      <tr><td>Estimated worker time</td><td>{formatWorkerTime(task.est_worker_time)}</td></tr>
      <tr><td>Rate</td><td>{task.effective_rate ? `$${task.effective_rate}` : '-'}</td></tr>
    </tbody>
  </table>

  <!-- Charge section -->
  {#if task.scheme_name}
    <h3>Charge</h3>
    <table border="1"><tbody>
      <tr><td><strong>Scheme</strong></td><td>{task.scheme_name}</td></tr>
      <tr><td><strong>Rate</strong></td><td>${task.effective_rate}/{task.scheme_unit_label}</td></tr>
      {#if task.active_modifiers && task.active_modifiers.length > 0}
        <tr><td><strong>Modifiers</strong></td>
          <td>{task.active_modifiers.join(', ')}</td></tr>
      {/if}
      {#if task.computed_charge}
        <tr><td><strong>Computed charge</strong></td><td>${task.computed_charge}</td></tr>
      {/if}
    </tbody></table>
  {/if}

  <!-- Edit button -->
  {#if canEdit}
    <p>
      <button type="button" onclick={() => { editModalOpen = true; }}>Edit Plan Task</button>
    </p>
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
          {#if canEdit}<th>Actions</th>{/if}
        </tr>
      </thead>
      <tbody>
        {#each materials as mat}
          <tr>
            <td>{mat.description || '(no description)'}</td>
            <td class="text-right">{formatQtyUnits(mat.quantity, mat.units)}</td>
            <td class="text-right">{mat.unit_cost ? `$${Number(mat.unit_cost).toFixed(2)}` : '-'}</td>
            <td class="text-right">{mat.sell_price ? `$${Number(mat.sell_price).toFixed(2)}` : '-'}</td>
            <td class="text-right">{(Number(mat.quantity) && Number(mat.sell_price)) ? `$${(Number(mat.quantity) * Number(mat.sell_price)).toFixed(2)}` : '-'}</td>
            {#if canEdit}
              <td>
                <button type="button" onclick={() => openEditMaterial(mat)}>edit</button>
                <button type="button" onclick={() => handleDeleteMaterial(mat)}>del</button>
              </td>
            {/if}
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p>No materials.</p>
  {/if}
  {#if canEdit}
    <p><button type="button" onclick={openAddMaterial}>Add Material</button></p>
  {/if}

  <PlanMaterialModal
    open={matModalOpen}
    mode={matModalMode}
    material={matModalMaterial}
    planTaskId={params.planTaskId}
    {categories}
    onSaved={handleMaterialSaved}
    onClose={() => { matModalOpen = false; matModalMaterial = null; }}
  />

  <WorkItemForm
    open={editModalOpen}
    mode="manual"
    context="worksheet"
    contextId={task?.est_worksheet?.est_worksheet_id}
    item={task}
    isEdit={true}
    {templates}
    onSaved={handleEditTaskSaved}
    onClose={() => { editModalOpen = false; }}
  />
{/if}

<style>
  .error { color: #a8071a; }
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
