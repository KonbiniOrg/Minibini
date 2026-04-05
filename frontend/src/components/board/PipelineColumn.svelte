<script>
  import JobCard from './JobCard.svelte';
  let { jobs = [] } = $props();

  function buildDocs(job) {
    const docs = [];
    if (job.worksheets) {
      for (const ws of job.worksheets) {
        docs.push({
          type: 'Worksheet',
          status: ws.status,
          statusLabel: ws.status === 'final' ? 'Final' : 'Draft',
          created_date: ws.created_date,
          total: null,
        });
      }
    }
    if (job.estimates) {
      for (const est of job.estimates) {
        docs.push({
          type: 'Estimate',
          status: est.status === 'open' ? 'open' : 'draft',
          statusLabel: est.status === 'open' ? 'Sent' : 'Draft',
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
  {#each jobs as job (job.job_id)}
    <a href="#/jobs/{job.job_id}" class="card-link">
      <JobCard {job} docs={buildDocs(job)} />
    </a>
  {/each}
  {#if jobs.length === 0}
    <p class="empty">No jobs in pipeline</p>
  {/if}
</div>

<style>
  .column-header { padding: 14px 16px 10px; display: flex; align-items: center; justify-content: center; gap: 10px; border-bottom: 3px solid #60a5fa; flex-shrink: 0; }
  .count { font-size: 12px; color: #999; }
  .column-body { flex: 1; overflow-y: auto; padding: 12px; background: #dde6f7; columns: 3; column-gap: 10px; }
  .card-link { text-decoration: none; color: inherit; display: block; break-inside: avoid; margin-bottom: 10px; }
  .empty { font-size: 13px; color: #999; text-align: center; padding: 20px 0; }
</style>
