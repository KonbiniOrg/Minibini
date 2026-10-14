<script>
  import JobCard from './JobCard.svelte';
  import NewJobButton from './NewJobButton.svelte';
  let { jobs = [] } = $props();

  // Pipeline order, top to bottom. Colors match JobCard.BORDER_COLORS so a
  // section header reads as the tab of the cards beneath it. Each card's
  // `section` is computed server-side (BoardService.pipeline_section) from
  // the job's status and estimates, hold flag ignored — a held card's pill
  // still says on-hold; its section says where it sits.
  const SECTIONS = [
    { key: 'needs-scoping',     label: 'Inquiries',         color: '#64748b' },
    { key: 'estimating',        label: 'Estimating',        color: '#2563eb' },
    { key: 'awaiting-response', label: 'Awaiting Approval', color: '#b45309' },
    { key: 'awaiting-prep',     label: 'Awaiting Prep',     color: '#ca8a04' },
  ];

  let sections = $derived(
    SECTIONS
      .map(s => ({ ...s, jobs: jobs.filter(j => j.section === s.key) }))
      .filter(s => s.jobs.length > 0)
  );

  const ESTIMATE_LABELS = {
    draft: 'Draft',
    open: 'Sent',
    accepted: 'Accepted',
    rejected: 'Rejected',
    expired: 'Expired',
  };

  function buildDocs(job) {
    const docs = [];
    if (job.estimates) {
      for (const est of job.estimates) {
        if (est.status === 'superseded') continue;
        docs.push({
          type: 'Estimate',
          status: est.status,
          statusLabel: est.is_amended
            ? 'Amended'
            : (ESTIMATE_LABELS[est.status] || est.status),
          created_date: est.created_date,
          total: est.total,
        });
      }
    }
    return docs;
  }
</script>

<div class="column-header">
  <strong>Pipeline</strong>
  <span class="count">{jobs.length}</span>
  <NewJobButton />
</div>
<div class="column-body">
  {#each sections as section (section.key)}
    <div class="section-divider" style="--section-color: {section.color};">
      <span class="section-label">{section.label}</span>
    </div>
    {#each section.jobs as job (job.job_id)}
      <a
        href="#/jobs/{job.job_id}"
        class="card-link"
        class:card-link--approved={section.key === 'awaiting-prep'}
      >
        <JobCard {job} docs={buildDocs(job)} />
      </a>
    {/each}
  {/each}
  {#if jobs.length === 0}
    <p class="empty">No jobs in pipeline</p>
  {/if}
</div>

<style>
  .column-header { position: relative; padding: 14px 16px 10px; display: flex; align-items: center; justify-content: center; gap: 10px; border-bottom: 3px solid #60a5fa; flex-shrink: 0; }
  .count { font-size: 12px; color: #999; }
  .column-body {
    flex: 1; overflow-y: auto; padding: 12px; background: #dde6f7;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 10px;
    align-content: start;
  }
  .card-link { text-decoration: none; color: inherit; display: block; }
  .card-link--approved { filter: drop-shadow(0 0 3px rgba(202, 138, 4, 0.25)); }
  .section-divider {
    grid-column: 1 / -1;
    display: flex; align-items: center; gap: 8px; margin: 8px 0 6px;
  }
  .section-divider::before,
  .section-divider::after { content: ''; flex: 1; height: 1px; background: var(--section-color); opacity: 0.4; }
  .section-label { font-size: 10px; font-weight: 700; color: var(--section-color); letter-spacing: 0.5px; text-transform: uppercase; white-space: nowrap; }
  .empty { font-size: 13px; color: #999; text-align: center; padding: 20px 0; }
</style>
