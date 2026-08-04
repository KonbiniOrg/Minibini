<script>
  import { link } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import AdjustmentModal from '../AdjustmentModal.svelte';
  import LineItemTable from '../LineItemTable.svelte';
  import LineItemModal from '../LineItemModal.svelte';
  import PriceListPicker from '../PriceListPicker.svelte';
  import EstimateAddLineForm from './EstimateAddLineForm.svelte';
  import DocSubnav from '../jobs/DocSubnav.svelte';
  import { buildEstimateDocItems } from '../../lib/estimateDocs.js';
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

  // Temporary: restore the create-change-order affordance to the estimate
  // toolbar (offered on an accepted estimate) until the workspace restructure
  // gives change orders their own home.
  let creatingChangeOrder = $state(false);
  async function handleCreateChangeOrder() {
    creatingChangeOrder = true;
    try {
      const co = await api.post('/api/change-orders/', { job: job.job_id });
      window.location.hash = `/jobs/${job.job_id}/change-order/${co.change_order_id}`;
    } catch (e) {
      showError(errorMessage(e, 'Failed to create change order.'));
      creatingChangeOrder = false;
    }
  }

  // One selection = one transition: ignore stray change events (and disable
  // the select) while a status PATCH is in flight — same guard as JobHeader's
  // status pill.
  let statusBusy = $state(false);

  async function handleStatusChange(e) {
    const newStatus = e.target.value;
    if (statusBusy || newStatus === estimate.status) return;
    statusBusy = true;
    try {
      await api.patch(`/api/estimates/${estimate.estimate_id}/`, { status: newStatus });
      await loadEstimate();
      // Estimate transitions drive job status (accepted → approved,
      // rejected/expired → rejected) — refresh the host's job header, same
      // as ChangeOrderPanel does on CO acceptance.
      onJobChange();
    } catch (err) {
      e.target.value = estimate.status;
      showError(errorMessage(err, 'Status change failed.'));
    } finally {
      statusBusy = false;
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
      const remembered = getJobWs(job?.job_id).modes[`est:${estimateId}`] ?? 'lines';
      mode = (remembered === 'reconcile' && canEdit) ? 'reconcile' : 'lines';
      modeInitializedFor = String(estimateId);
    }
  });

  function setMode(next) {
    mode = next;
    rememberMode(job?.job_id, `est:${estimateId}`, next);
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

  // Display-only category list, same reasoning as InvoicePanel's twin
  // (task-owned-money Phase 3, Task 4 follow-up): `categories` excludes the
  // Configuration-designated fallback category so pickers (EstimateAddLineForm,
  // LineItemModal, AdjustmentModal) never offer it, but LineItemTable's
  // read-only categoryName()/categoryTaxable() lookups need every category
  // nameable, including whichever one is currently the fallback.
  let displayCategories = $state([]);
  async function loadDisplayCategories() {
    try {
      const resp = await api.get('/api/accounting-categories/?page_size=100&include_fallback=true');
      displayCategories = resp.results || resp;
    } catch (_) {
      displayCategories = [];
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
      loadDisplayCategories();
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

  // Version subnav: estimate versions then this job's change orders, active on
  // the shown estimate. Shared with the change-order page via lib/estimateDocs.
  let subnavItems = $derived(
    buildEstimateDocItems({
      estimates,
      changeOrders,
      jobId: job.job_id,
      currentKey: `est-${estimateId}`,
    })
  );

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
  <DocSubnav items={subnavItems} section="estimate" />
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
        <!-- value-controlled like JobHeader's pill: selects keep their
             selected INDEX across option re-renders, so an uncontrolled pill
             can display the wrong option after a transition + reload. -->
        <select class="status-select status-{estimate.status}" value={estimate.status}
                onchange={handleStatusChange} disabled={statusBusy}>
          <option value={estimate.status}>{estimate.status}</option>
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
    <!-- Only the FIRST change order is created from the accepted estimate —
         further COs chain off the previous one via the CO page's "Start new
         change order" (seed-new) flow, so the button hides once any CO exists. -->
    <!-- …and only while the job is HELD: CO drafting happens inside a hold
         episode and the API refuses creation otherwise, so an un-held job's
         button could only ever produce an error. -->
    {#if canManageJobs && estimate.status === 'accepted' && changeOrders.length === 0 && job?.on_hold}
      <button type="button" onclick={handleCreateChangeOrder} disabled={creatingChangeOrder}>
        {creatingChangeOrder ? 'Creating…' : 'Create Change Order'}
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
    categories={displayCategories}
    showSource={true}
    canEdit={canEdit}
    actions={canEdit ? actionsSnippet : null}
    allowNullCategory={true}
  />

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
    <!-- Estimates belong to the quoting phase (draft/submitted): on a job
         past that (hand-approved estimate-less, or later) the backend
         refuses the create, so the button hides with a hint instead. -->
    {#if job?.can_manage && (job?.status === 'draft' || job?.status === 'submitted')}
      <button type="button" onclick={startEstimate} disabled={startingEstimate}>
        {startingEstimate ? 'Starting…' : 'Start Estimate'}
      </button>
    {:else if job?.can_manage}
      <p>No estimates. This job is past the estimating phase.</p>
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
