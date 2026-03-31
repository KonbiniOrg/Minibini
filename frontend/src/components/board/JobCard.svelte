<script>
  let { job } = $props();

  const SUB_STATUS_STYLES = {
    'needs-scoping':     { bg: '#f1f5f9', color: '#64748b' },
    'estimating':        { bg: '#dbeafe', color: '#2563eb' },
    'estimate-ready':    { bg: '#e0e7ff', color: '#4338ca' },
    'awaiting-response': { bg: '#fef3c7', color: '#b45309' },
    'completed':         { bg: '#f3e8ff', color: '#7c3aed' },
    'rejected':          { bg: '#fee2e2', color: '#b91c1c' },
    'cancelled':         { bg: '#f1f5f9', color: '#64748b' },
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
</script>

<div class="job-card">
  <div class="card-top">
    <span class="card-number">{job.job_number}</span>
    {#if job.sub_status || job.status}
      <span class="card-substatus" style={pillStyle(job.sub_status)}>{pillLabel(job.sub_status)}</span>
    {/if}
  </div>
  <div class="card-name">{job.name}</div>
  {#if job.contact_name}
    <a class="card-customer" href="#/contacts/{job.contact_id}">{job.contact_name}</a>
  {/if}
  {#if deadlineText()}
    <div class="card-deadline {deadlineClass()}">{deadlineText()}</div>
  {/if}
</div>

<style>
  .job-card {
    background: #fff; border-radius: 10px; padding: 10px 12px 8px; cursor: pointer;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06); transition: transform 0.1s, box-shadow 0.15s;
  }
  .job-card:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
  .card-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
  .card-number { font-size: 11px; color: #999; font-family: 'SF Mono', 'Fira Code', monospace; }
  .card-substatus { font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 600; white-space: nowrap; }
  .card-name { font-size: 14px; font-weight: 600; line-height: 1.3; margin-bottom: 3px; }
  .card-customer { font-size: 12px; color: #2563eb; text-decoration: none; display: inline-block; }
  .card-customer:hover { text-decoration: underline; }
  .card-deadline { font-size: 11px; color: #888; margin-top: 6px; }
  .card-deadline.overdue { color: #dc2626; font-weight: 600; }
  .card-deadline.soon { color: #d97706; }
</style>
