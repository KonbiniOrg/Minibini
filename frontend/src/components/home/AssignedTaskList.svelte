<script>
  import { link, push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { notifyBlepChanged } from '../../stores/blepActivity.js';
  import TaskActivityIndicator from '../tasks/TaskActivityIndicator.svelte';

  let { tasks = [] } = $props();

  // Local copy so we can reorder optimistically.
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  let items = $state([...tasks]);
  let busy = $state(false);
  let errorMessage = $state('');

  $effect(() => {
    items = [...tasks];
  });

  async function moveUp(index) {
    if (index <= 0 || busy) return;
    const snapshot = [...items];
    const next = [...items];
    [next[index - 1], next[index]] = [next[index], next[index - 1]];
    items = next;
    try {
      busy = true;
      errorMessage = '';
      await api.post('/api/tasks/reorder/', {
        task_ids: items.map((t) => t.id),
      });
    } catch (e) {
      items = snapshot;
      errorMessage = e.message || 'Could not save order.';
    } finally {
      busy = false;
    }
  }

  async function moveDown(index) {
    if (index >= items.length - 1 || busy) return;
    const snapshot = [...items];
    const next = [...items];
    [next[index + 1], next[index]] = [next[index], next[index + 1]];
    items = next;
    try {
      busy = true;
      errorMessage = '';
      await api.post('/api/tasks/reorder/', {
        task_ids: items.map((t) => t.id),
      });
    } catch (e) {
      items = snapshot;
      errorMessage = e.message || 'Could not save order.';
    } finally {
      busy = false;
    }
  }

  async function startWork(task) {
    if (busy) return;
    busy = true;
    errorMessage = '';
    try {
      await api.post(
        `/api/tasks/${task.id}/start-work/`,
        {}
      );
      await notifyBlepChanged();
      push(`/jobs/${task.job.id}/tasks/${task.id}`);
    } catch (e) {
      errorMessage = e.message || 'Could not start work.';
    } finally {
      busy = false;
    }
  }
</script>

<section>
  <h3>My Tasks</h3>
  {#if items.length === 0}
    <p>No assigned tasks.</p>
  {:else}
    <table class="data-table">
      <thead>
        <tr>
          <th>Task</th>
          <th>Job</th>
          <th>Status</th>
          <th>Start</th>
          <th>Reorder</th>
        </tr>
      </thead>
      <tbody>
        {#each items as task, i (task.id)}
          <tr>
            <td>
              {#if task.job}
                <a href={`/jobs/${task.job.id}/tasks/${task.id}`} use:link>
                  {task.name}
                </a>
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
            <td><TaskActivityIndicator {task} /></td>
            <td>
              <button type="button" onclick={() => startWork(task)} disabled={busy}>
                Start Work
              </button>
            </td>
            <td>
              <button type="button" onclick={() => moveUp(i)}
                      disabled={busy || i === 0}>Up</button>
              <button type="button" onclick={() => moveDown(i)}
                      disabled={busy || i === items.length - 1}>Down</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
  {#if errorMessage}
    <p class="error">{errorMessage}</p>
  {/if}
</section>

<style>
  .error { color: #a8071a; }
</style>
