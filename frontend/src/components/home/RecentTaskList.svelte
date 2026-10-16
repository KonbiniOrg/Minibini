<script>
  import { link } from 'svelte-spa-router';
  import { formatSessionDateTime } from '../../lib/format.js';
  import DataTable from '../DataTable.svelte';

  // Home Work tab's "Recent" list: tasks the user recently completed, most
  // recently-worked first. Read-only — these are done, so no Start/reorder.
  let { tasks = [], sinceDays = 7 } = $props();
</script>

<section>
  <h3>Recent</h3>
  <p class="window-note">(completed in the past {sinceDays} days)</p>
  <DataTable
    rows={tasks}
    key={(task) => task.id}
    emptyText="No recently completed tasks."
    columns={[
      { id: 'task',   label: 'Task',        cell: taskCell },
      { id: 'job',    label: 'Job',         cell: jobCell },
      { id: 'worked', label: 'Last worked', cell: workedCell },
    ]}
  />
</section>


{#snippet taskCell(task)}
  {#if task.job}
    <a href={`/jobs/${task.job.id}/tasks/${task.id}`} use:link>{task.name}</a>
  {:else}
    {task.name}
  {/if}
{/snippet}
{#snippet jobCell(task)}
  {#if task.job}
    <a href={`/jobs/${task.job.id}`} use:link>{task.job.job_number} {task.job.name}</a>
  {/if}
{/snippet}
{#snippet workedCell(task)}{task.last_worked_at ? formatSessionDateTime(task.last_worked_at) : '—'}{/snippet}

<style>
  .window-note { color: #6b7280; font-size: 0.85em; margin: -0.5em 0 0.5em; }
</style>
