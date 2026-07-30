<script>
  import { link, push } from 'svelte-spa-router';
  import { api, errorMessage as apiErrorMessage } from '../../lib/api.js';
  import { notifyBlepChanged } from '../../stores/blepActivity.js';
  import { isPriorSessionConflict, settlePriorSession } from '../../lib/priorSession.js';
  import TaskActivityIndicator from '../tasks/TaskActivityIndicator.svelte';
  import ActualQtyModal from '../tasks/ActualQtyModal.svelte';

  // The home Work tab's "Current Tasks": tasks assigned to me plus any task I
  // have an open/recent blep on. Backend orders mine first (worker-queue
  // order), others last. Only my own tasks carry reorder controls — reordering
  // writes my worker_queue, which is meaningless for a task in someone else's
  // queue, so those rows omit the Up/Down buttons.
  let { tasks = [] } = $props();

  // Local copy so we can reorder optimistically.
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  let items = $state([...tasks]);
  let busy = $state(false);
  let errorMessage = $state('');

  $effect(() => {
    items = [...tasks];
  });

  // My own tasks form the contiguous top block; only they reorder.
  let mineCount = $derived(items.filter((t) => t.assigned_to_me).length);

  async function persistOrder(snapshot) {
    try {
      busy = true;
      errorMessage = '';
      await api.post('/api/tasks/reorder/', {
        task_ids: items.filter((t) => t.assigned_to_me).map((t) => t.id),
      });
    } catch (e) {
      items = snapshot;
      errorMessage = e.message || 'Could not save order.';
    } finally {
      busy = false;
    }
  }

  async function moveUp(index) {
    if (index <= 0 || index >= mineCount || busy) return;
    const snapshot = [...items];
    const next = [...items];
    [next[index - 1], next[index]] = [next[index], next[index - 1]];
    items = next;
    await persistOrder(snapshot);
  }

  async function moveDown(index) {
    if (index >= mineCount - 1 || busy) return;
    const snapshot = [...items];
    const next = [...items];
    [next[index + 1], next[index]] = [next[index], next[index + 1]];
    items = next;
    await persistOrder(snapshot);
  }

  // Settle-first: an open session on another entered-qty task comes back
  // as a prior_session_qty conflict — prompt, settle, then re-post with
  // the flag. Cancelling the prompt aborts the start.
  let priorModal = $state(null); // {conflict, task}
  let modalError = $state('');

  async function startWork(task, priorQtyHandled = false) {
    if (busy) return;
    busy = true;
    errorMessage = '';
    try {
      const body = priorQtyHandled ? { prior_qty_handled: true } : {};
      const resp = await api.post(`/api/tasks/${task.id}/start-work/`, body);
      if (isPriorSessionConflict(resp)) {
        modalError = '';
        priorModal = { conflict: resp, task };
        return;
      }
      await notifyBlepChanged();
      push(`/jobs/${task.job.id}/tasks/${task.id}`);
    } catch (e) {
      errorMessage = e.message || 'Could not start work.';
    } finally {
      busy = false;
    }
  }

  async function submitPrior(qty, { completesTask }) {
    modalError = '';
    const { conflict, task } = priorModal;
    try {
      await settlePriorSession(conflict, qty, completesTask);
    } catch (e) {
      modalError = apiErrorMessage(e, 'Could not settle the previous session.');
      return;
    }
    priorModal = null;
    await startWork(task, true);
  }
</script>

<section>
  <h3>Current Tasks</h3>
  {#if items.length === 0}
    <p>No current tasks.</p>
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
              {#if task.assigned_to_me}
                <button type="button" onclick={() => moveUp(i)}
                        disabled={busy || i === 0}>Up</button>
                <button type="button" onclick={() => moveDown(i)}
                        disabled={busy || i === mineCount - 1}>Down</button>
              {/if}
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

{#if priorModal}
  <ActualQtyModal
    mode="session"
    unitLabel={priorModal.conflict.unit_label || ''}
    currentQty={priorModal.conflict.current_qty ?? null}
    priorTaskName={priorModal.conflict.prior_task?.name || ''}
    allowComplete={true}
    serverError={modalError}
    onSubmit={submitPrior}
    onClose={() => { priorModal = null; modalError = ''; }}
  />
{/if}

<style>
  .error { color: #a8071a; }
</style>
