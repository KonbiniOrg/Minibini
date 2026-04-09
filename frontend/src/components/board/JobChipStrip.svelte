<script>
  import JobCard from './JobCard.svelte';

  let { jobs = [], focusedJobIds = $bindable([]) } = $props();

  let hoveredJobId = $state(null);
  let popupPos = $state({ anchor: 'below', y: 0, left: 0 });
  let showTimer = null;
  let hideTimer = null;

  function scheduleShow(jobId, el) {
    clearTimeout(hideTimer); hideTimer = null;
    clearTimeout(showTimer); showTimer = null;
    if (hoveredJobId === jobId) return;
    // Hide any other popup immediately when switching chips
    if (hoveredJobId !== null) hoveredJobId = null;
    showTimer = setTimeout(() => {
      const rect = el.getBoundingClientRect();
      const popupWidth = 280;
      const popupHeightEst = 160;
      let left = rect.left;
      if (left + popupWidth > window.innerWidth - 8) {
        left = window.innerWidth - popupWidth - 8;
      }
      // Anchor to card bottom (below) or card top (above, via bottom CSS)
      // so the gap stays 4px regardless of popup's actual height.
      if (rect.bottom + 4 + popupHeightEst > window.innerHeight - 8) {
        popupPos = { anchor: 'above', y: window.innerHeight - rect.top + 4, left };
      } else {
        popupPos = { anchor: 'below', y: rect.bottom + 4, left };
      }
      hoveredJobId = jobId;
    }, 300);
  }

  function scheduleHide() {
    clearTimeout(showTimer); showTimer = null;
    hideTimer = setTimeout(() => { hoveredJobId = null; }, 100);
  }

  function cancelHide() {
    clearTimeout(hideTimer); hideTimer = null;
  }

  $effect(() => () => {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
  });

  function handleChipClick(jobId) {
    const next = focusedJobIds.includes(jobId)
      ? focusedJobIds.filter(id => id !== jobId)
      : [...focusedJobIds, jobId];
    // Treat "all selected" the same as "none selected" (no filter)
    focusedJobIds = next.length === jobs.length ? [] : next;
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

  let hoveredJob = $derived(hoveredJobId !== null ? jobs.find(j => j.job_id === hoveredJobId) : null);
</script>

<div class="job-strip">
  {#each jobs as job (job.job_id)}
    <div
      class="job-chip"
      class:focused={focusedJobIds.includes(job.job_id)}
      class:blocked={job.sub_status === 'blocked'}
      class:dimmed={focusedJobIds.length > 0 && !focusedJobIds.includes(job.job_id)}
      onclick={() => handleChipClick(job.job_id)}
      onmouseenter={(e) => scheduleShow(job.job_id, e.currentTarget)}
      onmouseleave={scheduleHide}
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

{#if hoveredJob}
  <div
    class="chip-popup"
    style="{popupPos.anchor === 'above' ? 'bottom' : 'top'}: {popupPos.y}px; left: {popupPos.left}px;"
    onmouseenter={cancelHide}
    onmouseleave={scheduleHide}
  >
    <a href="#/jobs/{hoveredJob.job_id}" class="popup-link">
      <JobCard job={hoveredJob} borderColorOverride={hoveredJob.accent_color} showProgress={true} />
    </a>
  </div>
{/if}

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
  .job-chip.blocked .chip-body {
    background: repeating-linear-gradient(
      -45deg,
      transparent,
      transparent 4px,
      rgba(220, 38, 38, 0.08) 4px,
      rgba(220, 38, 38, 0.08) 8px
    );
  }
  .job-chip.dimmed { opacity: 0.35; }
  .job-chip.focused { box-shadow: 0 2px 8px rgba(0,0,0,0.12); }
  .chip-number { font-size: 10px; color: #999; font-family: 'SF Mono', 'Fira Code', monospace; }
  .chip-name { font-size: 11px; font-weight: 600; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin: 1px 0; }
  .chip-deadline { font-size: 10px; color: #888; }
  .chip-deadline.overdue { color: #dc2626; font-weight: 600; }
  .chip-deadline.soon { color: #d97706; }

  .chip-popup {
    position: fixed;
    width: 280px;
    z-index: 1000;
    filter: drop-shadow(0 4px 12px rgba(0,0,0,0.15));
  }
  .popup-link { display: block; text-decoration: none; color: inherit; }
</style>
