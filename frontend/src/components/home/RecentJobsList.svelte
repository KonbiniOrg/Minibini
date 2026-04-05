<script>
  import { link } from 'svelte-spa-router';

  let { jobs = [] } = $props();

  function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleString();
  }
</script>

<section>
  <h3>Recent Jobs</h3>
  {#if jobs.length === 0}
    <p>No recent jobs.</p>
  {:else}
    <ul>
      {#each jobs as job (job.id)}
        <li>
          <a href={`/jobs/${job.id}`} use:link>
            {job.job_number} {job.name}
          </a>
          <small>— last worked {formatDate(job.last_worked_at)}</small>
        </li>
      {/each}
    </ul>
  {/if}
</section>
