<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { showError, showSuccess } from '../../stores/messages.js';
  import { canMarkWorkComplete } from '../../lib/jobActions.js';
  import { consumeMaterial, restockMaterial, drawMoreMaterial, moveMaterial }
    from '../../lib/materialOps.js';
  import MaterialFulfillmentModals from '../materials/MaterialFulfillmentModals.svelte';
  import TaskTree from '../TaskTree.svelte';
  import WorkItemForm from '../WorkItemForm.svelte';
  import MaterialModal from '../MaterialModal.svelte';
  import ExpenseModal from '../expenses/ExpenseModal.svelte';
  import AssignModal from '../AssignModal.svelte';
  import PriceListPicker from '../PriceListPicker.svelte';
  import Modal from '../Modal.svelte';
  import BundleModal from '../docsurface/BundleModal.svelte';
  import LoadState from '../LoadState.svelte';

  let { job, onJobChange = () => {} } = $props();

  let enrichedTasks = $state([]);
  let jobMaterials = $state([]);
  let jobExpenses = $state([]);
  let templates = $state([]);
  let categories = $state([]);
  let loading = $state(true);
  // Sub-fetches below each swallow their own failure so the task tree stays
  // usable (see the pool-fetch comments); this records WHICH ones failed so
  // the panel can say so instead of silently showing less.
  let loadFailures = $state([]);
  function noteFailure(label) {
    if (!loadFailures.includes(label)) loadFailures = [...loadFailures, label];
  }

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
  async function handleDeleteExpense(exp) {
    if (!confirm('Delete this expense? If synced, the QBO Purchase is voided.')) return;
    try {
      await api.delete(`/api/expenses/${exp.id}/`);
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not delete expense.'));
    }
  }

  async function handleRejectExpense(exp) {
    if (!confirm('Reject this expense? It will not be reimbursed.')) return;
    try {
      await api.post(`/api/expenses/${exp.id}/reject/`);
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not reject expense.'));
    }
  }

  let materialModalMode = $state('create');
  let materialModalMaterial = $state(null);
  let materialModalTaskId = $state(null);
  let materialModalJobId = $state(null);

  let selectedTaskId = $state(null);

  let assignModalOpen = $state(false);
  let assignModalTask = $state(null);

  // Picker state
  let pickerOpen = $state(false);
  let taskPresetTemplateId = $state(null);
  let taskPresetServiceItem = $state(null); // full picked object — see handleChoose
  let taskPresetName = $state('');
  let materialPresetPli = $state(null);
  let materialPresetDescription = $state('');
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
    const allTasks = [...enrichedTasks];
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

  // Estimate-context layer: the job's single non-superseded estimate (Task 1
  // guarantees at most one), its source pool when it's a draft, and the
  // "Start Estimate" offer when there's no live estimate yet. Tasks 3-4 build
  // selection checkboxes and the bundle CTA on top of these exact names.
  let liveEstimate = $state(null);
  let sourcePool = $state(null);
  let estimateContextLoaded = $state(false);

  const draftEstimate = $derived(
    liveEstimate?.status === 'draft' ? liveEstimate : null);
  const canBundle = $derived(
    !!draftEstimate && !!job?.can_manage && !jobLocked && !job?.on_hold);
  const canOfferEstimate = $derived(
    estimateContextLoaded && !liveEstimate && !!job?.can_manage && !jobLocked
    && ['draft', 'submitted'].includes(job?.status));

  // CO-context layer (Tasks-page CO lens, RM 2026-09-20): the job's at-most-
  // one draft change order (invariant enforced in ChangeOrder.clean()) and
  // its source pool. Structurally exclusive with the estimate layer above —
  // a draft estimate exists only pre-acceptance, a draft change order only
  // exists post-acceptance (while the job is held) — so the two bundling
  // targets can never coexist.
  let changeOrders = $state([]);
  let coSourcePool = $state(null);
  let coContextLoaded = $state(false);

  const draftCO = $derived(changeOrders.find((co) => co.status === 'draft') ?? null);
  const canBundleCO = $derived(!!draftCO && !!job?.can_manage && !jobLocked);
  // Hint state: a held job with an accepted estimate but no draft CO yet.
  // Unlike an estimate, a change order is always explicitly generated by a
  // user — the Tasks page never auto-creates one — so this is a passive
  // link, never a create button.
  const showChangeOrderHint = $derived(
    coContextLoaded && !!job?.on_hold && liveEstimate?.status === 'accepted'
    && !draftCO && !!job?.can_manage && !jobLocked);

  // Bundle-selection state (Task 3): which pool atoms the user has checked
  // to fold into the draft estimate or (Tasks-page CO lens) draft change
  // order. Keyed the same way as EstimateEditView's `selected` ("type:id"
  // strings) so Task 4's bundle modal can hand the array straight to the
  // same atom-parsing helpers.
  let selected = $state([]);
  // The pool actually backing checkboxes right now — whichever draft
  // document is live. Lens exclusivity (see draftCO above) means at most one
  // of these is ever non-null.
  const activePool = $derived(draftEstimate ? sourcePool : (draftCO ? coSourcePool : null));
  const poolByKey = $derived.by(() => {
    const map = new Map();
    for (const a of (activePool?.atoms || [])) map.set(`${a.type}:${a.id}`, a);
    return map;
  });

  // State-B fallback: before any estimate exists there is no source-pool to
  // fetch (the pool is estimate-scoped — `GET /api/estimates/{id}/source-pool/`
  // needs a live estimate id). Selectability is derived client-side instead:
  // a task is selectable unless cancelled, a material unless released.
  // Nothing can be "claimed" here — a claim only exists once an estimate or
  // change order has actually claimed the atom, and there is no estimate yet
  // — so every eligible row synthesizes a plain {state:'available'} entry
  // (the exact shape TaskRow/MaterialRow already render a real available
  // pool atom as) and ineligible rows get no entry at all. That means
  // TaskRow/MaterialRow need no changes for state B.
  const fallbackPoolByKey = $derived.by(() => {
    const map = new Map();
    for (const t of enrichedTasks) {
      if (t.status !== 'cancelled') {
        map.set(`task:${t.task_id}`, { type: 'task', id: t.task_id, state: 'available' });
      }
    }
    const allMaterials = [...jobMaterials];
    for (const t of enrichedTasks) allMaterials.push(...(t.materials || []));
    for (const m of allMaterials) {
      if (m.consumption_state !== 'released') {
        map.set(`material:${m.material_id}`, { type: 'material', id: m.material_id, state: 'available' });
      }
    }
    return map;
  });

  // Selection is offered in state A (bundle into the existing draft) and
  // state B (bundle into the draft the click itself will create) — never
  // state C. The pool TaskTree renders against switches the instant a draft
  // exists; loadEstimateContext()'s own selection-pruning step (below) must
  // keep reading the REAL poolByKey, never this fallback, so a state-B
  // selection gets validated against the freshly created draft's actual
  // pool once one exists — not against stale client-side guesses.
  const canSelectBundle = $derived(canBundle || canOfferEstimate || canBundleCO);
  const effectivePoolByKey = $derived(activePool ? poolByKey : fallbackPoolByKey);

  function toggleBundleSelect(key) {
    selected = selected.includes(key)
      ? selected.filter((k) => k !== key)
      : [...selected, key];
  }

  // Bundle CTA + modal (Task 4): the checked pool atoms fold into one draft
  // estimate line via the shared BundleModal (owns its own POST; this host
  // owns the 409-conflict refresh, per BundleModal.svelte:49-52).
  let bundleModalOpen = $state(false);
  const bundleAtoms = $derived(
    (activePool?.atoms || []).filter((a) => selected.includes(`${a.type}:${a.id}`)));
  const bundleApiBase = $derived(
    draftEstimate ? `/api/estimates/${draftEstimate.estimate_id}`
      : (draftCO ? `/api/change-orders/${draftCO.change_order_id}` : ''));

  async function refreshAfterBundle() {
    selected = [];
    await Promise.all([reload(), loadEstimateContext(), loadCOContext()]);
    // reload() refetches the job (a per-unit bundle stamps atom totals, so
    // task rows change); loadEstimateContext()/loadCOContext() refetch
    // whichever pool is live.
  }
  async function handleBundleCreated() {
    bundleModalOpen = false;
    const isCO = !!draftCO;
    const docNumber = isCO ? draftCO.change_order_number : draftEstimate?.estimate_number;
    await refreshAfterBundle();
    showSuccess(isCO
      ? `Line added to change order ${docNumber} (draft).`
      : `Line added to estimate ${docNumber} (draft).`);
  }
  async function handleBundleConflict(e) {
    bundleModalOpen = false;
    selected = [];
    await Promise.all([reload(), loadEstimateContext(), loadCOContext()]);
    showError(errorMessage(e,
      'Some of the selected work was claimed elsewhere in the meantime — refreshed.'));
  }

  // The job has at most one non-superseded estimate (enforced in
  // Estimate.clean() + create_for_job) — .find() is exact, not heuristic.
  async function loadEstimateContext() {
    try {
      const resp = await api.get(`/api/estimates/?job=${job.job_id}&page_size=100`);
      const rows = resp.results ?? resp;
      liveEstimate = rows.find((e) => e.status !== 'superseded') ?? null;
    } catch (e) {
      noteFailure('estimate context');
      liveEstimate = null;
      sourcePool = null;
      estimateContextLoaded = true;
      selected = selected.filter((k) => poolByKey.get(k)?.state === 'available');
      return;
    }
    if (liveEstimate?.status === 'draft') {
      try {
        sourcePool = await api.get(`/api/estimates/${liveEstimate.estimate_id}/source-pool/`);
      } catch (e) {
        // The draft itself is real (we already have its id from the list
        // fetch above) even though its pool failed to load — do NOT null
        // out liveEstimate here, or a start-and-bundle click that created
        // the draft successfully would bounce back to the "Start Estimate"
        // offer as if nothing happened. Land in state A with an empty pool
        // instead (no atoms selectable until a reload succeeds).
        noteFailure('estimate line pool');
        sourcePool = null;
      }
    } else {
      sourcePool = null;
    }
    estimateContextLoaded = true;
    // Drop any selection whose pool atom is gone or no longer available —
    // a reload (mutation, or another window claiming it) invalidates it.
    // Ordering guard: this always reads the REAL poolByKey (built off
    // sourcePool, just assigned above), never fallbackPoolByKey — by this
    // point liveEstimate/sourcePool already reflect whatever just happened
    // (including a state-B "start estimate" call that ran immediately
    // before this), so a B->A transition prunes a carried-over selection
    // against the new draft's actual pool, not against stale client-side
    // guesses. In practice every eligible state-B selection survives, since
    // a freshly created draft's pool has no claims yet.
    selected = selected.filter((k) => poolByKey.get(k)?.state === 'available');
  }

  // The job's at-most-one draft change order (Task 1's invariant) and its
  // source pool — the CO-lens sibling of loadEstimateContext(). Always
  // fetches the job's full CO list (cheap, and needed for the hint state's
  // "no draft CO yet" check) regardless of the estimate lens's state.
  async function loadCOContext() {
    try {
      const resp = await api.get(`/api/change-orders/?job=${job.job_id}&page_size=100`);
      changeOrders = resp.results ?? resp;
    } catch (e) {
      noteFailure('change-order context');
      changeOrders = [];
      coSourcePool = null;
      coContextLoaded = true;
      selected = selected.filter((k) => poolByKey.get(k)?.state === 'available');
      return;
    }
    const draft = changeOrders.find((co) => co.status === 'draft') ?? null;
    if (draft) {
      try {
        coSourcePool = await api.get(`/api/change-orders/${draft.change_order_id}/source-pool/`);
      } catch (e) {
        // Same reasoning as loadEstimateContext's pool-fetch catch: the
        // draft itself is real even if its pool failed to load.
        noteFailure('change-order line pool');
        coSourcePool = null;
      }
    } else {
      coSourcePool = null;
    }
    coContextLoaded = true;
    selected = selected.filter((k) => poolByKey.get(k)?.state === 'available');
  }

  async function handleStartEstimate() {
    const wantsBundle = selected.length > 0;
    try {
      const est = await api.post('/api/estimates/', { job: job.job_id });
      if (!wantsBundle) {
        showSuccess(`Estimate ${est.estimate_number} started.`);
        await loadEstimateContext();
        return;
      }
      // One-click "start & bundle": create, then re-resolve context — that
      // re-resolution (loadEstimateContext) is also what maps the carried
      // selection onto the new draft's real pool atoms (its pruning step
      // above). bundleAtoms (derived from sourcePool + selected, same as
      // state A) then already reflects the survivors.
      await loadEstimateContext();
      if (bundleAtoms.length > 0) {
        bundleModalOpen = true;
      } else {
        showError('The estimate was started, but the selected work is no ' +
          'longer available to bundle — pick again.');
      }
    } catch (e) {
      showError(errorMessage(e, 'Could not start an estimate.'));
    }
  }

  // Job-derived data (materials/expenses/enriched task tree) is recomputed
  // whenever `job` changes identity — including after a parent-driven reload
  // triggered by onJobChange(), which is how a mutation's "refresh the job"
  // effect now reaches this panel (the panel no longer owns the job fetch).
  async function loadPanelData() {
    loading = true;
    loadFailures = [];
    try {
      jobMaterials = (job.materials || []).filter(m => !m.task);
      try {
        const expData = await api.get(`/api/expenses/?job=${job.job_id}`);
        // Material-less expenses surface at the job level (material-linked ones
        // are represented by their material in the tree).
        jobExpenses = (expData.results ?? expData);
      } catch (e) {
        jobExpenses = [];
        noteFailure('expenses');
      }
      await enrichTasks();
      await loadEstimateContext();
      await loadCOContext();
    } finally {
      loading = false;
    }
  }

  async function enrichTasks() {
    if (!job || !job.tasks) {
      enrichedTasks = [];
      return;
    }
    const tasks = job.tasks || [];
    const enriched = await Promise.all(tasks.map(async (task) => {
      const materials = await fetchMaterials(task.task_id);
      return { ...task, materials };
    }));
    enrichedTasks = enriched;
  }

  async function fetchMaterials(taskId) {
    try {
      return await api.get(`/api/tasks/${taskId}/materials/`);
    } catch (e) {
      noteFailure('materials');
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
      // Pass the full picked object through: the live search may know items
      // the mount-time `templates` list doesn't (created in another window),
      // and anything the search returns must be usable by the form.
      taskPresetServiceItem = choice.serviceItem;
      taskPresetName = '';
      taskModalOpen = true;
    } else if (choice.type === 'freeform-task') {
      // Manual/freeform task — WorkItemForm's manual mode; user picks the rate
      // scheme there. Typed text seeds the name.
      taskModalTask = null;
      taskModalMode = 'manual';
      taskPresetTemplateId = null;
      taskPresetServiceItem = null;
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
    }
    // No other choice shape can arrive from the task-surface picker
    // (Task / Material only) — an unexpected one deliberately does nothing.
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

<LoadState {loading}>
  <div class="page-body">
  {#if loadFailures.length}
    <p class="load-degraded" role="status">
      Some details couldn't be loaded ({loadFailures.join(', ')}). Tasks are shown without them.
      <button type="button" onclick={loadPanelData}>Retry</button>
    </p>
  {/if}
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
    {#if canOfferEstimate}
      <button type="button" onclick={handleStartEstimate}>
        {selected.length === 0
          ? 'Start Estimate'
          : `Start Estimate & Bundle ${selected.length} into a line…`}
      </button>
    {/if}
    {#if canBundle || canBundleCO}
      <button type="button" disabled={selected.length === 0}
              onclick={() => { bundleModalOpen = true; }}>
        Bundle {selected.length} selected into a line…
      </button>
    {/if}
  </div>
  {#if canBundle}
    <p class="estimate-context">
      Bundling into estimate {draftEstimate.estimate_number} (draft) —
      <a href={`#/jobs/${job.job_id}/estimate`}>view</a>
    </p>
  {:else if canBundleCO}
    <p class="estimate-context">
      Bundling into change order {draftCO.change_order_number} (draft) —
      <a href={`#/jobs/${job.job_id}/change-order/${draftCO.change_order_id}`}>view</a>
    </p>
  {:else if showChangeOrderHint}
    <p class="estimate-context">
      Job is on hold — <a href={`#/jobs/${job.job_id}/estimate`}>start a change order</a> to cover this work.
    </p>
  {/if}

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
    onReorder={handleReorder}
    onTaskClick={handleTaskClick}
    onAssignTask={(task) => { assignModalTask = task; assignModalOpen = true; }}
    onCancelTask={handleCancelTask}
    onMoveMaterial={handleMoveMaterial}
    expenses={jobExpenses}
    onEditExpense={openEditExpense}
    onDeleteExpense={handleDeleteExpense}
    onRejectExpense={handleRejectExpense}
    bind:selectedTaskId
    bundleMode={canSelectBundle}
    poolByKey={effectivePoolByKey}
    bundleSelected={selected}
    onToggleBundle={toggleBundleSelect}
    bundleClaimedLabel={draftCO ? 'on change order' : 'estimated'}
    bundleClaimedTitle={draftCO ? 'Already on the draft change order' : 'Already on the draft estimate'}
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
    presetTemplateId={taskPresetTemplateId}
    presetServiceItem={taskPresetServiceItem}
    presetName={taskPresetName}
    canManage={job?.can_manage}
    {categories}
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

  <PriceListPicker open={pickerOpen} onChoose={handleChoose} onclose={() => { pickerOpen = false; }} taskSurface={true} />

  <ExpenseModal
    open={expenseModalOpen}
    expense={editingExpense}
    initialJob={job ? { job_id: job.job_id, job_number: job.job_number } : null}
    onSaved={() => { expenseModalOpen = false; editingExpense = null; reload(); }}
    onClose={() => { expenseModalOpen = false; editingExpense = null; }}
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

  <BundleModal
    open={bundleModalOpen}
    atoms={bundleAtoms}
    apiBase={bundleApiBase}
    onCreated={handleBundleCreated}
    onConflict={handleBundleConflict}
    onClose={() => { bundleModalOpen = false; }}
  />
  </div>
</LoadState>

<style>
  .load-degraded { background: #fff7e6; border: 1px solid #f0c060; padding: 6px 10px; margin-bottom: 8px; }
  .load-degraded button { margin-left: 8px; }
  /* .toolbar (and its buttons) come from app.css. */

  .estimate-context { color: #888; font-size: 13px; margin: 4px 0 12px; }

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
