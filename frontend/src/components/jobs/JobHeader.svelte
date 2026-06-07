<script>
  import { canManageJobs as canManageJobsStore } from '../../stores/permissions.js';
  import { api } from '../../lib/api.js';

  const {
    job,
    contact = null,
    onStatusChange = null,
  } = $props();

  let canManageJobs = $derived($canManageJobsStore);

  // The transitions the status pill offers — a subset of the Job model's
  // VALID_TRANSITIONS (the pill deliberately omits some, e.g. work_complete's
  // →completed/→cancelled).
  const VALID_TRANSITIONS = {
    draft: ['submitted', 'rejected'],
    submitted: ['approved', 'rejected'],
    approved: ['on_hold', 'cancelled'],
    in_progress: ['on_hold', 'work_complete', 'cancelled'],
    on_hold: ['in_progress', 'cancelled'],
    work_complete: ['in_progress'],
    rejected: [],
    completed: [],
    cancelled: ['in_progress'],
  };

  const STATUS_LABELS = {
    on_hold: 'On Hold',
    in_progress: 'In Progress',
    work_complete: 'Work Complete',
    draft: 'Draft',
    submitted: 'Submitted',
    approved: 'Approved',
    rejected: 'Rejected',
    completed: 'Completed',
    cancelled: 'Cancelled',
  };

  function statusLabel(s) {
    return STATUS_LABELS[s] || s;
  }

  let validNextStatuses = $derived(VALID_TRANSITIONS[job.status] || []);

  // Inline hold-reason field state
  let showHoldReason = $state(false);
  let holdReasonInput = $state('');
  let holdReasonBusy = $state(false);
  let pendingHoldStatus = $state('');

  async function handleStatusChange(e) {
    const newStatus = e.target.value;
    if (newStatus === job.status) return;
    if (newStatus === 'on_hold') {
      // Reset & show inline hold-reason field rather than committing immediately
      holdReasonInput = '';
      pendingHoldStatus = newStatus;
      showHoldReason = true;
      // Reset the select back to current status — the real change happens on confirm
      e.target.value = job.status;
      return;
    }
    try {
      await api.patch(`/api/jobs/${job.job_id}/`, { status: newStatus });
      if (onStatusChange) onStatusChange();
    } catch (err) {
      e.target.value = job.status;
      alert(err.message || 'Status change failed');
    }
  }

  async function confirmHold() {
    if (!holdReasonInput.trim()) {
      alert('Please enter a reason for putting this job on hold.');
      return;
    }
    holdReasonBusy = true;
    try {
      await api.patch(`/api/jobs/${job.job_id}/`, { status: 'on_hold', hold_reason: holdReasonInput.trim() });
      showHoldReason = false;
      holdReasonInput = '';
      if (onStatusChange) onStatusChange();
    } catch (e) {
      alert(e.message || 'Failed to put job on hold.');
    } finally {
      holdReasonBusy = false;
    }
  }

  function cancelHold() {
    showHoldReason = false;
    holdReasonInput = '';
    pendingHoldStatus = '';
  }

  let releasingToFloor = $state(false);

  async function releaseToFloor() {
    // No confirm: reversible via the on-hold transition.
    releasingToFloor = true;
    try {
      await api.patch(`/api/jobs/${job.job_id}/`, { status: 'in_progress' });
      if (onStatusChange) onStatusChange();
    } catch (e) {
      alert(e.message || 'Failed to release to floor.');
    } finally {
      releasingToFloor = false;
    }
  }
</script>

