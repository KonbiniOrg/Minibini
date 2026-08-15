<script>
  import { link } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import { user as userStore } from '../../stores/auth.js';
  import { currentBlep } from '../../stores/currentBlep.js';
  import { blepActivityVersion } from '../../stores/blepActivity.js';
  import TaskActivityIndicator from '../../components/tasks/TaskActivityIndicator.svelte';
  import TaskActions from '../../components/tasks/TaskActions.svelte';
  import StartWorkConflictModal from '../../components/tasks/StartWorkConflictModal.svelte';
  import BlepList from '../../components/tasks/BlepList.svelte';
  import BlepEditModal from '../../components/tasks/BlepEditModal.svelte';
  import TaskTree from '../../components/TaskTree.svelte';
  import LinkifiedText from '../../components/LinkifiedText.svelte';
  import MaterialRow from '../../components/materials/MaterialRow.svelte';
  import MaterialFulfillmentModals from '../../components/materials/MaterialFulfillmentModals.svelte';
  import ExpenseModal from '../../components/expenses/ExpenseModal.svelte';
  import { consumeMaterial, restockMaterial, drawMoreMaterial, moveMaterial }
    from '../../lib/materialOps.js';
  import MaterialModal from '../../components/MaterialModal.svelte';
  import WorkItemForm from '../../components/WorkItemForm.svelte';
  import AssignModal from '../../components/AssignModal.svelte';
  import JobShell from '../../components/jobs/JobShell.svelte';
  import { formatDuration } from '../../lib/format.js';

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

  let assignModalOpen = $state(false);
  // The actual-qty surface is add-only: the running total displays
  // read-only and the input is a signed delta (negative = correction).
  // Adds are NOT idempotent, so nothing commits implicitly — only the
  // Add button / Enter, never blur, never a client retry.
  let addQtyError = $state('');
  let addQtyInput = $state('');
  let addQtySaving = $state(false);
  let addQtyAdded = $state(false);

  // Edit-task modal
  let editTaskOpen = $state(false);
  let templates = $state([]);

  async function loadTemplates() {
    try {
      const resp = await api.get('/api/service-items/?page_size=100');
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
  // The add-qty widget takes new production entries; a blocked task takes none.
  const canAddQty = $derived(!taskIsTerminal && task?.status !== 'blocked');

  // Same lock the job task list uses: terminal jobs freeze everything.
  const jobLocked = $derived(
    job != null && ['completed', 'cancelled', 'rejected'].includes(job.status)
  );

  // Material rows here are the same shared fragment (MaterialRow) the job
  // task list renders, with the same full action set — gating is by
  // material status / permissions / job state, never by which page this is.
  // No move-target radios render on this page (moving a material between
  // tasks happens on the job task list), so Move stays hidden here and
  // only detach passes through.
  let selectedTaskId = $state(null);
  let attachExpenseMaterial = $state(null);
  let fulfillModals = $state(null);           // Order + Mark-received dialogs

  const handleConsumeMaterial = (material) => consumeMaterial(material, refresh);
  const handleRestockMaterial = (material) => restockMaterial(material, refresh);
  const handleDrawMoreMaterial = (material) => drawMoreMaterial(material, refresh);
  async function handleMoveMaterial(material, targetTaskId) {
    await moveMaterial(material, targetTaskId, refresh);
    selectedTaskId = null;
  }

  const materialCallbacks = $derived({
    onConsumeMaterial: handleConsumeMaterial,
    onRestockMaterial: handleRestockMaterial,
    onDrawMoreMaterial: handleDrawMoreMaterial,
    onMoveMaterial: handleMoveMaterial,
    onOrderMaterial: (m) => fulfillModals?.startOrder(m),
    onMarkOnHand: (m) => fulfillModals?.startReceipt(m),
    onAttachExpense: (m) => { attachExpenseMaterial = m; },
  });

  function handleConflict(c) { conflict = c; }
  function handleResolved() { conflict = null; refresh(); }
  function handleCancel() { conflict = null; }

  const activeBlepOnThisTask = $derived.by(() => {
    const cb = $currentBlep;
    if (!cb || !task) return null;
    return cb.task && cb.task.id === task.task_id ? cb : null;
  });


  // Deliberately NOT $state: loadTask runs inside $effects, and reading
  // reactive state it also writes (e.g. `task`) would make those effects
  // depend on it — an infinite refetch loop. A plain variable adds no
  // dependency.
  let loadedTaskId = null;

  async function loadTask() {
    // Blank the page only on first load or when navigating to a different
    // task. Background refetches (blep activity, post-add refresh) must
    // not flip `loading` — that unmounts TaskActions mid-interaction and
    // destroys any open prompt modal (e.g. the stop-work session prompt).
    if (loadedTaskId === null || String(loadedTaskId) !== String(params.taskId)) {
      loading = true;
    }
    error = '';
    try {
      task = await api.get(`/api/tasks/${params.taskId}/`);
      loadedTaskId = params.taskId;
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

  async function addActualQty() {
    if (!task) return;
    addQtyError = '';
    addQtyAdded = false;
    const delta = parseFloat(addQtyInput);
    if (!Number.isFinite(delta) || delta === 0) {
      addQtyError = 'Enter a non-zero amount to add (negative to correct).';
      return;
    }
    addQtySaving = true;
    try {
      const resp = await api.post(
        `/api/tasks/${task.task_id}/actual-qty/add/`, { actual_qty: delta });
      addQtyInput = '';
      addQtyAdded = true;
      setTimeout(() => { addQtyAdded = false; }, 1500);
      // Refresh silently (no loading flip — it would remount the row
      // mid-interaction); the response total is authoritative.
      const fresh = await api.get(`/api/tasks/${task.task_id}/`);
      task = { ...fresh, actual_qty: resp.actual_qty };
    } catch (e) {
      addQtyError = e.message || 'Could not add to actual qty';
    } finally {
      addQtySaving = false;
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

  async function refresh() {
    await loadTask();
    await loadBleps();
    await loadMaterials();
  }

  $effect(() => {
    if (params.taskId) {
      loadTask();
      loadBleps();
      loadMaterials();
      loadCategories();
      loadTemplates();
    }
  });

  // Refetch when any blep changes anywhere (e.g. Stop/Cancel from the global
  // band), so the finalization shows here without a full page reload.
  let lastBlepVersion = $state(0);
  $effect(() => {
    const v = $blepActivityVersion;
    if (v !== lastBlepVersion) {
      lastBlepVersion = v;
      if (params.taskId) { loadTask(); loadBleps(); }
    }
  });

  // Task-owned money (Phase 1): the task carries its own money block
  // (qty_source/rate/unit_label/accounting_category/active_modifiers) —
  // source_scheme_name is provenance only (which preset it was stamped
  // from), never itself read for money math. `active_modifiers` is now a
  // list of {key, label, percent} snapshot dicts (not bare keys), so the
  // tooltip reads each modifier's own label.
  const modifiersTooltip = $derived.by(() => {
    const mods = task?.active_modifiers;
    if (!Array.isArray(mods) || mods.length === 0) return '';
    const names = mods.map((m) => (m && (m.label || m.key)) || '').filter(Boolean);
    return names.length > 0 ? `Modifiers: ${names.join(', ')}` : '';
  });

  // Phase 3: a task's own accounting_category can be null (categorized
  // later, at invoicing, via the configured fallback AC) — name-lookup
  // against the already-loaded (unfiltered) `categories` list, same
  // convention as WorkItemForm's categoryLabel. null renders as a muted
  // "uncategorized" rather than blank, so it reads as an intentional state.
  const taskCategoryName = $derived.by(() => {
    if (task?.accounting_category == null) return null;
    const cat = categories.find((c) => c.id === task.accounting_category);
    return cat ? `${cat.code} — ${cat.name}` : `#${task.accounting_category}`;
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

  function handleMaterialSaved() {
    matModalOpen = false;
    matModalMaterial = null;
    loadMaterials();
  }

  function handleMatModalClose() {
    matModalOpen = false;
  }
</script>

{#snippet invoicedLink(inv)}
  <a class="badge-invoiced" href={`#/invoices/${inv.id}`} use:link
     title="Billed on this invoice">INVOICED</a>
{/snippet}

{#if loading}
  <p>Loading…</p>
{:else if error}
  <p class="error">{error}</p>
{:else if task}
  <JobShell {job} {contact} current="tasks" colorway="cw-tasks" onJobChange={refresh}>
  <!-- Task header: crumbs, pill + title left, stat chips right -->
  <div class="task-head">
    <!-- No task-list crumb: the nav rail's Tasks link covers it. -->
    <div class="title-row">
      <div class="title-cluster">
        {#if task.invoice}
          {@render invoicedLink(task.invoice)}
        {:else}
          <TaskActivityIndicator {task} pill />
        {/if}
        <h1 class="task-title">{task.name}</h1>
      </div>
      <div class="stat-chips">
        <div class="stat-chip">
          <div class="stat-chip-header">Assignee</div>
          <div class="stat-chip-body">
            {#if task.can_manage}
              <button type="button" class="chip-link" class:muted={!task.assignee_name}
                onclick={() => { assignModalOpen = true; }}>{task.assignee_name || 'Unassigned'}</button>
            {:else}
              <span class:muted={!task.assignee_name}>{task.assignee_name || 'Unassigned'}</span>
            {/if}
          </div>
        </div>
        {#if task.est_worker_time}
          <div class="stat-chip">
            <div class="stat-chip-header">Est Time</div>
            <div class="stat-chip-body">{formatDuration(task.est_worker_time)}</div>
          </div>
        {/if}
        <!-- Hour-unit tasks show this chip too, even though it restates Est
             Time (pair-filled) — a blank read as missing data (RM 2026-08-06;
             the old duplicate-suppression exception is gone). -->
        {#if task.rate != null && task.est_qty}
          <div class="stat-chip">
            <div class="stat-chip-header">Est Qty</div>
            <div class="stat-chip-body">{task.est_qty} {task.unit_label}</div>
          </div>
        {/if}
        {#if task.qty_source === 'entered_qty'}
          <div class="stat-chip">
            <div class="stat-chip-header">{addQtyAdded ? 'added ✓' : 'Actual'}</div>
            <div class="stat-chip-body">
              {task.actual_qty ?? 0} {task.unit_label}
              {#if canAddQty}
                <label class="add-qty">
                  <span class="sr-only">Add ({task.unit_label})</span>
                  <input
                    type="number" step="any" placeholder="+ / −"
                    bind:value={addQtyInput}
                    onkeydown={(e) => { if (e.key === 'Enter') addActualQty(); }}>
                </label>
                <button type="button" class="chip-add" onclick={addActualQty} disabled={addQtySaving}>
                  {addQtySaving ? 'Adding…' : 'Add'}
                </button>
              {/if}
            </div>
          </div>
        {:else if task.qty_source === 'elapsed_time'}
          <div class="stat-chip">
            <div class="stat-chip-header">Actual</div>
            <div class="stat-chip-body">{Number(task.actual_hours) || 0} {task.unit_label}</div>
          </div>
        {/if}
        {#if task.rate != null}
          <!-- Provenance only — never read for money math. The task owns its
               own rate/unit_label/etc; this just names the preset it was
               stamped from, or a dash when that preset is gone (SET_NULL on
               delete) or was never known (legacy row). -->
          <div class="stat-chip">
            <div class="stat-chip-header">Scheme</div>
            <div class="stat-chip-body" title={modifiersTooltip}>{task.source_scheme_name || '—'}</div>
          </div>
        {/if}
        <div class="stat-chip">
          <div class="stat-chip-header">Category</div>
          <div class="stat-chip-body">
            <span class:muted={!taskCategoryName}>{taskCategoryName || 'uncategorized'}</span>
          </div>
        </div>
        {#if task.rate != null && task.effective_rate}
          <div class="stat-chip money">
            <div class="stat-chip-header">Rate</div>
            <div class="stat-chip-body">${task.effective_rate}/{task.unit_label}</div>
          </div>
        {/if}
        {#if task.rate != null && task.computed_charge}
          <div class="stat-chip money">
            <div class="stat-chip-header">Charge</div>
            <div class="stat-chip-body">${task.computed_charge}</div>
          </div>
        {/if}
      </div>
    </div>
    {#if addQtyError}
      <div class="field-error">{addQtyError}</div>
    {/if}
    {#if task.status === 'blocked' && task.blocked_reason}
      <div class="blocked-line preserve-breaks">Blocked: {task.blocked_reason}</div>
    {/if}
  </div>

  {#if !job?.on_hold}
    <div class="action-band">
      <TaskActions
        {task}
        user={$userStore}
        {activeBlepOnThisTask}
        hideStop={true}
        onChanged={refresh}
        onConflict={handleConflict}
      />
      {#if !taskIsTerminal && (task.can_edit ?? true)}
        <button type="button" class="quiet" onclick={() => { editTaskOpen = true; }}>Edit Task</button>
      {/if}
    </div>
  {/if}

  <StartWorkConflictModal
    {conflict}
    taskId={task?.task_id}
    onResolved={handleResolved}
    onCancel={handleCancel}
  />

  <div class="page-body">

  <h3>Description</h3>
  <div class="description preserve-breaks"><LinkifiedText text={task.description || '-'} /></div>

  <!-- Materials section — the shared MaterialRow fragment, same status
       vocabulary and full action set as the job task list. -->
  <h3>Materials</h3>
  {#if materials.length > 0}
    <table class="materials-table">
      <thead>
        <tr>
          {#if !taskIsTerminal && !jobLocked}<th class="move-col" aria-label="Move target"></th>{/if}
          <th>Description</th>
          <th>Status</th>
          <th class="text-right">Qty</th>
          <th class="text-right">Units</th>
          <th class="text-right">Unit Cost</th>
          <th class="text-right">Sell Price</th>
          <th class="text-right">Total</th>
          {#if !taskIsTerminal}<th>Actions</th>{/if}
        </tr>
      </thead>
      <tbody>
        {#each materials as mat (mat.material_id)}
          <MaterialRow
            material={mat} ownerTask={task} ownerTerminal={taskIsTerminal}
            indentClass="" taskAligned={false} showAssignee={false}
            showStatus={true} readonly={taskIsTerminal} {jobLocked}
            jobOnHold={job?.on_hold ?? false} {selectedTaskId}
            onEditMaterial={(m) => openEditMaterial(m)}
            {...materialCallbacks}
          />
        {/each}
      </tbody>
    </table>
  {:else}
    <p>No materials.</p>
  {/if}
  {#if !taskIsTerminal && !job?.on_hold}
    <p><button type="button" onclick={openAddMaterial}>Add Material</button></p>
  {/if}

  <MaterialModal
    open={matModalOpen}
    mode={matModalMode}
    material={matModalMaterial}
    taskId={params.taskId}
    {categories}
    onSaved={handleMaterialSaved}
    onClose={handleMatModalClose}
  />

  <!-- Order chooser + Mark-received receipt dialogs (shared component). -->
  <MaterialFulfillmentModals bind:this={fulfillModals} onDone={refresh} />

  <ExpenseModal
    open={attachExpenseMaterial != null}
    initialJob={job ? { job_id: job.job_id, job_number: job.job_number } : null}
    initialMaterial={attachExpenseMaterial}
    onSaved={() => { attachExpenseMaterial = null; refresh(); }}
    onClose={() => { attachExpenseMaterial = null; }}
  />

  <WorkItemForm
    open={editTaskOpen}
    mode="manual"
    context="job"
    contextId={task.job?.id}
    item={task}
    isEdit={true}
    {templates}
    canManage={job?.can_manage}
    {categories}
    onSaved={() => { editTaskOpen = false; refresh(); }}
    onClose={() => { editTaskOpen = false; }}
  />

  <BlepList
    {bleps}
    currentUser={$userStore}
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
    onSaved={handleSaved}
    onClose={closeModal}
  />

  <AssignModal
    open={assignModalOpen}
    {task}
    onSaved={() => { assignModalOpen = false; refresh(); }}
    onClose={() => { assignModalOpen = false; }}
  />
  </div>
  </JobShell>
{/if}

<style>
  .error { color: #a8071a; }
  .field-error { color: #a8071a; font-size: 13px; margin-top: 6px; }

  .task-head {
    padding: 10px 20px 12px;
    background: #fafafa;
    border-bottom: 1px solid #e5e7eb;
  }
  .crumbs { font-size: 12px; color: #6b7280; }
  .title-row {
    display: flex; justify-content: space-between; align-items: center;
    gap: 18px; margin-top: 6px; flex-wrap: wrap;
  }
  .title-cluster { display: flex; align-items: center; gap: 12px; min-width: 0; }
  .task-title { font-size: 22px; margin: 0; }
  .blocked-line { margin-top: 6px; font-size: 13px; color: #991b1b; }

  /* Assignee opens a modal — an action, so a button — but reads as a link. */
  .chip-link {
    border: none; background: none; padding: 0; cursor: pointer;
    font: inherit; color: inherit; text-decoration: underline;
  }
  .add-qty input { width: 70px; font-size: 12px; padding: 2px 6px; }
  .chip-add {
    font-size: 11px; font-weight: 600; border: 1px solid #94a3b8;
    background: #f1f5f9; border-radius: 4px; padding: 3px 10px; cursor: pointer;
  }
  .chip-add:hover { background: #e2e8f0; }

  /* TaskActions renders its own .actions flex row; flatten it so its buttons
     sit as direct band items with uniform gap. */
  .action-band :global(.actions) { display: contents; }

  .description { font-size: 14px; line-height: 1.6; max-width: 900px; }

  .sr-only {
    position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
    overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
  }
  .materials-table { width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 8px; }
  /* Headerless radio column — just wide enough for the radio button. */
  .move-col { width: 24px; }
  .materials-table th { padding: 6px 10px; text-align: left; background: var(--doc-soft); color: var(--doc-accent); }
  .materials-table td { padding: 6px 10px; }
  .text-right { text-align: right; }
  /* Row buttons use .row-actions, INVOICED uses .badge-invoiced (app.css). */
</style>
