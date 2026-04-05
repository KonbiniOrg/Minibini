<script>
  import UnpaidCard from './UnpaidCard.svelte';
  let { jobs = [] } = $props();
</script>

<div class="column-header">
  <strong>Unpaid</strong>
  <span class="count">{jobs.length}</span>
</div>
<div class="column-body">
  {#each jobs as job (job.job_id)}
    <a href="#/jobs/{job.job_id}" class="card-link">
      <UnpaidCard {job} />
    </a>
  {/each}
  {#if jobs.length === 0}
    <p class="empty">No unpaid jobs</p>
  {/if}
</div>

<style>
  .column-header { padding: 14px 16px 10px; display: flex; align-items: center; justify-content: center; gap: 10px; border-bottom: 3px solid #f59e0b; flex-shrink: 0; }
  .count { font-size: 12px; color: #999; }
  .column-body { flex: 1; overflow-y: auto; padding: 12px; background: #f5eddb; columns: 3; column-gap: 10px; }
  .card-link { text-decoration: none; color: inherit; display: block; break-inside: avoid; margin-bottom: 10px; }
  .empty { font-size: 13px; color: #999; text-align: center; padding: 20px 0; }
</style>
