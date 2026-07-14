<script>
  import { link } from 'svelte-spa-router';
  import { formatSessionDateTime } from '../../lib/format.js';

  let { jobs = [], sinceDays = 7 } = $props();
</script>

<section>
  <h3>Recent Jobs</h3>
  <p class="window-note">(past {sinceDays} days)</p>
  {#if jobs.length === 0}
    <p>No recent jobs.</p>
  {:else}
    <table class="data-table">
      <thead>
        <tr><th>Job</th><th>Name</th><th>Last worked</th></tr>
      </thead>
      <tbody>
        {#each jobs as job (job.id)}
          <tr>
            <td><a href={`/jobs/${job.id}`} use:link>{job.job_number}</a></td>
            <td>{job.name}</td>
            <td>{job.last_worked_at ? formatSessionDateTime(job.last_worked_at) : '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .window-note { color: #6b7280; font-size: 0.85em; margin: -0.5em 0 0.5em; }
</style>
