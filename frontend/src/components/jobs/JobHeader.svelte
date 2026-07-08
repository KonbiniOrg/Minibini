<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import FormMessage from '../FormMessage.svelte';

  const {
    job,
    contact = null,
    onStatusChange = null,
  } = $props();

  // Job-scoped management: per-object can_manage (atom-holder OR this job's PM),
  // already ANDed server-side. Gate on this alone — not the global atom store.
  let canManageJobs = $derived(job?.can_manage ?? false);

  function formatAmount(amount) {
    if (amount == null) return '$—';
    return Number(amount).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  }

  let profitNum = $derived(job.profit_amount == null ? null : Number(job.profit_amount));

  // The transitions the status pill offers — a subset of the Job model's
  // VALID_TRANSITIONS (the pill deliberately omits some, e.g. work_complete's
  // →completed/→cancelled). on_hold is a flag, not a status — the hold/release
  // buttons drive it, so it never appears here.
  const VALID_TRANSITIONS = {
    draft: ['submitted', 'rejected'],
    submitted: ['approved', 'rejected'],
    approved: ['cancelled'],
    in_progress: ['work_complete', 'cancelled'],
    work_complete: ['in_progress'],
    rejected: [],
    completed: [],
    cancelled: ['in_progress'],
  };

  const STATUS_LABELS = {
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

  // While held the backend parks the status (cancel excepted).
  let validNextStatuses = $derived(
    job.on_hold ? ['cancelled'] : (VALID_TRANSITIONS[job.status] || [])
  );

  // A hold can be placed from approved or in_progress only.
  let canHold = $derived(
    !job.on_hold && (job.status === 'approved' || job.status === 'in_progress')
  );

  // Inline hold-reason field state
  let showHoldReason = $state(false);
  let holdReasonInput = $state('');
  let holdReasonBusy = $state(false);
  let holdError = $state('');

  async function handleStatusChange(e) {
    const newStatus = e.target.value;
    if (newStatus === job.status) return;
    try {
      await api.patch(`/api/jobs/${job.job_id}/`, { status: newStatus });
      if (onStatusChange) onStatusChange();
    } catch (err) {
      e.target.value = job.status;
      showError(errorMessage(err, 'Status change failed.'));
    }
  }

  function openHoldForm() {
    holdReasonInput = '';
    holdError = '';
    showHoldReason = true;
  }

  async function confirmHold() {
    if (!holdReasonInput.trim()) {
      holdError = 'Please enter a reason for putting this job on hold.';
      return;
    }
    holdReasonBusy = true;
    holdError = '';
    try {
      await api.post(`/api/jobs/${job.job_id}/hold/`, { reason: holdReasonInput.trim() });
      showHoldReason = false;
      holdReasonInput = '';
      if (onStatusChange) onStatusChange();
    } catch (e) {
      holdError = errorMessage(e, 'Failed to put job on hold.');
    } finally {
      holdReasonBusy = false;
    }
  }

  function cancelHold() {
    showHoldReason = false;
    holdReasonInput = '';
    holdError = '';
  }

  let releasingHold = $state(false);

  async function releaseHold() {
    // No confirm: exactly undoable by holding again.
    releasingHold = true;
    try {
      await api.post(`/api/jobs/${job.job_id}/release/`, {});
      if (onStatusChange) onStatusChange();
    } catch (e) {
      showError(errorMessage(e, 'Failed to release the hold.'));
    } finally {
      releasingHold = false;
    }
  }

  let releasingToFloor = $state(false);

  async function releaseToFloor() {
    // No confirm: reversible via a hold.
    releasingToFloor = true;
    try {
      await api.patch(`/api/jobs/${job.job_id}/`, { status: 'in_progress' });
      if (onStatusChange) onStatusChange();
    } catch (e) {
      showError(errorMessage(e, 'Failed to release to floor.'));
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
      <a href="#/jobs/{job.job_id}/history" class="edit-link">history</a>
    </h1>
    <p class="customer-line">
      {#if contact}
        for <a href="#/contacts/{contact.contact_id}">{contact.name}</a>{#if contact.business}, at <a href="#/businesses/{contact.business.business_id}">{contact.business.business_name}</a>{/if}
      {/if}
    </p>
    {#if job.project_manager_name}
      <p class="pm-line">Project manager: <a href="#/jobs?pm={job.project_manager}">{job.project_manager_name}</a></p>
    {/if}
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
      {#if job.on_hold}
        <span class="status-badge on-hold-badge">On Hold</span>
      {/if}
      <span class="dates">
        {#if job.start_date}Started {new Date(job.start_date).toLocaleDateString()}{/if}
        {#if job.due_date}{job.start_date ? ' · ' : ''}Due {new Date(job.due_date).toLocaleDateString()}{/if}
        {#if job.completed_date}{(job.start_date || job.due_date) ? ' · ' : ''}Completed {new Date(job.completed_date).toLocaleDateString()}{/if}
        {#if job.customer_po_number}{(job.start_date || job.due_date || job.completed_date) ? ' · ' : ''}PO: {job.customer_po_number}{/if}
      </span>
      {#if job.status === 'approved' && !job.on_hold && canManageJobs}
        <button class="release-btn" onclick={releaseToFloor} disabled={releasingToFloor}>
          {releasingToFloor ? 'Releasing…' : 'Release to floor'}
        </button>
      {/if}
      {#if canHold && canManageJobs}
        <button class="release-btn" onclick={openHoldForm}>Put on hold</button>
      {/if}
      {#if job.on_hold && canManageJobs}
        <button class="release-btn" onclick={releaseHold} disabled={releasingHold}>
          {releasingHold ? 'Releasing…' : 'Release hold'}
        </button>
      {/if}
    </div>
    {#if job.on_hold && job.hold_reason}
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
        <FormMessage error={holdError} />
      </div>
    {/if}
  </div>
  <div class="pl-grid">
    <div class="pl-item"><div class="pl-label">Estimate</div><div class="pl-value">{formatAmount(job.estimated_amount)}</div></div>
    <div class="pl-item"><div class="pl-label">Spent</div><div class="pl-value pl-spent">{formatAmount(job.spent_amount)}</div></div>
    <div class="pl-item"><div class="pl-label">Invoiced</div><div class="pl-value pl-invoiced">{formatAmount(job.invoiced_amount)}</div></div>
    <div class="pl-item"><div class="pl-label">Profit</div><div class="pl-value" class:pl-profit-pos={profitNum != null && profitNum >= 0} class:pl-profit-neg={profitNum != null && profitNum < 0}>{formatAmount(job.profit_amount)}</div></div>
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
  /* .edit-link comes from app.css (banner-page vocabulary). */
  .customer-line, .pm-line { font-size: 13px; opacity: 0.85; margin: 2px 0 0; }
  .customer-line a, .pm-line a { color: #fff; text-decoration: underline; }
  .status-row { margin-top: 8px; display: flex; gap: 10px; align-items: center; font-size: 12px; }
  /* Colors come from the global .status-{status} classes (app.css); only the
     compact sizing for this dense band is local. */
  .status-badge { padding: 3px 10px; border-radius: 10px; font-size: 12px; }
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
  .on-hold-badge {
    background: repeating-linear-gradient(
      -45deg, #fde68a, #fde68a 6px, #fcd34d 6px, #fcd34d 12px
    );
    color: #92400e;
  }
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
  .pl-invoiced { color: #86efac; }
  .pl-profit-pos { color: #86efac; }
  .pl-profit-neg { color: #fca5a5; }
</style>
