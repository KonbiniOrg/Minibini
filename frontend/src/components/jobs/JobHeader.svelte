<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import FormMessage from '../FormMessage.svelte';
  import Modal from '../Modal.svelte';
  import JobEditModal from './JobEditModal.svelte';
  import DuplicateJobModal from './DuplicateJobModal.svelte';

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
  // →completed/→cancelled). The pill also carries *trigger* options that are
  // not statuses (values prefixed __): "Hold…" opens the reason modal and
  // "Release hold" posts the release — on_hold stays a flag, never a status.
  const VALID_TRANSITIONS = {
    draft: ['submitted', 'rejected'],
    submitted: ['approved', 'rejected'],
    approved: ['in_progress', 'cancelled'],
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

  // Trigger labels: the pill names the *act*, not the resulting status, where
  // the act is the clearer read (releasing an approved job to the floor).
  function transitionLabel(next) {
    if (job.status === 'approved' && next === 'in_progress') return 'Release to floor';
    return statusLabel(next);
  }

  // While held the backend parks the status (cancel excepted).
  // Approved is offered only on estimate-less jobs: once a job has any
  // estimate, approval flows from accepting the estimate (the backend
  // rejects a direct edit — see JobService.update_job).
  let validNextStatuses = $derived(
    job.on_hold
      ? ['cancelled']
      : (VALID_TRANSITIONS[job.status] || []).filter(
          (s) => s !== 'approved' || !job.has_estimates)
  );

  // A hold can be placed from approved or in_progress only.
  let canHold = $derived(
    !job.on_hold && (job.status === 'approved' || job.status === 'in_progress')
  );

  // Held jobs hide their true status: the pill just says HOLD.
  let pillLabel = $derived(job.on_hold ? 'HOLD' : statusLabel(job.status));

  // A closed job doesn't offer Edit (Duplicate stays — cloning a finished
  // job is a normal way to start the next one).
  let isTerminal = $derived(
    ['completed', 'rejected', 'cancelled'].includes(job.status)
  );

  let showStatusSelect = $derived(
    canManageJobs && (validNextStatuses.length > 0 || canHold || job.on_hold)
  );

  let titleText = $derived(`JOB #${job.job_number.replace(/^JOB-/, '')}: ${job.name || '(untitled)'}`);

  // Right-column facts line: dates + customer PO as one dot-joined string;
  // the PM link renders separately so it can stay an <a>.
  let factsText = $derived([
    job.start_date ? `Started ${new Date(job.start_date).toLocaleDateString()}` : null,
    job.due_date ? `Due ${new Date(job.due_date).toLocaleDateString()}` : null,
    job.completed_date ? `Completed ${new Date(job.completed_date).toLocaleDateString()}` : null,
    job.customer_po_number ? `PO: ${job.customer_po_number}` : null,
  ].filter(Boolean).join(' · '));

  // Edit / Duplicate modals — openable from any job page (the header is the
  // one place both are always mounted). History moved to the rail.
  let editOpen = $state(false);
  let dupOpen = $state(false);

  // One selection = one transition: while a PATCH is in flight the pill is
  // disabled and any stray second change event is ignored, so a double-click
  // (or an event firing against the re-rendered option list) can't chain two
  // transitions in a single gesture.
  let statusBusy = $state(false);

  async function handleStatusChange(e) {
    const picked = e.target.value;
    if (statusBusy || picked === job.status) return;
    // Trigger options aren't statuses: snap the pill back to the current
    // value immediately — the trigger's own flow (modal / API + reload)
    // decides what actually happens.
    if (picked === '__hold') {
      e.target.value = job.status;
      openHoldModal();
      return;
    }
    if (picked === '__release_hold') {
      e.target.value = job.status;
      releaseHold();
      return;
    }
    statusBusy = true;
    try {
      await api.patch(`/api/jobs/${job.job_id}/`, { status: picked });
      if (onStatusChange) onStatusChange();
    } catch (err) {
      e.target.value = job.status;
      showError(errorMessage(err, 'Status change failed.'));
    } finally {
      statusBusy = false;
    }
  }

  // Hold-reason modal state
  let holdModalOpen = $state(false);
  let holdReasonInput = $state('');
  let holdReasonBusy = $state(false);
  let holdError = $state('');

  function openHoldModal() {
    holdReasonInput = '';
    holdError = '';
    holdModalOpen = true;
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
      holdModalOpen = false;
      holdReasonInput = '';
      if (onStatusChange) onStatusChange();
    } catch (e) {
      holdError = errorMessage(e, 'Failed to put job on hold.');
    } finally {
      holdReasonBusy = false;
    }
  }

  function cancelHold() {
    holdModalOpen = false;
    holdReasonInput = '';
    holdError = '';
  }

  async function releaseHold() {
    // No confirm: exactly undoable by holding again.
    try {
      await api.post(`/api/jobs/${job.job_id}/release/`, {});
      if (onStatusChange) onStatusChange();
    } catch (e) {
      showError(errorMessage(e, 'Failed to release the hold.'));
    }
  }
