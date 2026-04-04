<script>
  let { job } = $props();

  function formatAmount(amount) {
    if (amount == null) return '$0.00';
    return Number(amount).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  }

  function formatDate(isoDate) {
    if (!isoDate) return '';
    return new Date(isoDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function borderColor() {
    if (job.status === 'completed') return '#7c3aed';
    if (job.status === 'rejected') return '#b91c1c';
    return '#64748b';
  }

  function statusLabel() {
    if (job.status === 'completed') return 'Completed';
    if (job.status === 'rejected') return 'Rejected';
    if (job.status === 'cancelled') return 'Cancelled';
    return job.status;
  }

  function statusClass() {
    return job.status;
  }

  function duration() {
    if (!job.start_date || !job.completed_date) return '';
    const start = new Date(job.start_date);
    const end = new Date(job.completed_date);
    const days = Math.round((end - start) / (1000 * 60 * 60 * 24));
    if (days < 14) return `${days} day${days !== 1 ? 's' : ''}`;
    const weeks = Math.floor(days / 7);
    const remainder = days % 7;
    if (remainder === 0) return `${weeks} week${weeks !== 1 ? 's' : ''}`;
    return `${weeks} week${weeks !== 1 ? 's' : ''} ${remainder} day${remainder !== 1 ? 's' : ''}`;
  }

  let margin = $derived(() => {
    const billed = Number(job.billed) || 0;
    if (billed === 0) return null;
    return Math.round(((billed - (Number(job.spent) || 0)) / billed) * 100);
  });
</script>

<div class="closed-card" style="border-left-color: {borderColor()};">
  <div class="card-head">
    <div class="card-head-top">
      <span class="job-name">{job.name}</span>
      <span class="substatus {statusClass()}">{statusLabel()}</span>
    </div>
    <div class="card-head-sub">
      <a class="customer" href="#/contacts/{job.contact_id}">{job.contact_name || 'No contact'}</a>
      <span class="job-num">{job.job_number}</span>
    </div>
  </div>
  <div class="card-details">
    <div class="detail-row">
      <span class="label">Start</span>
      <span class="value">{formatDate(job.start_date)}</span>
      <span class="label">End</span>
      <span class="value">{formatDate(job.completed_date)}</span>
      {#if duration()}
        <span class="duration">{duration()}</span>
      {/if}
    </div>
  </div>
  <div class="profit-row">
    <span>Billed <span class="val">{formatAmount(job.billed)}</span></span>
    <span>Spent <span class="val">{formatAmount(job.spent)}</span></span>
    <span>Profit <span class="val" class:green={Number(job.profit) >= 0} class:red={Number(job.profit) < 0}>{formatAmount(job.profit)}</span></span>
    <span class="spacer"></span>
    {#if margin() !== null}
      <span class="margin" class:green={margin() >= 0} class:red={margin() < 0}>{margin()}%</span>
    {/if}
  </div>
</div>

<style>
  .closed-card {
    background: #fff; border-radius: 10px; overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    border-left: 4px solid #9ca3af;
  }

  .card-head { padding: 8px 10px 6px; }
  .card-head-top { display: flex; align-items: baseline; gap: 6px; }
  .job-name { font-size: 13px; font-weight: 600; }
  .substatus { font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 600; margin-left: auto; }
  .substatus.completed { background: #f3e8ff; color: #7c3aed; }
  .substatus.rejected { background: #fee2e2; color: #b91c1c; }
  .substatus.cancelled { background: #f1f5f9; color: #64748b; }
  .card-head-sub { display: flex; align-items: baseline; gap: 6px; margin-top: 2px; }
  .customer { font-size: 11px; color: #2563eb; text-decoration: none; }
  .customer:hover { text-decoration: underline; }
  .job-num { font-size: 10px; color: #999; font-family: 'SF Mono', 'Fira Code', monospace; }

  .card-details { padding: 0 10px 8px; }
  .detail-row {
    display: flex; align-items: center; gap: 8px;
    font-size: 11px; color: #666; margin-top: 4px;
  }
  .label { color: #999; font-size: 10px; min-width: 36px; }
  .value { font-size: 11px; }
  .duration { margin-left: auto; font-size: 10px; color: #888; }

  .profit-row {
    display: flex; align-items: center; gap: 8px; padding: 5px 10px;
    font-size: 10px; color: #888; background: #f8f9fa; border-top: 1px solid #f0f0f0;
  }
  .val { font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; }
  .val.green, .green { color: #15803d; }
  .val.red, .red { color: #dc2626; }
  .spacer { flex: 1; }
  .margin { font-weight: 600; }
</style>