<div class="job-header">
  <div class="titleblock">
    <h1>
      JOB #{job.job_number.replace(/^JOB-/, '')}: {job.name || '(untitled)'}
      {#if canManageJobs}<a href="#/jobs/{job.job_id}/edit" class="edit-link">edit</a>{/if}
      {#if canManageJobs}<a href="#/jobs/{job.job_id}/duplicate" class="edit-link">duplicate…</a>{/if}
    </h1>
    <p class="customer-line">
      {#if contact}
        for <a href="#/contacts/{contact.contact_id}">{contact.name}</a>{#if contact.business}, at <a href="#/businesses/{contact.business.business_id}">{contact.business.business_name}</a>{/if}
      {/if}
    </p>
    <div class="status-row">
      {#if canManageJobs && validNextStatuses.length > 0}
        <span class="status-select-wrapper">
          <select class="status-select status-{job.status}" onchange={handleStatusChange}>
            <option value={job.status} selected>{statusLabel(job.status)}</option>
            {#each validNextStatuses as nextStatus}
              <option value={nextStatus}>{statusLabel(nextStatus)}</option>
            {/each}
          </select>
        </span>
      {:else}
        <span class="status-badge status-{job.status}">{statusLabel(job.status)}</span>
      {/if}
      <span class="dates">
        {#if job.start_date}Started {new Date(job.start_date).toLocaleDateString()}{/if}
        {#if job.due_date}{job.start_date ? ' · ' : ''}Due {new Date(job.due_date).toLocaleDateString()}{/if}
        {#if job.completed_date}{(job.start_date || job.due_date) ? ' · ' : ''}Completed {new Date(job.completed_date).toLocaleDateString()}{/if}
        {#if job.customer_po_number}{(job.start_date || job.due_date || job.completed_date) ? ' · ' : ''}PO: {job.customer_po_number}{/if}
      </span>
      {#if job.status === 'approved' && canManageJobs}
        <button class="release-btn" onclick={releaseToFloor} disabled={releasingToFloor}>
          {releasingToFloor ? 'Releasing…' : 'Release to floor'}
        </button>
      {/if}
    </div>
    {#if job.status === 'on_hold' && job.hold_reason}
      <div class="hold-reason-display">
        <span class="hold-reason-label">Hold reason:</span>
        <span class="hold-reason-text">{job.hold_reason}</span>
      </div>
    {/if}
    {#if showHoldReason}
      <div class="hold-reason-form">
        <label for="hold-reason-input"><strong>Reason for hold *</strong></label>
        <input
          id="hold-reason-input"
          type="text"
          bind:value={holdReasonInput}
          placeholder="Describe why this job is being put on hold"
          disabled={holdReasonBusy}
        />
        <button type="button" onclick={confirmHold} disabled={holdReasonBusy || !holdReasonInput.trim()}>
          {holdReasonBusy ? 'Saving…' : 'Confirm Hold'}
        </button>
        <button type="button" onclick={cancelHold} disabled={holdReasonBusy}>Cancel</button>
      </div>
    {/if}
  </div>
  <div class="pl-grid">
    <div class="pl-item"><div class="pl-label">Estimated</div><div class="pl-value">$—</div></div>
    <div class="pl-item"><div class="pl-label">Spent</div><div class="pl-value pl-spent">$—</div></div>
    <div class="pl-item"><div class="pl-label">Billable</div><div class="pl-value pl-billable">$—</div></div>
    <div class="pl-item"><div class="pl-label">Invoiced</div><div class="pl-value pl-invoiced">$—</div></div>
  </div>
</div>

<style>
  .job-header {
    background: #1f2937;
    color: #fff;
    padding: 14px 24px;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 24px;
    align-items: center;
    height: 110px;
    box-sizing: border-box;
    flex: 0 0 auto;
    /* Establish a stacking context above the page body so the hold-reason
       form (which overflows the fixed 110px height) paints on top and stays
       clickable, instead of being covered by the content below. */
    position: relative;
    z-index: 30;
  }
  .titleblock { padding-left: 52px; min-width: 0; }
  .titleblock h1 { font-size: 22px; font-weight: 700; margin: 0; color: #fff; }
  .edit-link { font-size: 12px; font-weight: 400; opacity: 0.6; margin-left: 10px; color: #fff; text-decoration: none; }
  .edit-link:hover { opacity: 1; text-decoration: underline; }
  .customer-line { font-size: 13px; opacity: 0.85; margin: 2px 0 0; }
  .customer-line a { color: #fff; text-decoration: underline; }
  .status-row { margin-top: 8px; display: flex; gap: 10px; align-items: center; font-size: 12px; }
  .status-badge {
    padding: 3px 10px; border-radius: 10px; font-size: 12px;
    font-weight: 600; text-transform: capitalize;
  }
  .status-select-wrapper { position: relative; display: inline-block; }
  .status-select {
    appearance: none; -webkit-appearance: none;
    padding: 3px 26px 3px 10px; border-radius: 10px;
    font-size: 12px; font-weight: 600; text-transform: capitalize;
    border: 2px solid transparent; cursor: pointer; outline: none;
    transition: border-color 0.15s ease;
  }
  .status-select:hover { border-color: rgba(0,0,0,0.15); }
  .status-select:focus { border-color: rgba(0,0,0,0.3); }
  .status-select-wrapper::after {
    content: '\25BE'; position: absolute; right: 9px; top: 50%;
    transform: translateY(-50%); font-size: 10px; pointer-events: none; opacity: 0.6;
  }
  .status-draft { background: #f3f4f6; color: #374151; }
  .status-submitted { background: #dbeafe; color: #1e40af; }
  .status-approved { background: #dcfce7; color: #166534; }
  .status-in_progress { background: #fef3c7; color: #92400e; }
  .status-on_hold { background: #fde68a; color: #92400e; }
  .status-work_complete { background: #e0e7ff; color: #3730a3; }
  .status-completed { background: #dbeafe; color: #1e40af; }
  .status-rejected { background: #fee2e2; color: #991b1b; }
  .status-cancelled { background: #fef3c7; color: #92400e; }
  .dates { opacity: 0.7; }
  .release-btn { font-size: 12px; padding: 3px 10px; margin-left: 4px; }

  .hold-reason-display {
    margin-top: 4px; font-size: 12px; opacity: 0.9;
    display: flex; gap: 6px; align-items: baseline;
  }
  .hold-reason-label { font-weight: 600; opacity: 0.7; text-transform: uppercase; font-size: 10px; letter-spacing: 0.4px; }
  .hold-reason-text { font-style: italic; }

  .hold-reason-form {
    position: relative; z-index: 1;
    margin-top: 6px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
    /* Solid dark background (not translucent) so the form is legible where it
       overflows the header onto the light page body below; the shadow reads it
       as a popover floating over that content. */
    background: #1f2937; border: 1px solid rgba(255,255,255,0.18);
    box-shadow: 0 6px 16px rgba(0,0,0,0.35);
    border-radius: 6px; padding: 8px 12px;
  }
  .hold-reason-form label { font-size: 12px; white-space: nowrap; }
  .hold-reason-form input {
    font-size: 12px; padding: 3px 8px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.4);
    background: rgba(255,255,255,0.9); color: #1f2937; flex: 1 1 200px;
  }
  .hold-reason-form button { font-size: 12px; padding: 3px 10px; }

  .pl-grid {
    display: grid;
    grid-template-columns: repeat(4, auto);
    gap: 22px;
    background: rgba(255,255,255,0.06);
    padding: 10px 18px;
    border-radius: 8px;
    border: 1px solid rgba(255,255,255,0.08);
  }
  .pl-item { text-align: right; }
  .pl-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.6px; opacity: 0.65; }
  .pl-value { font-size: 18px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums; }
  .pl-spent { color: #fca5a5; }
  .pl-billable { color: #fde68a; }
  .pl-invoiced { color: #86efac; }
</style>
