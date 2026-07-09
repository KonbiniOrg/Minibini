<script>
  import { link } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import AdjustmentModal from '../AdjustmentModal.svelte';
  import LineItemTable from '../LineItemTable.svelte';
  import LineItemModal from '../LineItemModal.svelte';
  import PriceListPicker from '../PriceListPicker.svelte';
  import EstimateAddLineForm from './EstimateAddLineForm.svelte';
  import DeliverablesSection from '../jobs/DeliverablesSection.svelte';
  import DocSubnav from '../jobs/DocSubnav.svelte';
  import ReconcileMode from '../wizards/ReconcileMode.svelte';
  import { getJobWs, rememberMode } from '../../stores/jobWorkspace.js';

  let { job, estimateId, onJobChange = () => {} } = $props();

  let estimate = $state(null);
  let estimates = $state([]); // all versions for this job (raw /api/estimates/?job= results)
  let changeOrders = $state([]);
  let listLoaded = $state(false);
  let categories = $state([]);
  let defaultMaterialCategoryId = $state(null);
  let docLoading = $state(true);
  let error = $state('');


  let adjustmentModalOpen = $state(false);
  let pickerOpen = $state(false);
  let addChoice = $state(null);
  let modalOpen = $state(false);
  let modalMode = $state('edit');
  let modalItem = $state(null);

  function openEditItem(li) { modalItem = li; modalMode = 'edit'; modalOpen = true; }
  function handleSaved() { modalOpen = false; modalItem = null; loadEstimate(); }

  function handleChoose(choice) {
    pickerOpen = false;
    addChoice = choice;
  }
  function handleLineAdded() {
    addChoice = null;
    loadEstimate();
  }

  async function handleDeleteItem(li) {
    // No confirm: draft-only line edit, re-addable via Show Tasks & Materials.
    try {
      await api.delete(`/api/estimates/${estimate.estimate_id}/line-items/${li.line_item_id}/`);
      await loadEstimate();
    } catch (e) {
      showError(errorMessage(e, 'Could not delete line item.'));
    }
  }

  // Per-object gate: atom-holder OR this job's project_manager (server-computed).
  const canManageJobs = $derived(estimate?.can_manage ?? false);

  // Send Estimate (draft → open) is handled by the mark-open action, not the dropdown.
  const VALID_TRANSITIONS = {
    draft: ['rejected'],
    open: ['accepted', 'rejected', 'expired', 'superseded'],
    accepted: [],
    rejected: [],
    expired: [],
    superseded: [],
  };
  let validNextStatuses = $derived(VALID_TRANSITIONS[estimate?.status] || []);

  let revising = $state(false);

  async function handleRevise() {
    if (!confirm('Revise this estimate? This will mark the current version superseded and open a new draft.')) return;
    revising = true;
    try {
      const newEst = await api.post(`/api/estimates/${estimate.estimate_id}/revise/`);
      window.location.hash = `/estimates/${newEst.estimate_id}`;
    } catch (e) {
      showError(errorMessage(e, 'Could not revise estimate.'));
      revising = false;
    }
  }

  async function handleStatusChange(e) {
    const newStatus = e.target.value;
    if (newStatus === estimate.status) return;
    try {
      await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: newStatus });
      await loadEstimate();
    } catch (err) {
      e.target.value = estimate.status;
      showError(errorMessage(err, 'Status change failed.'));
    }
  }

  let lineItems = $derived(
    (estimate?.line_items || []).slice().sort((a, b) => a.line_number - b.line_number)
  );
  let isSuperseded = $derived(estimate?.status === 'superseded');
  let isDraft = $derived(estimate?.status === 'draft');
  let canEdit = $derived(canManageJobs && isDraft);

  // Reconcile (wizard) is a mode of this panel, not a separate route. Initial
  // mode comes from the per-doc workspace memory, but is validated against the
  // live doc: reconcile is only restorable while the estimate is still an
  // editable draft (someone may have sent it since the mode was remembered).
  let mode = $state('lines');
  let modeInitializedFor = $state(null);
  $effect(() => {
    if (estimate && String(estimate.estimate_id) === String(estimateId)
        && modeInitializedFor !== String(estimateId)) {
      const remembered = getJobWs(job?.job_id).modes[String(estimateId)] ?? 'lines';
      mode = (remembered === 'reconcile' && canEdit) ? 'reconcile' : 'lines';
      modeInitializedFor = String(estimateId);
    }
  });

  function setMode(next) {
    mode = next;
    rememberMode(job?.job_id, estimateId, next);
    // Returning to lines must show fresh data — reconcile mode may have mutated
    // the estimate's line items.
    if (next === 'lines') loadEstimate();
  }

  async function loadEstimate() {
    docLoading = true;
    error = '';
    try {
      estimate = await api.get(`/api/estimates/${estimateId}/`);
    } catch (e) {
      error = e.message || 'Could not load estimate.';
    } finally {
      docLoading = false;
    }
  }

  // Value-keyed: the glue (JobEstimatePage) assigns a new `job` object on
  // every loadJob() run, even when the job itself hasn't changed. Deriving
  // jobId memoizes on the value, so the effect below only reruns when the
  // job actually changes. The load functions read this derived (not
  // job.job_id directly) so they don't reintroduce a dependency on the raw
  // job object.
  const jobId = $derived(job?.job_id);

  async function loadVersions() {
    try {
      const resp = await api.get(`/api/estimates/?job=${jobId}`);
      estimates = resp?.results || resp || [];
    } catch (_) {
      estimates = [];
    } finally {
      listLoaded = true;
    }
  }

  async function loadChangeOrders() {
    try {
      const resp = await api.get(`/api/change-orders/?job=${jobId}`);
      changeOrders = resp?.results || resp || [];
    } catch (_) {
      changeOrders = [];
    }
  }

  async function loadCategories() {
    try {
      const resp = await api.get('/api/accounting-categories/?page_size=100');
      categories = resp.results || resp;
    } catch (_) {
      categories = [];
    }
  }

  async function loadSettings() {
    try {
      const s = await api.get('/api/settings/');
      const raw = s.default_material_accounting_category;
      defaultMaterialCategoryId = raw != null ? Number(raw) : null;
    } catch (_) {
      defaultMaterialCategoryId = null;
    }
  }

  $effect(() => {
    if (estimateId) {
      loadEstimate();
      loadCategories();
      loadSettings();
    }
  });

  $effect(() => {
    if (jobId) {
      loadVersions();
      loadChangeOrders();
    }
  });

  function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleString();
  }

  async function handleReorder(itemIds) {
    try {
      await api.post(`/api/estimates/${estimate.estimate_id}/line-items/reorder/`, {
        item_ids: itemIds,
      });
      await loadEstimate();
    } catch (e) {
      showError(errorMessage(e, 'Could not reorder line items.'));
    }
  }

  function moveUp(index) {
    if (index === 0) return;
    const ids = lineItems.map(li => li.line_item_id);
    [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]];
    handleReorder(ids);
  }

  function moveDown(index) {
    if (index >= lineItems.length - 1) return;
    const ids = lineItems.map(li => li.line_item_id);
    [ids[index], ids[index + 1]] = [ids[index + 1], ids[index]];
    handleReorder(ids);
  }

  function lineOutOfSync(li) {
    // Only meaningful on a draft estimate — once sent/accepted/superseded the line
    // can no longer be adjusted in the wizard, so flagging it would be misleading.
    if (!isDraft) return false;
    // Hand-entered lines have no sources; nothing to be out of sync with.
    if (!li.sources || li.sources.length === 0) return false;
    const sum = li.sources.reduce((s, src) => s + (parseFloat(src.computed_amount) || 0), 0);
    const qty = parseFloat(li.qty) || 0;
    if (qty <= 0) return false;
    const expected = Math.round((sum / qty) * 100) / 100;
    return Math.abs((parseFloat(li.price) || 0) - expected) > 0.001;
  }

  // Version subnav: estimate versions (oldest→newest) then this job's change
  // orders. CO entries link to the (still top-level, unchanged this pass)
  // /change-orders/:id route.
  let sortedEstimates = $derived(
    [...(estimates || [])].sort((a, b) => a.version - b.version)
  );
  let sortedChangeOrders = $derived(
    [...(changeOrders || [])].sort((a, b) => {
      if (a.change_order_number && b.change_order_number) {
        return a.change_order_number.localeCompare(b.change_order_number);
      }
      return (a.change_order_id ?? 0) - (b.change_order_id ?? 0);
    })
  );

  // Display status for estimates: show "amended" instead of "accepted" when the
  // estimate has been amended by an accepted change order. Derived server-side
  // (EstimateSerializer.is_amended); the stored status stays "accepted".
  function estimateDisplayStatus(est) {
    return est?.is_amended ? 'amended' : est?.status;
  }

  // Display status for change orders: show "amended" instead of "accepted" when
  // a later accepted CO exists on the same job (ordered by change_order_id).
  function changeOrderDisplayStatus(co, allCosForJob) {
    if (co?.status === 'accepted' && (allCosForJob || []).some(
      other => other.change_order_id > co.change_order_id
               && other.status === 'accepted'
    )) {
      return 'amended';
    }
    return co?.status;
  }

  let subnavItems = $derived([
    ...sortedEstimates.map((e) => ({
      id: `est-${e.estimate_id}`,
      label: `v${e.version}`,
      status: estimateDisplayStatus(e),
      href: `#/jobs/${job.job_id}/estimate/${e.estimate_id}`,
      current: String(e.estimate_id) === String(estimateId),
    })),
    ...sortedChangeOrders.map((co) => ({
      id: `co-${co.change_order_id}`,
      label: co.change_order_number || `CO #${co.change_order_id}`,
      status: changeOrderDisplayStatus(co, changeOrders),
      href: `#/change-orders/${co.change_order_id}`,
      current: false,
    })),
  ]);

  let startingEstimate = $state(false);
  async function startEstimate() {
    startingEstimate = true;
    try {
      // Job now owns its work atoms; an estimate is created directly off the job
      // (no intermediate worksheet/plan). Land on the new draft estimate.
      const est = await api.post('/api/estimates/', { job: job.job_id });
      window.location.hash = `/jobs/${job.job_id}/estimate/${est.estimate_id}`;
    } catch (e) {
      showError(errorMessage(e, 'Failed to start estimate.'));
    } finally {
      startingEstimate = false;
    }
  }

