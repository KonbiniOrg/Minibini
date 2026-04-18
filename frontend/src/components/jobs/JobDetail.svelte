<script>
  import Accordion from '../Accordion.svelte';
  import HistoryPanel from '../HistoryPanel.svelte';
  import { user } from '../../stores/auth.js';
  import { api } from '../../lib/api.js';

  const {
    job,
    contact = null,
    estimates = null,
    worksheets = null,
    invoices = null,
    purchaseOrders = null,
    emails = null,
    history = null,
    onAddNote = null,
    onStatusChange = null,
    onStartWizard = null,
  } = $props();

  // Permission check
  let canManageJobs = $derived(
    $user?.permissions?.includes('can_manage_jobs') ?? false
  );
  let canManageFinancials = $derived(
    $user?.permissions?.includes('can_manage_financials') ?? false
  );

  // Valid status transitions (mirrors Job model)
  const VALID_TRANSITIONS = {
    draft: ['submitted', 'rejected'],
    submitted: ['approved', 'rejected'],
    approved: ['completed', 'cancelled'],
    rejected: [],
    completed: [],
    cancelled: [],
  };

  let validNextStatuses = $derived(VALID_TRANSITIONS[job.status] || []);

  async function handleStatusChange(e) {
    const newStatus = e.target.value;
    if (newStatus === job.status) return;
    try {
      await api.patch(`/api/jobs/${job.job_id}/`, { status: newStatus });
      if (onStatusChange) onStatusChange();
    } catch (err) {
      // Revert select on failure
      e.target.value = job.status;
      alert(err.message || 'Status change failed');
    }
  }

  // Determine which accordion opens by default
  let defaultOpen = $derived.by(() => {
    if (job.status === 'work_complete' || job.status === 'completed') {
      if (invoices?.results?.length > 0) return 'invoices';
    }
    if ((job.tasks || []).length > 0) return 'tasks';
    if (estimates?.results?.length > 0) return 'estimates';
    if (worksheets?.results?.length > 0) return 'worksheets';
    return 'worksheets';
  });

  // Current (non-superseded) estimate
  let currentEstimate = $derived(
    estimates?.results?.find(e => e.status !== 'superseded') || estimates?.results?.[0] || null
  );
  let supersededCount = $derived(
    (estimates?.results?.filter(e => e.status === 'superseded') || []).length
  );

  // Latest worksheet (highest version)
  let currentWorksheet = $derived.by(() => {
    const ws = worksheets?.results || [];
    if (ws.length === 0) return null;
    return ws.reduce((best, w) => (w.version > best.version ? w : best), ws[0]);
  });

  // Job tasks (top-level), invoice list, PO list
  let jobTasks = $derived((job.tasks || []).filter(t => !t.parent_task));
  let hasTasks = $derived(jobTasks.length > 0);
  let invList = $derived(invoices?.results || []);
  let poList = $derived(purchaseOrders?.results || []);
  let draftInvoice = $derived(invList.find(inv => inv.status === 'draft') || null);
  let canBuildInvoice = $derived(
    (canManageJobs || canManageFinancials) &&
    (job.status === 'approved' || job.status === 'work_complete' || job.status === 'completed')
  );
</script>

