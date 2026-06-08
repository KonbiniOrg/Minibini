<script>
  import JobCard from './JobCard.svelte';
  let { jobs = [] } = $props();

  let preJobs = $derived(jobs.filter(j => j.status !== 'approved'));
  let approvedJobs = $derived(jobs.filter(j => j.status === 'approved'));

  const ESTIMATE_LABELS = {
    draft: 'Draft',
    open: 'Sent',
    accepted: 'Accepted',
    rejected: 'Rejected',
    expired: 'Expired',
  };

  function buildDocs(job) {
    const docs = [];
    if (job.worksheets) {
      for (const ws of job.worksheets) {
        docs.push({
          type: 'Worksheet',
          status: 'draft',
          statusLabel: 'Draft',
          created_date: ws.created_date,
          total: null,
        });
      }
    }
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
</div>
<div class="column-body">
  {#each preJobs as job (job.job_id)}
    <a href="#/jobs/{job.job_id}" class="card-link">
      <JobCard {job} docs={buildDocs(job)} />
    </a>
  {/each}
  {#if approvedJobs.length > 0}
    <div class="section-divider">
      <span class="section-label">Awaiting Prep</span>
    </div>
    {#each approvedJobs as job (job.job_id)}
      <a href="#/jobs/{job.job_id}" class="card-link card-link--approved">
        <JobCard {job} docs={buildDocs(job)} />
      </a>
    {/each}
  {/if}
  {#if jobs.length === 0}
    <p class="empty">No jobs in pipeline</p>
  {/if}
</div>

<style>
  .column-header { padding: 14px 16px 10px; display: flex; align-items: center; justify-content: center; gap: 10px; border-bottom: 3px solid #60a5fa; flex-shrink: 0; }
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
  .section-divider::after { content: ''; flex: 1; height: 1px; background: #ca8a04; opacity: 0.4; }
  .section-label { font-size: 10px; font-weight: 700; color: #854d0e; letter-spacing: 0.5px; text-transform: uppercase; white-space: nowrap; }
  .empty { font-size: 13px; color: #999; text-align: center; padding: 20px 0; }
</style>