</script>

{#if subnavItems.length > 0}
  <DocSubnav items={subnavItems} />
{/if}

{#if estimateId}
  {#if docLoading}
    <p>Loading...</p>
  {:else if error}
    <p class="error">{error}</p>
  {:else if estimate}
  <div class="page-body">
  <div class="toolbar">
    <span class="page-title" class:superseded={isSuperseded}>Estimate: {estimate.estimate_number}</span>
    {#if canManageJobs && validNextStatuses.length > 0}
      <span class="status-select-wrapper">
        <select class="status-select status-{estimate.status}" onchange={handleStatusChange}>
          <option value={estimate.status} selected>{estimate.status}</option>
          {#each validNextStatuses as nextStatus}
            <option value={nextStatus}>{nextStatus}</option>
          {/each}
        </select>
      </span>
    {:else}
      <!-- Accepted estimate amended by an accepted change order reads "amended"
           (derived server-side as estimate.is_amended); the stored status stays
           "accepted", so the CSS class keys off the real status. -->
      <span class="status-badge status-{estimate.status}">{estimate.is_amended ? 'amended' : estimate.status}</span>
    {/if}
    {#if canManageJobs && estimate.status === 'draft'}
      <a class="action-link" href="#/estimates/{estimate.estimate_id}/send">Send Email</a>
    {/if}
    {#if canManageJobs && estimate.status === 'open'}
      <a class="action-link" href="#/estimates/{estimate.estimate_id}/send">Resend Email</a>
    {/if}
    {#if canManageJobs && estimate.status === 'open'}
      <button type="button" onclick={handleRevise} disabled={revising}>
        {revising ? 'Revising...' : 'Revise Estimate'}
      </button>
    {/if}
    {#if canEdit}
      {#if mode === 'reconcile'}
        <button type="button" onclick={() => setMode('lines')}>Back to lines</button>
      {:else}
        <button type="button" onclick={() => setMode('reconcile')}>Reconcile</button>
      {/if}
    {/if}
  </div>

  <table class="data-table" class:superseded={isSuperseded}>
    <tbody>
      <tr><th>Field</th><th>Value</th></tr>
      <tr><td>Estimate Number</td><td>{estimate.estimate_number}-{estimate.version}
        {#if estimate.parent}
          (<a href={`/estimates/${estimate.parent}`} use:link>Parent</a>)
        {/if}
      </td></tr>
      <tr>
        <td>Job</td>
        <td>
          {#if job}
            <a href={`/jobs/${estimate.job}`} use:link>{job.job_number}{job.name ? `: ${job.name}` : ''}</a>
          {:else}
            <a href={`/jobs/${estimate.job}`} use:link>Job #{estimate.job}</a>
          {/if}
        </td>
      </tr>
      <tr><td>Status</td><td>{estimate.status}</td></tr>
      <tr><td>Created Date</td><td>{fmtDate(estimate.created_date)}</td></tr>
      <tr><td>Sent Date</td><td>{estimate.sent_date ? fmtDate(estimate.sent_date) : 'Not sent yet'}</td></tr>
      <tr><td>Expiration Date</td><td>{estimate.expiration_date ? fmtDate(estimate.expiration_date) : 'Not set'}</td></tr>
      <tr><td>Closed Date</td><td>{estimate.closed_date ? fmtDate(estimate.closed_date) : 'Not closed yet'}</td></tr>
    </tbody>
  </table>

  {#if isSuperseded}
    <p><em>This estimate has been superseded and cannot be modified.</em></p>
  {/if}

  {#if mode === 'reconcile'}
    <ReconcileMode
      docType="estimate"
      docId={estimate.estimate_id}
      onChanged={loadEstimate}
      onExit={() => setMode('lines')}
    />
  {:else}
  <h3>Line Items</h3>
  {#if canEdit}
    <p>
      <button type="button" onclick={() => { pickerOpen = true; }}>Add line</button>
      <button type="button" onclick={() => { adjustmentModalOpen = true; }}>Add Adjustment</button>
      <button type="button" onclick={() => setMode('reconcile')}>Show Tasks &amp; Materials</button>
    </p>
  {/if}

  {#snippet actionsSnippet(li, i)}
    <button type="button" onclick={() => openEditItem(li)}>Edit</button>
    <button type="button" onclick={() => moveUp(i)} disabled={i === 0}>&#9650;</button>
    <button type="button" onclick={() => moveDown(i)} disabled={i === lineItems.length - 1}>&#9660;</button>
    <button type="button" onclick={() => handleDeleteItem(li)}>Delete</button>
    {#if lineOutOfSync(li)}
      <span class="out-of-sync" title="The line no longer matches its atoms; adjust in Show Tasks &amp; Materials if needed.">⚠ out of sync with atoms</span>
    {/if}
  {/snippet}

  <LineItemTable
    {lineItems}
    {categories}
    showSource={true}
    canEdit={canEdit}
    actions={canEdit ? actionsSnippet : null}
  />

  {#if estimate.job}
    <DeliverablesSection jobId={estimate.job} canManage={estimate.can_manage} />
  {/if}

  <PriceListPicker open={pickerOpen} onChoose={handleChoose} onclose={() => { pickerOpen = false; }} />

  <EstimateAddLineForm
    open={addChoice != null}
    choice={addChoice}
    estimateId={estimate.estimate_id}
    {categories}
    {defaultMaterialCategoryId}
    onSaved={handleLineAdded}
    onClose={() => { addChoice = null; }}
  />

  <LineItemModal
    open={modalOpen}
    mode={modalMode}
    apiBase={`/api/estimates/${estimate.estimate_id}`}
    item={modalItem}
    {categories}
    showMaterialMarker={true}
    {defaultMaterialCategoryId}
    onSaved={handleSaved}
    onClose={() => { modalOpen = false; }}
  />

  <AdjustmentModal
    open={adjustmentModalOpen}
    apiBase={`/api/estimates/${estimate.estimate_id}`}
    {categories}
    onSaved={() => { adjustmentModalOpen = false; loadEstimate(); }}
    onClose={() => { adjustmentModalOpen = false; }}
  />
  {/if}
  </div>
  {/if}
{:else if !listLoaded}
  <p>Loading...</p>
{:else}
  <div class="page-body">
    {#if job?.can_manage}
      <button type="button" onclick={startEstimate} disabled={startingEstimate}>
        {startingEstimate ? 'Starting…' : 'Start Estimate'}
      </button>
    {:else}
      <p>No estimates yet.</p>
    {/if}
  </div>
{/if}

<style>
  .error { color: #a8071a; }
  .superseded { opacity: 0.6; }
  .out-of-sync { color: #a55; font-size: 12px; font-weight: 600; margin-left: 6px; }
  table { border-collapse: collapse; }
  th, td { padding: 6px 10px; }

  /* .toolbar / .action-link / .page-title come from app.css. */
  .status-line { margin: 8px 0 16px; display: flex; align-items: center; gap: 12px; }
  /* Pill styling/colors come from the global .status-badge / .status-{status}
     classes (app.css); the select keeps its local control styling. */
  .status-select-wrapper { position: relative; display: inline-block; }
  .status-select {
    appearance: none; -webkit-appearance: none;
    padding: 4px 28px 4px 12px; border-radius: 12px;
    font-size: 13px; font-weight: 600; text-transform: capitalize;
    border: 2px solid transparent; cursor: pointer; outline: none;
    transition: border-color 0.15s ease;
  }
  .status-select:hover { border-color: rgba(0,0,0,0.15); }
  .status-select:focus { border-color: rgba(0,0,0,0.3); }
  .status-select-wrapper::after {
    content: '\25BE'; position: absolute; right: 10px; top: 50%;
    transform: translateY(-50%); font-size: 11px; pointer-events: none; opacity: 0.6;
  }
</style>