<div class="job-header">
  <h1>JOB #{job.job_number.replace(/^JOB-/, '')}: {job.name || '(untitled)'} {#if canManageJobs}<a href="#/jobs/{job.job_id}/edit" class="edit-link">edit</a>{/if}</h1>
  <p class="customer-line">
    {#if contact}
      for <a href="#/contacts/{contact.contact_id}">{contact.name}</a>{#if contact.business}, at <a href="#/businesses/{contact.business.business_id}">{contact.business.business_name}</a>{/if}
    {/if}
  </p>
  <div class="status-line">
    {#if canManageJobs && validNextStatuses.length > 0}
      <span class="status-select-wrapper">
        <select class="status-select status-{job.status}" onchange={handleStatusChange}>
          <option value={job.status} selected>{job.status}</option>
          {#each validNextStatuses as nextStatus}
            <option value={nextStatus}>{nextStatus}</option>
          {/each}
        </select>
      </span>
    {:else}
      <span class="status-badge status-{job.status}">{job.status}</span>
    {/if}
    <span class="dates">
      {#if job.start_date}Started {new Date(job.start_date).toLocaleDateString()}{/if}
      {#if job.due_date}{job.start_date ? ' · ' : ''}Due {new Date(job.due_date).toLocaleDateString()}{/if}
      {#if job.completed_date}{(job.start_date || job.due_date) ? ' · ' : ''}Completed {new Date(job.completed_date).toLocaleDateString()}{/if}
      {#if job.customer_po_number}{(job.start_date || job.due_date || job.completed_date) ? ' · ' : ''}PO: {job.customer_po_number}{/if}
    </span>
  </div>
</div>

<div class="desc-history">
  <div class="description">
    <div class="label">Description</div>
    <p>{job.description || 'No description.'}</p>
  </div>
  <div class="history-panel-container">
    <HistoryPanel {history} {emails} {onAddNote} />
  </div>
</div>

<Accordion
  title="Worksheet"
  meta={currentWorksheet ? `v${currentWorksheet.version} · ${currentWorksheet.status}` : 'None'}
  metaDim={(worksheets?.results?.length || 0) > 1 ? `(${worksheets.results.length} worksheets)` : ''}
  open={defaultOpen === 'worksheets'}
  headerBg="#0d9488"
  borderColor="#99f6e4"
>
  {#if currentWorksheet?.tasks?.length > 0}
    <table class="ws-table">
      <thead><tr><th>Task</th><th class="text-center">Status</th></tr></thead>
      <tbody>
        {#each currentWorksheet.tasks as task}
          <tr>
            <td>{task.name}</td>
            <td class="text-center"><span class="pill pill-{task.status}">{task.status}</span></td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="empty-msg">No worksheet data.</p>
  {/if}
  <div class="accordion-actions">
    {#if currentWorksheet}
      <a href="#/worksheets/{currentWorksheet.est_worksheet_id}">View Full Worksheet</a>
    {/if}
    {#if canManageJobs && !currentWorksheet && job.status === 'draft'}
      <a href="#/jobs/{job.job_id}/create-worksheet">Create Worksheet</a>
    {/if}
    {#if canManageJobs && currentWorksheet && !currentEstimate && (currentWorksheet.status === 'draft' || currentWorksheet.status === 'final')}
      <a href="#/worksheets/{currentWorksheet.est_worksheet_id}/generate-estimate">Generate Estimate</a>
    {/if}
  </div>
</Accordion>

<Accordion
  title="Estimate"
  meta={currentEstimate ? `${currentEstimate.estimate_number} · v${currentEstimate.version} · ${currentEstimate.status}` : 'None'}
  metaDim={supersededCount > 0 ? `(${supersededCount} previous)` : ''}
  open={defaultOpen === 'estimates'}
  headerBg="#4f46e5"
  borderColor="#c7d2fe"
>
  {#if currentEstimate?.line_items?.length > 0}
    <table class="est-table">
      <thead><tr>
        <th>#</th><th>Description</th>
        <th class="text-right">Qty</th><th class="text-right">Price</th><th class="text-right">Total</th>
      </tr></thead>
      <tbody>
        {#each currentEstimate.line_items as li}
          <tr>
            <td>{li.line_number}</td>
            <td>{li.description}</td>
            <td class="text-right">{li.qty} {li.units || ''}</td>
            <td class="text-right">${Number(li.price).toFixed(2)}</td>
            <td class="text-right">${(Number(li.qty) * Number(li.price)).toFixed(2)}</td>
          </tr>
        {/each}
      </tbody>
      <tfoot>
        <tr>
          <td colspan="4" class="text-right" style="font-weight:600;">Total</td>
          <td class="text-right" style="font-weight:700;">
            ${currentEstimate.line_items.reduce((sum, li) => sum + Number(li.qty) * Number(li.price), 0).toFixed(2)}
          </td>
        </tr>
      </tfoot>
    </table>
    {#if supersededCount > 0}
      <div class="prev-link">
        {#each estimates.results.filter(e => e.status === 'superseded') as prev}
          <a href="#/estimates/{prev.estimate_id}">{prev.estimate_number} (v{prev.version}, superseded)</a>
        {/each}
      </div>
    {/if}
  {:else if currentEstimate}
    <p class="empty-msg">Estimate has no line items.</p>
  {:else}
    <p class="empty-msg">No estimates yet.</p>
  {/if}
  <div class="accordion-actions">
    {#if currentEstimate}
      <a href="#/estimates/{currentEstimate.estimate_id}">View Full Estimate</a>
    {/if}
    {#if canManageJobs && currentEstimate && (currentEstimate.status === 'open' || currentEstimate.status === 'accepted')}
      <a href="#/estimates/{currentEstimate.estimate_id}/revise">Revise Estimate</a>
    {/if}
    {#if canManageJobs && currentEstimate?.status === 'accepted' && !hasTasks}
      <a href="#/jobs/{job.job_id}/populate-from-estimate">Populate tasks from estimate</a>
    {/if}
    {#if canManageJobs && !currentEstimate}
      <a href="#/jobs/{job.job_id}/create-estimate">Create Estimate</a>
    {/if}
  </div>
</Accordion>

<Accordion
  title="Tasks"
  meta={hasTasks ? `${jobTasks.length} task${jobTasks.length === 1 ? '' : 's'}${job.template?.name ? ' · ' + job.template.name : ''}` : 'None'}
  open={defaultOpen === 'tasks'}
  headerBg="#b45309"
  borderColor="#fbbf24"
>
  {#if hasTasks}
    <table class="wo-table">
      <thead><tr><th>Task</th><th>Assigned</th><th class="text-center">Status</th></tr></thead>
      <tbody>
        {#each jobTasks as task}
          <tr class:row-active={task.status === 'in_progress'}>
            <td><a href="#/jobs/{job.job_id}/tasks/{task.task_id}">{task.name}</a></td>
            <td class="assigned">{task.assignee_name || '—'}</td>
            <td class="text-center"><span class="pill pill-{task.status}">{task.status}</span>{#if task.status === 'blocked' && task.blocked_reason}<br><small>{task.blocked_reason}</small>{/if}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="empty-msg">No tasks yet.</p>
  {/if}
  <div class="accordion-actions">
    <a href="#/jobs/{job.job_id}/tasklist">View task list &rarr;</a>
  </div>
</Accordion>

<Accordion
  title="Invoices"
  meta={invList.length > 0 ? `${invList[0].invoice_number} · ${invList.length} invoice${invList.length > 1 ? 's' : ''}` : 'None yet'}
  open={defaultOpen === 'invoices'}
  headerBg="#15803d"
  borderColor="#bbf7d0"
>
  {#if invList.length > 0}
    <table class="inv-table">
      <thead><tr><th>Invoice #</th><th>Status</th><th class="text-right">Total</th></tr></thead>
      <tbody>
        {#each invList as inv}
          <tr>
            <td><a href="#/invoices/{inv.invoice_id}">{inv.invoice_number}</a></td>
            <td><span class="pill pill-{inv.status}">{inv.status}</span></td>
            <td class="text-right">
              ${inv.line_items?.reduce((sum, li) => sum + Number(li.qty) * Number(li.price), 0).toFixed(2) || '0.00'}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="empty-msg">No invoices created for this job yet.</p>
  {/if}
  <div class="accordion-actions">
    {#if canBuildInvoice}
      <button onclick={() => onStartWizard?.()}>
        {draftInvoice ? `Continue draft (${draftInvoice.invoice_number})` : 'Build invoice'}
      </button>
    {/if}
    {#if (canManageJobs || canManageFinancials) && hasTasks}
      <a href="#/jobs/{job.job_id}/create-invoice">Create Invoice</a>
    {/if}
  </div>
</Accordion>

<Accordion
  title="Purchase Orders"
  meta={poList.length > 0 ? `${poList[0].po_number} · ${poList.length} order${poList.length > 1 ? 's' : ''}` : 'None'}
  open={false}
  headerBg="#475569"
  borderColor="#cbd5e1"
>
  {#if poList.length > 0}
    <table class="po-table">
      <thead><tr><th>PO #</th><th>Vendor</th><th class="text-right">Total</th><th class="text-center">Status</th></tr></thead>
      <tbody>
        {#each poList as po}
          <tr>
            <td><a href="#/purchase-orders/{po.po_id}">{po.po_number}</a></td>
            <td>{po.business_name}</td>
            <td class="text-right">
              ${po.line_items?.reduce((sum, li) => sum + Number(li.qty) * Number(li.price), 0).toFixed(2) || '0.00'}
            </td>
            <td class="text-center"><span class="pill pill-{po.status}">{po.status}</span></td>
          </tr>
          {#if po.line_items?.some(li => li.effective_job_id && li.effective_job_id !== job.job_id)}
            {#each po.line_items as li}
              <tr class:other-job={li.effective_job_id && li.effective_job_id !== job.job_id}>
                <td colspan="2" style="padding-left: 32px; font-size: 13px;">
                  {li.description}
                  {#if li.effective_job_id && li.effective_job_id !== job.job_id}
                    <span class="other-job-label">(other job)</span>
                  {/if}
                </td>
                <td class="text-right" style="font-size: 13px;">${(Number(li.qty) * Number(li.price)).toFixed(2)}</td>
                <td></td>
              </tr>
            {/each}
          {/if}
        {/each}
      </tbody>
    </table>
  {:else}
    <p class="empty-msg">No purchase orders for this job.</p>
  {/if}
  <div class="accordion-actions">
    {#if canManageJobs}
      <a href="#/jobs/{job.job_id}/create-po">Create Purchase Order</a>
    {/if}
  </div>
</Accordion>

<style>
  .job-header h1 { font-size: 26px; font-weight: 700; margin-bottom: 4px; }
  .edit-link { font-size: 14px; font-weight: 400; color: #2563eb; margin-left: 12px; }
  .customer-line { font-size: 16px; color: #555; margin-bottom: 16px; }
  .status-line { margin-bottom: 20px; display: flex; align-items: center; gap: 12px; }
  .status-badge {
    padding: 4px 12px; border-radius: 12px; font-size: 13px;
    font-weight: 600; text-transform: capitalize;
  }

  /* Status dropdown styled as pill */
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
  .status-submitted { background: #dbeafe; color: #1e40af; }
  .status-approved { background: #dcfce7; color: #166534; }
  .status-complete, .status-completed { background: #dbeafe; color: #1e40af; }
  .status-rejected { background: #fee2e2; color: #991b1b; }
  .status-cancelled { background: #fef3c7; color: #92400e; }
  .dates { color: #888; font-size: 13px; margin-left: 12px; }

  .desc-history { display: flex; gap: 20px; margin-bottom: 28px; align-items: stretch; }
  .description {
    background: #f8f9fa; border: 1px solid #e5e7eb; border-radius: 6px;
    padding: 16px; min-height: 160px; flex: 1;
  }
  .description .label {
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
    color: #888; margin-bottom: 8px;
  }
  .description p { line-height: 1.6; color: #333; }
  .history-panel-container { width: 320px; min-width: 320px; }

  /* Shared table styles */
  table { width: 100%; border-collapse: collapse; font-size: 14px; border: none; }
  th { text-align: left; padding: 8px 16px; font-weight: 600; }
  td { padding: 8px 16px; }
  .text-right { text-align: right; }
  .text-center { text-align: center; }
  .assigned { color: #555; }
  .empty-msg { padding: 16px; color: #888; text-align: center; }
  .prev-link { padding: 8px 16px 12px; font-size: 13px; }

  /* Status pills */
  .pill { padding: 2px 10px; border-radius: 10px; font-size: 12px; font-weight: 500; text-transform: capitalize; }
  .pill-complete { background: #e0f2fe; color: #0369a1; }
  .pill-in_progress { background: #fef3c7; color: #92400e; }
  .pill-pending { background: #f3e8ff; color: #7c3aed; }
  .pill-draft { background: #f3f4f6; color: #6b7280; }
  .pill-final { background: #e0e7ff; color: #4338ca; }
  .pill-blocked { background: #fee2e2; color: #991b1b; }
  .pill-cancelled { background: #fecaca; color: #991b1b; }
  .pill-accepted { background: #dcfce7; color: #166534; }
  .pill-open { background: #dbeafe; color: #1e40af; }
  .pill-active { background: #dcfce7; color: #166534; }
  .pill-received { background: #e0f2fe; color: #0369a1; }
  .pill-issued { background: #dbeafe; color: #1e40af; }

  /* Worksheet table colors */
  .ws-table thead { background: #ccfbf1; }
  .ws-table thead th { color: #115e59; }
  .ws-table tbody tr { background: #f0fdfa; }
  .ws-table tbody tr:nth-child(even) { background: #e6faf5; }
  .ws-table tbody tr + tr { border-top: 1px solid #ccfbf1; }

  /* Estimate table colors */
  .est-table thead { background: #ddd6fe; }
  .est-table thead th { color: #3730a3; }
  .est-table tbody tr { background: #eef2ff; }
  .est-table tbody tr:nth-child(even) { background: #e8e5ff; }
  .est-table tbody tr + tr { border-top: 1px solid #ddd6fe; }
  .est-table tfoot { background: #e0e7ff; border-top: 2px solid #c7d2fe; }
  .est-table tfoot td { color: #3730a3; }

  /* Work Order table colors */
  .wo-table thead { background: #fde68a; }
  .wo-table thead th { color: #78350f; }
  .wo-table tbody tr { background: #fffbeb; }
  .wo-table tbody tr:nth-child(even) { background: #fef3c7; }
  .wo-table tbody tr + tr { border-top: 1px solid #fde68a; }
  .wo-table .row-active { background: #fde68a; }

  /* Invoice table colors */
  .inv-table thead { background: #bbf7d0; }
  .inv-table thead th { color: #14532d; }
  .inv-table tbody tr { background: #f0fdf4; }
  .inv-table tbody tr:nth-child(even) { background: #dcfce7; }
  .inv-table tbody tr + tr { border-top: 1px solid #bbf7d0; }

  /* PO table colors */
  .po-table thead { background: #e2e8f0; }
  .po-table thead th { color: #334155; }
  .po-table tbody tr { background: #f8fafc; }
  .po-table tbody tr:nth-child(even) { background: #f1f5f9; }
  .po-table tbody tr + tr { border-top: 1px solid #e2e8f0; }

  /* Accordion action rows */
  .accordion-actions {
    padding: 8px 16px; display: flex; gap: 8px;
    border-top: 1px solid #e5e7eb; background: #fafafa;
  }
  .accordion-actions a {
    font-size: 13px; padding: 4px 10px;
    border: 1px solid #d1d5db; border-radius: 4px;
    background: #fff; color: #374151;
  }
  .accordion-actions a:hover { background: #f3f4f6; text-decoration: none; }

  /* PO other-job differentiation */
  .other-job { opacity: 0.5; }
  .other-job-label { font-size: 11px; color: #999; font-style: italic; margin-left: 4px; }
</style>
