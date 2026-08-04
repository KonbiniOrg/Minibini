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
  import { formatDuration, durationToHours } from '../../lib/format.js';
  import { taskActual, fmtWorkerTime } from '../../lib/taskTotals.js';

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

  // For an elapsed_time (hour-unit) scheme, est_qty and est_worker_time are
  // the same underlying value (backend pair-fills them — Task 8) — showing
  // both chips restates one number twice. Suppress the Est Qty chip only
  // when it's a literal duplicate; a legacy row where they've diverged
  // (pre-pair-fill data) still shows both, same as today. Inputs are
  // minute-grained in practice (est_worker_time), so durationToHours is safe
  // here — this comparison must NOT be reused for blep-derived elapsed
  // values, which carry seconds and would double-round.
  const estQtyIsDuplicate = $derived(
    task?.unit_label === 'hour'
    && task?.est_worker_time
    && Number(task?.est_qty) === durationToHours(task.est_worker_time)
  );

  // Quantity structure (spec §9 rule 4, task-owned-money Phase 4 Task 4): a
  // parent task with no explicit rate of its own still has real money —
  // Task.effective_rate() already resolves to derived_unit_price() for it
  // server-side. The money block used to gate purely on the task's OWN raw
  // `rate` (never null-but-priced before structures existed); widen the
  // gate so a rate-null parent still shows its Scheme/Rate/Category/Charge
  // chips, with the Rate chip labeled to say where the number came from.
  const hasMoney = $derived(
    task?.rate != null || (task?.is_parent && task?.derived_unit_price != null)
  );
  const rateIsDerived = $derived(task?.rate == null && task?.is_parent);

  // Quantity structure (spec §9 rule 1): a parent delegates start/blep/
  // assign to its children — never render those affordances for one.
  const isParentTask = $derived(!!task?.is_parent);

  // Parent completion is OFFERED, not automatic — only once every child is
  // terminal (complete/cancelled), mirroring TaskLifecycleService.
  // complete_task's own open_children check exactly (vacuously true with
  // no children yet, same as the backend's `.exclude(...)` returning
  // empty). Drives both the Complete button's visibility (via TaskActions)
  // and the explanatory note below it.
  const childrenReady = $derived(
    subtasks.every((s) => s.status === 'complete' || s.status === 'cancelled')
  );

  // Same lock the job task list uses: terminal jobs freeze everything.
  const jobLocked = $derived(
    job != null && ['completed', 'cancelled', 'rejected'].includes(job.status)
  );

  // Material rows here are the same shared fragment (MaterialRow) the job
  // task list renders, with the same full action set — gating is by
  // material status / permissions / job state, never by which page this is.
  let selectedTaskId = $state(null);          // Move-target radio (subtask rows)
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

  // accounting_category is nullable end-to-end now (task-owned-money Phase
  // 3, Task 2): a manual/flat task may legitimately carry no AC yet
  // ("categorize at invoicing"). Render that state as a plain dash, not an
  // error — the money-permission gate (server-side) is what actually
  // controls who may set/clear it.
  function categoryLabel(id) {
    if (id == null) return '—';
    const cat = categories.find((c) => String(c.id) === String(id));
    return cat ? `${cat.code} — ${cat.name}` : `#${id}`;
  }

  // Quantity structure (spec §9 rule 3, task-owned-money Phase 4): the
  // children table's "Expected" column reads the API's derived value —
  // never re-derives the multiplier client-side (that's Task.expected_qty()/
  // expected_worker_time()'s job, the ONE place it's computed). Falls back
  // to the worker-time expectation for a scheme with no quantity of its own
  // (e.g. elapsed_time), then to a dash.
  function childExpectedDisplay(sub) {
    if (sub.expected_qty != null) return `${sub.expected_qty} ${sub.unit_label || ''}`.trim();
    if (sub.expected_worker_time) return fmtWorkerTime(sub.expected_worker_time);
    return '-';
  }

  // "Logged / Actual" reads the same taskActual() helper TaskRow uses —
  // bleps-derived hours for elapsed_time, worker-entered actual_qty for
  // entered_qty.
  function childLoggedDisplay(sub) {
    const actual = taskActual(sub);
    return actual == null ? '-' : `${actual} ${sub.unit_label || ''}`.trim();
  }

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

  // Subtasks reorder among their siblings here — the job task list page
  // deliberately offers no subtask reordering (B3). Same endpoint as
  // top-level reorder; the backend scopes the swap to the peer group.
  async function handleSubtaskReorder(taskId, direction) {
    try {
      await api.post(`/api/jobs/${task.job.id}/reorder-tasks/`, {
        task_id: taskId,
        direction,
      });
      await loadSubtasks();
    } catch (e) {
      showError(errorMessage(e, 'Could not reorder.'));
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

{#snippet invoicedLink(inv)}
  <a class="badge-invoiced" href={`#/invoices/${inv.id}`} use:link
     title="Billed on this invoice">INVOICED</a>
{/snippet}

{#if loading}
  <p>Loading…</p>
{:else if error}
  <p class="error">{error}</p>
{:else if task}
  <JobShell {job} {contact} current="tasks" onJobChange={refresh}>
  <!-- Task header: crumbs, pill + title left, stat chips right -->
  <div class="task-head">
    <!-- No task-list crumb: the nav rail's Tasks link covers it. The only
         crumb is the parent link on a subtask. -->
    {#if task.job && task.parent_task}
      <div class="crumbs">
        subtask of <a href={`/jobs/${task.job.id}/tasks/${task.parent_task}`} use:link>{task.parent_task_name}</a>
      </div>
    {/if}
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
            {#if task.can_manage && !isParentTask}
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
        {#if task.rate != null && task.est_qty && !estQtyIsDuplicate}
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
        {#if hasMoney}
          <!-- Provenance only — never read for money math. The task owns its
               own rate/unit_label/etc; this just names the preset it was
               stamped from, or a dash when that preset is gone (SET_NULL on
               delete) or was never known (legacy row). A rate-null parent
               has no preset of its own (its price comes from children), so
               this stays a dash for it too. -->
          <div class="stat-chip">
            <div class="stat-chip-header">Scheme</div>
            <div class="stat-chip-body" title={modifiersTooltip}>{task.source_scheme_name || '—'}</div>
          </div>
        {/if}
        {#if hasMoney && task.effective_rate}
          <div class="stat-chip money">
            <div class="stat-chip-header">Rate</div>
            <div class="stat-chip-body">
              {#if rateIsDerived}derived from children: {/if}${task.effective_rate}/{task.unit_label}
            </div>
          </div>
        {/if}
        {#if hasMoney}
          <!-- Nullable end-to-end (Phase 3, Task 2): a flat/manual task may
               have no AC yet — "—" here, not an error; correction happens
               at invoicing (fallback stamping, Task 3) or via edit. Not a
               dollar amount itself (like Scheme), so no .money class. -->
          <div class="stat-chip">
            <div class="stat-chip-header">Category</div>
            <div class="stat-chip-body">{categoryLabel(task.accounting_category)}</div>
          </div>
        {/if}
        {#if hasMoney && task.computed_charge}
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
        isParent={isParentTask}
        {childrenReady}
        onChanged={refresh}
        onConflict={handleConflict}
      />
      {#if !taskIsTerminal && (task.can_edit ?? true)}
        <button type="button" class="quiet" onclick={() => { editTaskOpen = true; }}>Edit Task</button>
      {/if}
    </div>
    {#if isParentTask && !taskIsTerminal && !childrenReady}
      <p class="completion-note">
        Complete will be available once every subtask is complete or cancelled.
      </p>
    {/if}
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

  <!-- Subtasks section — only on top-level tasks: one level of subtasks
       (B1), so a subtask has no subtasks of its own and no section at all. -->
  {#if !task.parent_task}
    <h3>Subtasks</h3>
    {#if subtasks.length > 0}
      <!-- Quantity structure (spec §9, task-owned-money Phase 4): the
           expected-vs-logged comparison for a parent's children — the
           per-unit estimate a subtask actually carries, the DERIVED total
           it expects (Task.expected_qty(), the ONE place the parent
           multiplier is applied), and what's actually been logged against
           it so far. Additive to the passive tree below (which keeps its
           own materials/reorder wiring untouched). -->
      <table class="children-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Status</th>
            <th class="text-right">Per-unit Est</th>
            <th class="text-right">Expected</th>
            <th class="text-right">Logged / Actual</th>
          </tr>
        </thead>
        <tbody>
          {#each subtasks as sub (sub.task_id)}
            <tr>
              <td>{sub.name}</td>
              <td>{sub.status}</td>
              <td class="text-right">
                {sub.est_qty ?? '-'} {sub.unit_label || ''}{sub.qty_scales_with_parent === false ? ' (batch)' : ''}
              </td>
              <td class="text-right">{childExpectedDisplay(sub)}</td>
              <td class="text-right">{childLoggedDisplay(sub)}</td>
            </tr>
          {/each}
        </tbody>
      </table>

      <!-- Deliberately passive rows (A3): no edit/del/cancel here — a
           subtask's own detail page is its editing surface. Wired: material
           add/edit and sibling reorder (B3). -->
      <TaskTree
        tasks={subtasks}
        readonly={taskIsTerminal}
        {jobLocked}
        jobOnHold={job?.on_hold ?? false}
        canManage={task?.can_manage}
        showStatus={true}
        showAssignee={true}
        onTaskClick={handleSubtaskTaskClick}
        onAddMaterial={handleSubtaskAddMaterial}
        onEditMaterial={handleSubtaskEditMaterial}
        onReorder={handleSubtaskReorder}
        onConsumeMaterial={materialCallbacks.onConsumeMaterial}
        onRestockMaterial={materialCallbacks.onRestockMaterial}
        onDrawMoreMaterial={materialCallbacks.onDrawMoreMaterial}
        onMoveMaterial={materialCallbacks.onMoveMaterial}
        onOrderMaterial={materialCallbacks.onOrderMaterial}
        onMarkOnHand={materialCallbacks.onMarkOnHand}
        onAttachExpense={materialCallbacks.onAttachExpense}
        bind:selectedTaskId
      />
    {:else}
      <p>No subtasks.</p>
    {/if}
    {#if !taskIsTerminal && !job?.on_hold}
      <p><button type="button" onclick={openAddSubtask}>Add Subtask</button></p>
    {/if}
  {/if}

  <!-- Materials section — the shared MaterialRow fragment, same status
       vocabulary and full action set as the job task list (Move targets are
       the subtask radios above; removal is the release action). -->
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
    taskId={effectiveMatTaskId}
    {categories}
    onSaved={subtaskMatTaskId ? handleMaterialSavedForSubtask : handleMaterialSaved}
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
    open={subtaskModalOpen}
    mode="manual"
    context="subtask"
    contextId={task?.task_id}
    templates={[]}
    canManage={job?.can_manage}
    {categories}
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
    canAdd={!isParentTask}
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
  .materials-table th { padding: 6px 10px; text-align: left; background: #fefce8; }
  .materials-table td { padding: 6px 10px; }
  .text-right { text-align: right; }
  /* Row buttons use .row-actions, INVOICED uses .badge-invoiced (app.css). */

  /* Quantity structure (spec §9, task-owned-money Phase 4): the parent's
     expected-vs-logged comparison — a compact, money-adjacent counterpart
     to the passive tree below it (materials-table's palette, not the
     tree's green header). */
  .children-table { width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 8px; }
  .children-table th { padding: 6px 10px; text-align: left; background: #fefce8; }
  .children-table td { padding: 6px 10px; }
  .completion-note { font-size: 13px; color: #6b7280; margin: 0 0 8px; }
</style>
