<script>
  let { job, docs = [] } = $props();

  const SUB_STATUS_STYLES = {
    'needs-scoping':     { bg: '#f1f5f9', color: '#64748b' },
    'estimating':        { bg: '#dbeafe', color: '#2563eb' },
    'estimate-ready':    { bg: '#e0e7ff', color: '#4338ca' },
    'awaiting-response': { bg: '#fef3c7', color: '#b45309' },
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

<div class="job-card" style="border-left-color: {borderColor()};">
  <div class="card-top">
    <span class="card-number">{job.job_number}</span>
    {#if job.sub_status || job.status}
      <span class="card-substatus" style={pillStyle(job.sub_status)}>{pillLabel(job.sub_status)}</span>
    {/if}
  </div>
  <div class="card-body">
    <div class="card-name">{job.name}</div>
    {#if job.contact_name}
      <a class="card-customer" href="#/contacts/{job.contact_id}">{job.contact_name}</a>
    {/if}
    {#if deadlineText()}
      <div class="card-deadline {deadlineClass()}">{deadlineText()}</div>
    {/if}
  </div>
  {#each docs as doc}
    <div class="doc-row">
      <span class="doc-type">{doc.type}</span>
      <span class="doc-pill {DOC_PILL_STYLES[doc.status] || ''}">{doc.statusLabel}</span>
      <span class="doc-date">{formatDate(doc.created_date)}</span>
      <span class="doc-amount">{formatAmount(doc.total)}</span>
    </div>
  {/each}
</div>

<style>
  .job-card {
    background: #fff; border-radius: 10px; overflow: hidden; cursor: pointer;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06); transition: transform 0.1s, box-shadow 0.15s;
    border-left: 4px solid #94a3b8;
  }
  .job-card:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
  .card-top { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px 0; margin-bottom: 6px; }
  .card-number { font-size: 11px; color: #999; font-family: 'SF Mono', 'Fira Code', monospace; }
  .card-substatus { font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 600; white-space: nowrap; }
  .card-body { padding: 0 12px 8px; }
  .card-name { font-size: 14px; font-weight: 600; line-height: 1.3; margin-bottom: 3px; }
  .card-customer { font-size: 12px; color: #2563eb; text-decoration: none; display: inline-block; }
  .card-customer:hover { text-decoration: underline; }
  .card-deadline { font-size: 11px; color: #888; margin-top: 6px; }
  .card-deadline.overdue { color: #dc2626; font-weight: 600; }
  .card-deadline.soon { color: #d97706; }

  .doc-row {
    display: flex; align-items: center; gap: 6px; padding: 5px 12px;
    font-size: 11px; color: #666; background: #f8f9fb; border-top: 1px solid #f0f0f0;
  }
  .doc-type { font-weight: 600; color: #555; min-width: 68px; }
  .doc-pill { font-size: 9px; padding: 1px 6px; border-radius: 8px; font-weight: 600; }
  .doc-pill-draft { background: #f1f5f9; color: #64748b; }
  .doc-pill-final { background: #dcfce7; color: #15803d; }
  .doc-pill-open { background: #fef3c7; color: #b45309; }
  .doc-date { font-size: 10px; color: #999; }
  .doc-amount { margin-left: auto; font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; color: #333; }
</style>
