<script>
  import { link } from 'svelte-spa-router';
  import { formatSessionDateTime } from '../../lib/format.js';

  // Home Work tab's "Recent" list: tasks the user recently completed, most
  // recently-worked first. Read-only — these are done, so no Start/reorder.
  let { tasks = [], sinceDays = 7 } = $props();
</script>

<section>
  <h3>Recent</h3>
  <p class="window-note">(completed in the past {sinceDays} days)</p>
  {#if tasks.length === 0}
    <p>No recently completed tasks.</p>
  {:else}
    <table class="data-table">
      <thead>
        <tr><th>Task</th><th>Job</th><th>Last worked</th></tr>
      </thead>
      <tbody>
        {#each tasks as task (task.id)}
          <tr>
            <td>
              {#if task.job}
                <a href={`/jobs/${task.job.id}/tasks/${task.id}`} use:link>{task.name}</a>
              {:else}
                {task.name}
              {/if}
            </td>
            <td>
              {#if task.job}
                <a href={`/jobs/${task.job.id}`} use:link>
                  {task.job.job_number} {task.job.name}
                </a>
              {/if}
            </td>
            <td>{task.last_worked_at ? formatSessionDateTime(task.last_worked_at) : '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .window-note { color: #6b7280; font-size: 0.85em; margin: -0.5em 0 0.5em; }
</style>
