<script>
  let { job, docs = [], borderColorOverride = null, showProgress = false } = $props();

  const SUB_STATUS_STYLES = {
    'needs-scoping':     { bg: '#f1f5f9', color: '#64748b' },
    'estimating':        { bg: '#dbeafe', color: '#2563eb' },
    'estimate-ready':    { bg: '#e0e7ff', color: '#4338ca' },
    'awaiting-response': { bg: '#fef3c7', color: '#b45309' },
    'needs-work-order':  { bg: '#dcfce7', color: '#15803d' },
    'work-ready':        { bg: '#dcfce7', color: '#0d9488' },
    'in-progress':       { bg: '#ccfbf1', color: '#0f766e' },
    'blocked':           { bg: '#fee2e2', color: '#b91c1c' },
    'invoice-prepped':   { bg: '#f3e8ff', color: '#7c3aed' },
    'invoice-sent':      { bg: '#fce7f3', color: '#be185d' },
    'needs-invoice':     { bg: '#f1f5f9', color: '#64748b' },
    'completed':         { bg: '#f3e8ff', color: '#7c3aed' },
    'rejected':          { bg: '#fee2e2', color: '#b91c1c' },
    'cancelled':         { bg: '#f1f5f9', color: '#64748b' },
  };

  const BORDER_COLORS = {
    'needs-scoping': '#64748b',
    'estimating': '#2563eb',
    'estimate-ready': '#4338ca',
    'awaiting-response': '#b45309',
    'completed': '#7c3aed',
    'rejected': '#b91c1c',
    'cancelled': '#64748b',
  };

  function pillLabel(subStatus) {
    if (!subStatus) return job.status;
    return subStatus.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function pillStyle(subStatus) {
    const key = subStatus || job.status;
    const s = SUB_STATUS_STYLES[key];
    if (!s) return '';
    return `background:${s.bg}; color:${s.color};`;
  }

  function borderColor() {
    if (borderColorOverride) return borderColorOverride;
    const key = job.sub_status || job.status;
    return BORDER_COLORS[key] || '#94a3b8';
  }

  function deadlineClass() {
    if (!job.due_date) return '';
    const due = new Date(job.due_date);
    const now = new Date();
    const daysLeft = (due - now) / (1000 * 60 * 60 * 24);
    if (daysLeft < 0) return 'overdue';
    if (daysLeft < 7) return 'soon';
    return '';
  }

  function deadlineText() {
    if (job.completed_date) {
      const label = job.status === 'rejected' ? 'Rejected' : job.status === 'cancelled' ? 'Cancelled' : 'Completed';
      return `${label} ${new Date(job.completed_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
    }
    if (!job.due_date) return '';
    const due = new Date(job.due_date);
    const now = new Date();
    if (due < now) {
      return `Overdue — was ${due.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
    }
    return `Due ${due.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
  }

  function formatDate(isoDate) {
    if (!isoDate) return '';
    return new Date(isoDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function formatAmount(amount) {
    if (amount == null) return '';
    return Number(amount).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  }

  const DOC_PILL_STYLES = {
    'draft': 'doc-pill-draft',
    'final': 'doc-pill-final',
    'open': 'doc-pill-open',
  };
</script>

<div class="job-card">
  <div class="card-border" style="background: {borderColor()};">
    <span class="border-num">{job.job_number}</span>
  </div>
  <div class="card-main">
    <div class="card-head">
      <div class="card-left">
        <div class="job-name">{job.name}</div>
        <div class="card-sub">
          {#if job.contact_name}
            <a class="card-customer" href="#/contacts/{job.contact_id}">{job.contact_name}</a>
          {/if}
        </div>
        {#if !showProgress && (job.sub_status || job.status)}
          <span class="card-substatus" style={pillStyle(job.sub_status)}>{pillLabel(job.sub_status)}</span>
        {/if}
        {#if deadlineText()}
          <div class="card-deadline {deadlineClass()}">{deadlineText()}</div>
        {/if}
      </div>
    </div>
    {#each docs as doc}
      <div class="doc-row">
        <span class="doc-type">{doc.type}</span>
        <span class="doc-pill {DOC_PILL_STYLES[doc.status] || ''}">{doc.statusLabel}</span>
        <span class="doc-date">{formatDate(doc.created_date)}</span>
        <span class="doc-amount">{formatAmount(doc.total)}</span>
      </div>
    {/each}
    {#if showProgress && job.sub_status === 'blocked'}
      <div class="blocked-banner">BLOCKED</div>
    {/if}
    {#if showProgress}
      {@const total = job.task_total ?? 0}
      {@const completed = job.task_completed ?? 0}
      {@const pct = total > 0 ? Math.round((completed / total) * 100) : 0}
      {@const barColor = borderColor()}
      <div
        class="progress-bar"
        style="background: linear-gradient(to right, {barColor} 0%, {barColor} {pct}%, color-mix(in srgb, {barColor} 18%, #fff) {pct}%, color-mix(in srgb, {barColor} 18%, #fff) 100%);"
      >
        <span class="progress-text">
          {#if total === 0}
            No tasks
          {:else}
            {pct}% complete &middot; {completed} of {total}
          {/if}
        </span>
      </div>
    {/if}
  </div>
</div>

<style>
  .job-card {
    background: #fff; border-radius: 10px; overflow: hidden; cursor: pointer;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    display: flex;
  }

  .card-border {
    width: 18px; flex-shrink: 0; position: relative;
    display: flex; align-items: center; justify-content: center;
    border-radius: 10px 0 0 10px;
  }
  .border-num {
    writing-mode: vertical-rl; text-orientation: mixed;
    transform: rotate(180deg);
    font-size: 8px; font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace;
    letter-spacing: 0.3px; white-space: nowrap; user-select: none;
    color: #fff; opacity: 0.85;
  }

  .card-main { flex: 1; min-width: 0; }

  .card-head { padding: 8px 10px 6px; }
  .card-left { min-width: 0; }
  .job-name {
    font-size: 13px; font-weight: 600; line-height: 1.3;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .card-sub { display: flex; align-items: baseline; gap: 6px; margin-top: 2px; }
  .card-customer { font-size: 11px; color: #2563eb; text-decoration: none; }
  .card-customer:hover { text-decoration: underline; }
  .card-substatus { font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 600; white-space: nowrap; display: inline-block; margin-top: 4px; }
  .card-deadline { font-size: 11px; color: #888; margin-top: 4px; }
  .card-deadline.overdue { color: #dc2626; font-weight: 600; }
  .card-deadline.soon { color: #d97706; }

  .doc-row {
    display: flex; align-items: center; gap: 6px; padding: 5px 10px;
    font-size: 11px; color: #666; background: #f8f9fb; border-top: 1px solid #f0f0f0;
  }
  .doc-type { font-weight: 600; color: #555; min-width: 62px; }
  .doc-pill { font-size: 9px; padding: 1px 6px; border-radius: 8px; font-weight: 600; }
  .doc-pill-draft { background: #f1f5f9; color: #64748b; }
  .doc-pill-final { background: #dcfce7; color: #15803d; }
  .doc-pill-open { background: #fef3c7; color: #b45309; }
  .doc-date { font-size: 10px; color: #999; }
  .doc-amount { margin-left: auto; font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; color: #333; }

  .blocked-banner {
    background: #fee2e2; color: #b91c1c; font-size: 11px; font-weight: 700;
    text-align: center; padding: 3px 0; letter-spacing: 0.5px;
    border-top: 1px solid #f0f0f0;
  }

  .progress-bar {
    position: relative;
    height: 22px;
    border-top: 1px solid #f0f0f0;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .progress-text {
    font-size: 10px;
    font-weight: 700;
    color: #fff;
    text-shadow: 0 0 3px rgba(0,0,0,0.45);
    letter-spacing: 0.3px;
  }
</style>
