<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import AdjustmentModal from '../../components/AdjustmentModal.svelte';
  import JobHeader from '../../components/jobs/JobHeader.svelte';
  import LineItemTable from '../../components/LineItemTable.svelte';
  import DeliverablesSection from '../../components/jobs/DeliverablesSection.svelte';

  let { params = {} } = $props();

  let estimate = $state(null);
  let job = $state(null);
  let contact = $state(null);
  let categories = $state([]);
  let loading = $state(true);
  let error = $state('');


  let adjustmentModalOpen = $state(false);

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
      alert(e.message || 'Could not revise estimate.');
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
      alert(err.message || 'Status change failed');
    }
  }

  let lineItems = $derived(
    (estimate?.line_items || []).slice().sort((a, b) => a.line_number - b.line_number)
  );
  let isSuperseded = $derived(estimate?.status === 'superseded');
  let isDraft = $derived(estimate?.status === 'draft');
  let canEdit = $derived(canManageJobs && isDraft);

  async function loadEstimate() {
    loading = true;
    error = '';
    try {
      estimate = await api.get(`/api/estimates/${params.id}/`);
      if (estimate?.job) {
        try {
          job = await api.get(`/api/jobs/${estimate.job}/`);
          if (job?.contact) {
            try {
              contact = await api.get(`/api/contacts/${job.contact}/`);
            } catch (_) {
              contact = null;
            }
          }
        } catch (_) {
          job = null;
          contact = null;
        }
      }
    } catch (e) {
      error = e.message || 'Could not load estimate.';
    } finally {
      loading = false;
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

  $effect(() => {
    if (params.id) {
      loadEstimate();
      loadCategories();
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
      alert(e.message || 'Could not reorder line items.');
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

</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p class="error">{error}</p>
{:else if estimate}
  {#if job}
    <JobHeader {job} {contact} onStatusChange={loadEstimate} />
  {/if}

  <div class="toolbar">
    <a href={`/jobs/${estimate.job}`} use:link class="back-link">&laquo; back to overview</a>
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

  <h3>Line Items</h3>
  {#if canEdit}
    <p>
      <button type="button" onclick={() => { adjustmentModalOpen = true; }}>Add Adjustment</button>
      <a href={`/estimates/${estimate.estimate_id}/wizard`} use:link>Show Tasks &amp; Materials</a>
    </p>
  {/if}

  {#snippet actionsSnippet(li, i)}
    <!-- Reorder only here; all editing goes through Show Tasks & Materials. -->
    <button type="button" onclick={() => moveUp(i)} disabled={i === 0}>&#9650;</button>
    <button type="button" onclick={() => moveDown(i)} disabled={i === lineItems.length - 1}>&#9660;</button>
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

  <AdjustmentModal
    open={adjustmentModalOpen}
    apiBase={`/api/estimates/${estimate.estimate_id}`}
    {categories}
    onSaved={() => { adjustmentModalOpen = false; loadEstimate(); }}
    onClose={() => { adjustmentModalOpen = false; }}
  />
{/if}

<style>
  .error { color: #a8071a; }
  .superseded { opacity: 0.6; }
  .out-of-sync { color: #a55; font-size: 12px; font-weight: 600; margin-left: 6px; }
  table { border-collapse: collapse; }
  th, td { padding: 6px 10px; }

  .toolbar {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
    padding: 8px 24px;
  }
  .back-link { font-size: 13px; }
  .action-link {
    display: inline-block; padding: 4px 12px;
    border: 1px solid #d1d5db; border-radius: 3px;
    background: #fff; color: #2563eb; text-decoration: none;
    font-size: 13px; cursor: pointer;
  }
  .action-link:hover { background: #f3f4f6; }
  .page-title { font-size: 18px; font-weight: 600; }
  .status-line { margin: 8px 0 16px; display: flex; align-items: center; gap: 12px; }
  .status-badge {
    padding: 4px 12px; border-radius: 12px; font-size: 13px;
    font-weight: 600; text-transform: capitalize;
  }
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
  .status-draft { background: #f3f4f6; color: #374151; }
  .status-open { background: #dbeafe; color: #1e40af; }
  .status-accepted { background: #dcfce7; color: #166534; }
  .status-rejected { background: #fee2e2; color: #991b1b; }
  .status-expired { background: #fef3c7; color: #92400e; }
  .status-superseded { background: #fed7aa; color: #9a3412; }


</style>
