<script>
  import JobCard from './JobCard.svelte';
  let { jobs = [] } = $props();
</script>

<div class="column-header">
  <strong>Pipeline</strong>
  <span class="count">{jobs.length}</span>
</div>
<div class="column-body">
  {#each jobs as job (job.job_id)}
    <a href="#/jobs/{job.job_id}" class="card-link">
      <JobCard {job} />
    </a>
  {/each}
  {#if jobs.length === 0}
    <p class="empty">No jobs in pipeline</p>
  {/if}
</div>

<style>
  .column-header { padding: 14px 16px 10px; display: flex; align-items: center; justify-content: center; gap: 10px; border-bottom: 3px solid #60a5fa; }
  .count { font-size: 12px; color: #999; }
  .column-body { flex: 1; overflow-y: auto; padding: 12px; background: #f0f5ff; display: flex; flex-direction: column; gap: 10px; }
  .card-link { text-decoration: none; color: inherit; }
  .empty { font-size: 13px; color: #999; text-align: center; padding: 20px 0; }
</style>
