<script>
  let { jobs = [], focusedJobId = $bindable(null) } = $props();

  const SUB_STATUS_STYLES = {
    'needs-work-order': { bg: '#dcfce7', color: '#15803d' },
    'work-ready':       { bg: '#dcfce7', color: '#0d9488' },
    'in-progress':      { bg: '#ccfbf1', color: '#0f766e' },
    'blocked':          { bg: '#fee2e2', color: '#b91c1c' },
    'invoice-prepped':  { bg: '#f3e8ff', color: '#7c3aed' },
    'invoice-sent':     { bg: '#fce7f3', color: '#be185d' },
  };

  function handleChipClick(jobId) {
    focusedJobId = focusedJobId === jobId ? null : jobId;
  }

  function handleChipDblClick(jobId) {
    window.location.hash = `#/jobs/${jobId}`;
  }

  function deadlineClass(job) {
    if (!job.due_date) return '';
    const due = new Date(job.due_date);
    const now = new Date();
    if (due < now) return 'overdue';
    if ((due - now) / 86400000 < 7) return 'soon';
    return '';
  }

  function deadlineText(job) {
    if (!job.due_date) return '';
    const due = new Date(job.due_date);
    if (due < new Date()) return `Overdue — ${due.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
    return `Due ${due.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
  }

  function pillStyle(subStatus) {
    const s = SUB_STATUS_STYLES[subStatus];
    if (!s) return '';
    return `background:${s.bg}; color:${s.color};`;
  }

  function pillLabel(subStatus) {
    if (!subStatus) return '';
    return subStatus.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }
</script>

<div class="job-strip">
  {#each jobs as job (job.job_id)}
    <div
      class="job-chip"
      class:focused={focusedJobId === job.job_id}
      class:dimmed={focusedJobId !== null && focusedJobId !== job.job_id}
      style="border-left-color: {job.accent_color};"
      onclick={() => handleChipClick(job.job_id)}
      ondblclick={() => handleChipDblClick(job.job_id)}
      role="button"
      tabindex="0"
    >
      {#if focusedJobId === job.job_id}
        <button class="clear-focus" onclick={(e) => { e.stopPropagation(); focusedJobId = null; }}>×</button>
      {/if}
      <div class="chip-number">{job.job_number}</div>
      <div class="chip-name">{job.name}</div>
      {#if deadlineText(job)}
        <div class="chip-deadline {deadlineClass(job)}">{deadlineText(job)}</div>
      {/if}
      <div class="chip-overlay" style="border-left-color: {job.accent_color};">
        <div class="overlay-customer">{job.contact_name || 'No contact'}</div>
        {#if job.sub_status}
          <span class="overlay-status" style={pillStyle(job.sub_status)}>{pillLabel(job.sub_status)}</span>
        {/if}
      </div>
    </div>
  {/each}
</div>

<style>
  .job-strip { background: #e8f5ec; padding: 8px 12px; display: flex; gap: 8px; flex-wrap: wrap; border-bottom: 1px solid #d0e8d6; flex-shrink: 0; }
  .job-chip {
    background: #fff; border-radius: 6px; padding: 5px 10px; min-width: 0; flex: 1 1 120px; max-width: 180px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.06); border-left: 4px solid transparent;
    cursor: pointer; transition: opacity 0.2s, box-shadow 0.2s; position: relative;
  }
  .job-chip.dimmed { opacity: 0.35; }
  .job-chip.focused { box-shadow: 0 2px 8px rgba(0,0,0,0.12); }
  .clear-focus {
    position: absolute; top: 2px; right: 4px; background: none; border: none;
    font-size: 14px; color: #999; cursor: pointer; padding: 0 3px; line-height: 1;
  }
  .clear-focus:hover { color: #333; }
  .chip-number { font-size: 10px; color: #999; font-family: 'SF Mono', 'Fira Code', monospace; }
  .chip-name { font-size: 11px; font-weight: 600; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin: 1px 0; }
  .chip-deadline { font-size: 10px; color: #888; }
  .chip-deadline.overdue { color: #dc2626; font-weight: 600; }
  .chip-deadline.soon { color: #d97706; }
  .chip-overlay {
    display: none; position: absolute; left: -4px; top: calc(100% + 6px);
    background: #fff; border-radius: 8px; padding: 10px 12px;
    box-shadow: 0 6px 20px rgba(0,0,0,0.15); border-left: 4px solid transparent;
    z-index: 100; min-width: 200px; white-space: nowrap;
  }
  .job-chip:hover .chip-overlay { display: block; }
  .overlay-customer { font-size: 12px; color: #2563eb; margin-bottom: 4px; }
  .overlay-status { font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 600; display: inline-block; }
</style>
