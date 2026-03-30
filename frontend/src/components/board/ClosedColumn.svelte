<script>
  import JobCard from './JobCard.svelte';
  let { jobs = [] } = $props();
</script>

<div class="column-header">
  <span class="col-indicator"></span>
  <strong>Closed</strong>
  <span class="count">{jobs.length}</span>
</div>
<div class="column-body">
  {#each jobs as job (job.job_id)}
    <a href="#/jobs/{job.job_id}" class="card-link">
      <JobCard {job} />
    </a>
  {/each}
  {#if jobs.length === 0}
    <p class="empty">No recently closed jobs</p>
  {/if}
</div>

<style>
  .column-header { padding: 14px 16px 10px; display: flex; align-items: center; gap: 10px; border-bottom: 3px solid #9ca3af; }
  .col-indicator { width: 4px; height: 24px; border-radius: 2px; background: #9ca3af; }
  .count { font-size: 12px; color: #999; margin-left: auto; }
  .column-body { flex: 1; overflow-y: auto; padding: 12px; background: #f5f5f6; display: flex; flex-direction: column; gap: 10px; }
  .card-link { text-decoration: none; color: inherit; }
  .empty { font-size: 13px; color: #999; text-align: center; padding: 20px 0; }
</style>