</script>

<div class="job-header">
  <div class="titleblock">
    <h1 title={titleText}>{titleText}</h1>
    <p class="customer-line">
      {#if contact}
        for <a href="#/contacts/{contact.contact_id}">{contact.name}</a>{#if contact.business}, at <a href="#/businesses/{contact.business.business_id}">{contact.business.business_name}</a>{/if}
      {/if}
    </p>
    <div class="status-row">
      {#if canManageJobs}
        {#if !isTerminal}
          <button type="button" class="edit-link header-action" onclick={() => { editOpen = true; }}>Edit</button>
        {/if}
        <button type="button" class="edit-link header-action" onclick={() => { dupOpen = true; }}>Duplicate…</button>
      {/if}
      {#if showStatusSelect}
        <span class="status-select-wrapper">
          <!-- value-controlled: a native select keeps its selected INDEX when
               the options re-render, so after a transition + reload an
               uncontrolled pill displays the option at the clicked index —
               which is now the NEXT transition (approved-click showed
               "Work Complete"). Pinning value to job.status makes every
               render show the real current status. -->
          <select
            class="status-select {job.on_hold ? 'on-hold-pill' : `status-${job.status}`}"
            value={job.status}
            onchange={handleStatusChange}
            disabled={statusBusy}
          >
            <option value={job.status}>{pillLabel}</option>
            {#if job.on_hold}
              <option value="__release_hold">Release hold</option>
            {/if}
            {#each validNextStatuses as nextStatus}
              <option value={nextStatus}>{transitionLabel(nextStatus)}</option>
            {/each}
            {#if canHold}
              <option value="__hold">Hold…</option>
            {/if}
          </select>
        </span>
      {:else}
        <span class="status-badge {job.on_hold ? 'on-hold-pill' : `status-${job.status}`}">{pillLabel}</span>
      {/if}
      {#if job.on_hold && job.hold_reason}
        <span class="hold-reason" title={job.hold_reason}>
          <span class="hold-reason-label">Why:</span> {job.hold_reason}
        </span>
      {/if}
    </div>
  </div>
  <div class="factblock">
    <div class="facts-line">
      {factsText}{#if job.project_manager_name}{factsText ? ' · ' : ''}PM: <a href="#/jobs?pm={job.project_manager}">{job.project_manager_name}</a>{/if}
    </div>
    <div class="pl-grid">
      <div class="pl-item"><div class="pl-label">Estimate</div><div class="pl-value">{formatAmount(job.estimated_amount)}</div></div>
      <div class="pl-item"><div class="pl-label">Spent</div><div class="pl-value pl-spent">{formatAmount(job.spent_amount)}</div></div>
      <div class="pl-item"><div class="pl-label">Invoiced</div><div class="pl-value pl-invoiced">{formatAmount(job.invoiced_amount)}</div></div>
      <div class="pl-item"><div class="pl-label">Profit</div><div class="pl-value" class:pl-profit-pos={profitNum != null && profitNum >= 0} class:pl-profit-neg={profitNum != null && profitNum < 0}>{formatAmount(job.profit_amount)}</div></div>
    </div>
  </div>
</div>

<Modal open={holdModalOpen} onSave={confirmHold} onCancel={cancelHold} busy={holdReasonBusy} maxWidth="520px" label="Put job on hold">
  <h3 class="hold-modal-title">Put job on hold</h3>
  <label class="hold-modal-label" for="hold-reason-input">Reason for hold *</label>
  <input
    id="hold-reason-input"
    type="text"
    bind:value={holdReasonInput}
    placeholder="Describe why this job is being put on hold"
    disabled={holdReasonBusy}
  />
  <div class="hold-modal-actions">
    <button type="button" onclick={confirmHold} disabled={holdReasonBusy || !holdReasonInput.trim()}>
      {holdReasonBusy ? 'Saving…' : 'Confirm Hold'}
    </button>
    <button type="button" onclick={cancelHold} disabled={holdReasonBusy}>Cancel</button>
  </div>
  <FormMessage error={holdError} />
</Modal>

<JobEditModal
  {job}
  open={editOpen}
  onSaved={() => { editOpen = false; if (onStatusChange) onStatusChange(); }}
  onClose={() => { editOpen = false; }}
/>

<DuplicateJobModal
  {job}
  open={dupOpen}
  onClose={() => { dupOpen = false; }}
/>

<style>
  /* Fixed-height banner: the left titleblock is a hard three-line budget
     (truncating title / customer / status row) and the right factblock is
     facts line + money grid, so nothing optional can grow the header. */
  .job-header {
    background: #1f2937;
    color: #fff;
    padding: 14px 24px;
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 24px;
    align-items: center;
    height: 110px;
    box-sizing: border-box;
    flex: 0 0 auto;
  }

  .titleblock { padding-left: 52px; min-width: 0; }
  .titleblock h1 {
    font-size: 22px; font-weight: 700; margin: 0; color: #fff;
    /* The title may never wrap: it truncates, full name on hover. */
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }

  .customer-line { font-size: 13px; opacity: 0.85; margin: 2px 0 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .customer-line a { color: #fff; text-decoration: underline; }

  .status-row { margin-top: 8px; display: flex; gap: 10px; align-items: center; font-size: 12px; min-width: 0; }
  /* Colors come from the global .status-{status} classes (app.css); only the
     compact sizing for this dense band is local. */
  .status-badge { padding: 3px 10px; border-radius: 10px; font-size: 12px; flex: 0 0 auto; }
  .status-select-wrapper { position: relative; display: inline-block; flex: 0 0 auto; }
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
  /* Held jobs: the pill (select or read-only badge) wears the hold stripes
     and says HOLD — the true status is deliberately not visible. */
  .on-hold-pill {
    background: repeating-linear-gradient(
      -45deg, #fde68a, #fde68a 6px, #fcd34d 6px, #fcd34d 12px
    );
    color: #92400e;
  }
  .hold-reason {
    font-style: italic; opacity: 0.9;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    min-width: 0; flex: 0 1 auto;
  }
  .hold-reason-label {
    font-style: normal; font-weight: 600; opacity: 0.7;
    text-transform: uppercase; font-size: 10px; letter-spacing: 0.4px;
  }
  .factblock { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
  .facts-line { font-size: 14px; opacity: 0.9; white-space: nowrap; position: relative; top: -3px; }
  .facts-line a { color: #fff; text-decoration: underline; }

  .pl-grid {
    display: grid;
    grid-template-columns: repeat(4, auto);
    gap: 22px;
    background: rgba(255,255,255,0.06);
    padding: 8px 18px;
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

  /* Hold modal content (shell geometry comes from Modal.svelte) */
  .hold-modal-title { margin: 0 0 12px; font-size: 16px; }
  .hold-modal-label { display: block; font-weight: 600; font-size: 13px; margin-bottom: 4px; }
  #hold-reason-input { width: 100%; box-sizing: border-box; padding: 6px 8px; font-size: 13px; }
  .hold-modal-actions { display: flex; gap: 8px; margin-top: 12px; }
</style>
