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
</script>

<div class="closed-card">
  <div class="card-border" style="background: {borderColor()};">
    <span class="border-num">{job.job_number}</span>
  </div>
  <div class="card-main">
    <div class="card-head">
      <div class="card-head-top">
        <div class="card-left">
          <div class="job-name">{job.name}</div>
          <div class="card-sub">
            <a class="customer" href="#/contacts/{job.contact_id}">{job.contact_name || 'No contact'}</a>
          </div>
          <span class="substatus {statusClass()}">{statusLabel()}</span>
        </div>
        <div class="card-right">
          <div class="pr-line"><span class="pr-label">Billed</span> <span class="pr-val">{formatAmount(job.billed)}</span></div>
          <div class="pr-line"><span class="pr-label">Spent</span> <span class="pr-val">{formatAmount(job.spent)}</span></div>
          <div class="pr-line"><span class="pr-label">Profit</span> <span class="pr-val" class:green={Number(job.profit) >= 0} class:red={Number(job.profit) < 0}>{formatAmount(job.profit)}</span></div>
        </div>
      </div>
    </div>
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
</div>

<style>
  .closed-card {
    background: #fff; border-radius: 10px; overflow: hidden;
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
  .card-head-top { display: flex; align-items: flex-start; gap: 8px; }
  .card-left { flex: 1; min-width: 0; }
  .job-name { font-size: 13px; font-weight: 600; line-height: 1.3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .card-sub { display: flex; align-items: baseline; gap: 6px; margin-top: 2px; }
  .customer { font-size: 11px; color: #2563eb; text-decoration: none; }
  .customer:hover { text-decoration: underline; }
  .substatus { font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 600; display: inline-block; margin-top: 4px; }
  .substatus.completed { background: #f3e8ff; color: #7c3aed; }
  .substatus.rejected { background: #fee2e2; color: #b91c1c; }
  .substatus.cancelled { background: #f1f5f9; color: #64748b; }

  .card-right { flex-shrink: 0; text-align: right; font-size: 10px; color: #888; line-height: 1.5; }
  .pr-line { display: flex; justify-content: flex-end; gap: 3px; }
  .pr-label { color: #aaa; }
  .pr-val { font-weight: 600; font-family: 'SF Mono', 'Fira Code', monospace; min-width: 52px; text-align: right; }
  .pr-val.green { color: #15803d; }
  .pr-val.red { color: #dc2626; }

  .detail-row {
    display: flex; align-items: center; gap: 6px; padding: 0 10px 6px;
    font-size: 11px; color: #666;
  }
  .label { color: #999; font-size: 10px; }
  .value { font-size: 11px; }
  .duration { margin-left: auto; font-size: 10px; color: #888; }
</style>
