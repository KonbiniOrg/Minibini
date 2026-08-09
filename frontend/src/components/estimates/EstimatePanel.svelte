<script>
  import { link } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import DocSubnav from '../jobs/DocSubnav.svelte';
  import { buildEstimateDocItems } from '../../lib/estimateDocs.js';
  import { formatQtyUnits } from '../../lib/format.js';
  import DocModeBar from '../docsurface/DocModeBar.svelte';
  import DocCustomerView from '../docsurface/DocCustomerView.svelte';
  import DocReorderView from '../docsurface/DocReorderView.svelte';
  import EstimateEditView from './EstimateEditView.svelte';
  import { getJobWs, rememberMode } from '../../stores/jobWorkspace.js';

  let { job, estimateId, onJobChange = () => {} } = $props();

  let estimate = $state(null);
  let estimates = $state([]); // all versions for this job (raw /api/estimates/?job= results)
  let changeOrders = $state([]);
  let listLoaded = $state(false);
  let categories = $state([]);
  let defaultMaterialCategoryId = $state(null);
  let sourcePool = $state(null);
  let docLoading = $state(true);
  let error = $state('');

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

  // Doc-shaped rows for the read-only Customer/Reorder kit views — ALL lines
  // including adjustments, numbered as stored. `line_id` (not just
  // line_number) is required: DocReorderView's onReorder callback needs the
  // real line_item_id to build the reorder payload.
  let docLines = $derived(
    lineItems.map((li) => ({
      line_id: li.line_item_id,
      line_number: li.line_number,
      description: li.description,
      qty_display: formatQtyUnits(li.qty, li.units),
      price: li.price,
      amount: Number(li.qty || 0) * Number(li.price || 0),
    }))
  );

  // The mode bar is a surface of this panel, not a separate route. Initial
  // mode comes from the per-doc workspace memory; legacy remembered values
  // ('lines' from the old two-mode panel, 'reconcile' from the old wizard
  // toggle) normalize to 'edit' here at the read site — the store itself
  // keeps whatever was written, unmigrated. Reorder is only restorable while
  // the estimate is still an editable draft (someone may have sent it since
  // the mode was remembered).
  let mode = $state('edit');
  let modeInitializedFor = $state(null);
  let modes = $derived(canEdit ? ['edit', 'customer', 'reorder'] : ['edit', 'customer']);
  $effect(() => {
    if (estimate && String(estimate.estimate_id) === String(estimateId)
        && modeInitializedFor !== String(estimateId)) {
      const remembered = getJobWs(job?.job_id).modes[`est:${estimateId}`] ?? 'edit';
      const normalized = (remembered === 'lines' || remembered === 'reconcile') ? 'edit' : remembered;
      mode = (normalized === 'reorder' && !canEdit) ? 'edit' : normalized;
      modeInitializedFor = String(estimateId);
    }
  });

  function setMode(next) {
    mode = next;
    rememberMode(job?.job_id, `est:${estimateId}`, next);
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

  async function loadSourcePool() {
    try {
      sourcePool = await api.get(`/api/estimates/${estimateId}/source-pool/`);
    } catch (_) {
      sourcePool = { atoms: [] };
    }
  }

  // EstimateEditView is presentation + gestures only — every mutation it
  // makes (add/remove atoms, add/edit/remove a line, adjustments) calls back
  // here so the doc and the uncovered-work pool stay in sync.
  async function handleEditChanged() {
    await Promise.all([loadEstimate(), loadSourcePool()]);
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
      loadSourcePool();
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

  // Reorder mode: swap the doc-shaped line's line_item_id with its up/down
  // neighbor and send the full order (same endpoint the old lines-view
  // up/down arrows used).
  async function handleReorderDoc(lineId, direction) {
    const ids = lineItems.map((li) => li.line_item_id);
    const idx = ids.indexOf(lineId);
    if (idx === -1) return;
    const swapIdx = direction === 'up' ? idx - 1 : idx + 1;
    if (swapIdx < 0 || swapIdx >= ids.length) return;
    [ids[idx], ids[swapIdx]] = [ids[swapIdx], ids[idx]];
    try {
      await api.post(`/api/estimates/${estimate.estimate_id}/line-items/reorder/`, {
        item_ids: ids,
      });
      await loadEstimate();
    } catch (e) {
      showError(errorMessage(e, 'Could not reorder line items.'));
    }
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

  <DocModeBar {mode} onMode={setMode} {modes} />

  {#if mode === 'edit'}
    <EstimateEditView
      {estimate}
      {canEdit}
      onChanged={handleEditChanged}
      {sourcePool}
      {lineItems}
      {categories}
      {defaultMaterialCategoryId}
    />
  {:else if mode === 'customer'}
    <DocCustomerView
      title={`Estimate ${estimate.estimate_number}-${estimate.version}`}
      lines={docLines}
      grandTotal={Number(estimate.total)}
    />
  {:else if mode === 'reorder'}
    <DocReorderView
      title={`Estimate ${estimate.estimate_number}-${estimate.version}`}
      lines={docLines}
      grandTotal={Number(estimate.total)}
      onReorder={handleReorderDoc}
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
