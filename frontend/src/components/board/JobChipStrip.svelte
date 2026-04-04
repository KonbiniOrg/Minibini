<script>
  let { jobs = [], focusedJobIds = $bindable([]) } = $props();

  function handleChipClick(jobId) {
    const next = focusedJobIds.includes(jobId)
      ? focusedJobIds.filter(id => id !== jobId)
      : [...focusedJobIds, jobId];
    // Treat "all selected" the same as "none selected" (no filter)
    focusedJobIds = next.length === jobs.length ? [] : next;
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
</script>

<div class="job-strip">
  {#each jobs as job (job.job_id)}
    <div
      class="job-chip"
      class:focused={focusedJobIds.includes(job.job_id)}
      class:dimmed={focusedJobIds.length > 0 && !focusedJobIds.includes(job.job_id)}
      onclick={() => handleChipClick(job.job_id)}
      ondblclick={() => handleChipDblClick(job.job_id)}
      role="button"
      tabindex="0"
    >
      <div class="chip-border" style="background: {job.accent_color};"></div>
      <div class="chip-body">
        <div class="chip-number">{job.job_number}</div>
        <div class="chip-name">{job.name}</div>
        {#if deadlineText(job)}
          <div class="chip-deadline {deadlineClass(job)}">{deadlineText(job)}</div>
        {/if}
      </div>
    </div>
  {/each}
</div>

<style>
  .job-strip { background: #e8f5ec; padding: 8px 12px; display: flex; gap: 8px; flex-wrap: wrap; border-bottom: 1px solid #d0e8d6; flex-shrink: 0; }
  .job-chip {
    background: #fff; border-radius: 6px; min-width: 0; flex: 1 1 120px; max-width: 180px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.06);
    cursor: pointer; transition: opacity 0.2s, box-shadow 0.2s;
    display: flex; overflow: hidden;
  }
  .chip-border { width: 8px; flex-shrink: 0; border-radius: 6px 0 0 6px; }
  .chip-body { flex: 1; min-width: 0; padding: 5px 10px; }
  .job-chip.dimmed { opacity: 0.35; }
  .job-chip.focused { box-shadow: 0 2px 8px rgba(0,0,0,0.12); }
  .chip-number { font-size: 10px; color: #999; font-family: 'SF Mono', 'Fira Code', monospace; }
  .chip-name { font-size: 11px; font-weight: 600; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin: 1px 0; }
  .chip-deadline { font-size: 10px; color: #888; }
  .chip-deadline.overdue { color: #dc2626; font-weight: 600; }
  .chip-deadline.soon { color: #d97706; }
</style>
