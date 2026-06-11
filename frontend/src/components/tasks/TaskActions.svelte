<script>
  import { api } from '../../lib/api.js';
  import { notifyBlepChanged } from '../../stores/blepActivity.js';
  import ActualQtyModal from './ActualQtyModal.svelte';
  import BlepEditModal from './BlepEditModal.svelte';

  let {
    task,
    user,
    userPermissions = [],
    canManage = false,
    activeBlepOnThisTask = null,
    onChanged = () => {},
    onConflict = () => {},
  } = $props();

  let busy = $state(false);
  let error = $state('');
  let qtyModal = $state(null);   // {unitLabel} while the entered-qty prompt is open
  let blepModal = $state(false); // true while the historical-time prompt is open

  // While the user's own active session on this task is under the configured
  // minimum, Stop becomes Cancel (delete + undo). Tick once a second so the
  // label flips live as the timer crosses the threshold.
  let nowMs = $state(Date.now());
  $effect(() => {
    if (activeBlepOnThisTask) {
      const t = setInterval(() => { nowMs = Date.now(); }, 1000);
      return () => clearInterval(t);
    }
  });
  const underMinimum = $derived.by(() => {
    const ab = activeBlepOnThisTask;
    if (!ab || !ab.start_time) return false;
    const minMinutes = ab.blep_minimum_minutes ?? task?.blep_minimum_minutes ?? 1;
    const wholeMinutes = Math.floor((nowMs - new Date(ab.start_time).getTime()) / 60000);
    return wholeMinutes < minMinutes;
  });

  // Visibility per status (see design doc § Action visibility)
  const show = $derived.by(() => {
    const status = task?.status;
    const isActiveHere = activeBlepOnThisTask !== null;
    const base = {
      startWork: false, stopWork: false, complete: false,
      block: false, unblock: false, cancel: false,
    };
    if (status === 'pending' || status === 'in_progress') {
      base.startWork = !isActiveHere;
      base.stopWork = isActiveHere;
      base.complete = true;
      base.block = true;
      base.cancel = true;
    } else if (status === 'blocked') {
      base.unblock = true;
      base.cancel = true;
    }
    return base;
  });

  async function call(url, body = {}) {
    busy = true;
    error = '';
    try {
      const resp = await api.post(url, body);
      if (resp && resp.conflict) {
        onConflict(resp);
      } else {
        await notifyBlepChanged();
        onChanged();
      }
    } catch (e) {
      error = e.message || 'Action failed.';
    } finally {
      busy = false;
    }
  }

  // Complete has its own flow. A task whose rate scheme needs an actual
  // quantity that isn't on record makes the server answer with a prompt
  // signal: `needs_actual_qty` (worker-entered qty) or `needs_time_logged`
  // (elapsed-time task with no logged time).
  async function completeTask(actualQty = null) {
    busy = true;
    error = '';
    try {
      const body = actualQty != null ? { actual_qty: actualQty } : {};
      const resp = await api.post(`/api/tasks/${task.task_id}/complete/`, body);
      if (resp && resp.needs_actual_qty) {
        qtyModal = { unitLabel: resp.unit_label || '' };
        return;
      }
      if (resp && resp.needs_time_logged) {
        blepModal = true;
        return;
      }
      await notifyBlepChanged();
      onChanged();
    } catch (e) {
      error = e.message || 'Action failed.';
    } finally {
      busy = false;
    }
  }

  function submitQty(qty) {
    qtyModal = null;
    completeTask(qty);
  }

  function onTimeLogged() {
    blepModal = false;
    completeTask();
  }

  const startWork = () => call(`/api/tasks/${task.task_id}/start-work/`);
  const stopWork = () => call(`/api/tasks/${task.task_id}/stop-work/`);
  const cancelWork = () => call(`/api/tasks/${task.task_id}/cancel-work/`);
  const block = () => {
    const reason = prompt('Reason for blocking?');
    if (reason) call(`/api/tasks/${task.task_id}/block/`, { reason });
  };
  const unblock = () => call(`/api/tasks/${task.task_id}/unblock/`);
  const cancel = () => {
    if (confirm('Cancel this task?')) call(`/api/tasks/${task.task_id}/cancel/`);
  };
</script>

<div class="actions">
  {#if show.startWork}<button type="button" onclick={startWork} disabled={busy}>Start Work</button>{/if}
  {#if show.stopWork}
    {#if underMinimum}
      <button type="button" class="cancel-work" onclick={cancelWork} disabled={busy}>Cancel</button>
    {:else}
      <button type="button" onclick={stopWork} disabled={busy}>Stop Work</button>
    {/if}
  {/if}
  {#if show.complete}<button type="button" onclick={() => completeTask()} disabled={busy}>Complete</button>{/if}
  {#if show.block}<button type="button" onclick={block} disabled={busy}>Block</button>{/if}
  {#if show.unblock}<button type="button" onclick={unblock} disabled={busy}>Unblock</button>{/if}
  {#if show.cancel && canManage}<button type="button" onclick={cancel} disabled={busy}>Cancel</button>{/if}
</div>
{#if error}<p class="error">{error}</p>{/if}

{#if qtyModal}
  <ActualQtyModal
    unitLabel={qtyModal.unitLabel}
    onSubmit={submitQty}
    onClose={() => { qtyModal = null; }}
  />
{/if}

{#if blepModal}
  <BlepEditModal
    open={true}
    mode="create"
    taskId={task.task_id}
    currentUser={user}
    userPermissions={userPermissions}
    onSaved={onTimeLogged}
    onClose={() => { blepModal = false; }}
  />
{/if}

<style>
  .actions { display: flex; gap: 8px; margin: 8px 0; flex-wrap: wrap; }
  .cancel-work { color: #a8071a; }
  .error { color: #a8071a; }
</style>
