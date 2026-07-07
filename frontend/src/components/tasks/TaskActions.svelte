<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import { notifyBlepChanged } from '../../stores/blepActivity.js';
  import { settlePriorSession } from '../../lib/priorSession.js';
  import ActualQtyModal from './ActualQtyModal.svelte';
  import BlepEditModal from './BlepEditModal.svelte';

  let {
    task,
    user,
    canManage = false,
    activeBlepOnThisTask = null,
    // TaskDetailPage relocates Start Work to its toolbar (via the
    // exported startWork()) and relies on the yellow band as the only
    // stop/cancel surface while a session runs — avoids two Cancel
    // buttons in one row (blep-cancel beside task-cancel). Direction
    // to be refined with the task-page design pass.
    hideStartStop = false,
    onChanged = () => {},
    onConflict = () => {},
  } = $props();

  let busy = $state(false);
  let settleModal = $state(null);  // {unitLabel, currentQty} — settle-up at Complete
  let sessionModal = $state(null); // {unitLabel, currentQty} — prompt after own Stop
  let priorModal = $state(null);   // prior_session_qty conflict dict — settle before Start
  let modalError = $state('');     // server error shown inside the open modal
  let blepModal = $state(false);   // true while the historical-time prompt is open

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
    try {
      const resp = await api.post(url, body);
      if (resp && resp.conflict) {
        onConflict(resp);
      } else {
        await notifyBlepChanged();
        onChanged();
      }
    } catch (e) {
      // Plain action buttons (no form): the global overlay is the venue.
      showError(errorMessage(e, 'Action failed.'));
    } finally {
      busy = false;
    }
  }

  // Complete has its own flow. An ENTERED_QTY task ALWAYS answers the bare
  // complete with `needs_actual_qty` (+ the running total) — the settle-up
  // prompt: "entered so far X, any more to add?". The re-post carries the
  // increment as add_qty. An elapsed-time task with no logged time answers
  // `needs_time_logged` instead.
  async function completeTask(addQty = null) {
    busy = true;
    try {
      const body = addQty != null ? { add_qty: addQty } : {};
      const resp = await api.post(`/api/tasks/${task.task_id}/complete/`, body);
      if (resp && resp.needs_actual_qty) {
        settleModal = {
          unitLabel: resp.unit_label || '',
          currentQty: resp.current_qty ?? null,
        };
        return;
      }
      if (resp && resp.needs_time_logged) {
        blepModal = true;
        return;
      }
      settleModal = null;
      await notifyBlepChanged();
      onChanged();
    } catch (e) {
      showError(errorMessage(e, 'Action failed.'));
    } finally {
      busy = false;
    }
  }

  function submitSettle(addQty) {
    settleModal = null;
    completeTask(addQty);
  }

  function onTimeLogged() {
    blepModal = false;
    completeTask();
  }

  // Stop always succeeds first (the blep closes regardless); the session
  // prompt is after the fact and skippable. prompt_actual_qty only comes
  // back for an own stop on an ENTERED_QTY task.
  async function stopWork() {
    busy = true;
    try {
      const resp = await api.post(`/api/tasks/${task.task_id}/stop-work/`, {});
      await notifyBlepChanged();
      onChanged();
      if (resp && resp.prompt_actual_qty) {
        modalError = '';
        sessionModal = {
          unitLabel: resp.unit_label || '',
          currentQty: resp.current_qty ?? null,
        };
      }
    } catch (e) {
      showError(errorMessage(e, 'Action failed.'));
    } finally {
      busy = false;
    }
  }

  // Session modal submit (stop flow). Checkbox checked = one atomic
  // add-and-complete call; on failure the modal stays open so the typed
  // value isn't lost (uncheck and Add, or cancel).
  async function submitSession(qty, { completesTask }) {
    modalError = '';
    busy = true;
    try {
      if (completesTask) {
        await api.post(`/api/tasks/${task.task_id}/complete/`, { add_qty: qty ?? 0 });
      } else if (qty != null) {
        await api.post(`/api/tasks/${task.task_id}/actual-qty/add/`, { actual_qty: qty });
      }
      sessionModal = null;
      onChanged();
    } catch (e) {
      modalError = errorMessage(e, 'Could not save the quantity.');
    } finally {
      busy = false;
    }
  }

  // Start settles first: without the flag, an open session on another
  // ENTERED_QTY task comes back as a prior_session_qty conflict. Resolve
  // it (add / complete / skip), then re-post with prior_qty_handled.
  // Cancelling the prompt aborts the start — the old session keeps running.
  export async function startWork() {
    busy = true;
    try {
      const resp = await api.post(`/api/tasks/${task.task_id}/start-work/`, {});
      if (resp && resp.conflict === 'prior_session_qty') {
        modalError = '';
        priorModal = resp;
      } else if (resp && resp.conflict) {
        onConflict(resp);
      } else {
        await notifyBlepChanged();
        onChanged();
      }
    } catch (e) {
      showError(errorMessage(e, 'Action failed.'));
    } finally {
      busy = false;
    }
  }

  async function submitPrior(qty, { completesTask }) {
    modalError = '';
    busy = true;
    try {
      await settlePriorSession(priorModal, qty, completesTask);
      const resp = await api.post(
        `/api/tasks/${task.task_id}/start-work/`, { prior_qty_handled: true });
      priorModal = null;
      if (resp && resp.conflict) {
        onConflict(resp);
      } else {
        await notifyBlepChanged();
        onChanged();
      }
    } catch (e) {
      modalError = errorMessage(e, 'Could not settle the previous session.');
    } finally {
      busy = false;
    }
  }

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
  {#if show.startWork && !hideStartStop}<button type="button" onclick={startWork} disabled={busy}>Start Work</button>{/if}
  {#if show.stopWork && !hideStartStop}
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

{#if settleModal}
  <ActualQtyModal
    mode="complete"
    unitLabel={settleModal.unitLabel}
    currentQty={settleModal.currentQty}
    onSubmit={submitSettle}
    onClose={() => { settleModal = null; }}
  />
{/if}

{#if sessionModal}
  <ActualQtyModal
    mode="session"
    unitLabel={sessionModal.unitLabel}
    currentQty={sessionModal.currentQty}
    allowComplete={true}
    serverError={modalError}
    onSubmit={submitSession}
    onClose={() => { sessionModal = null; modalError = ''; }}
  />
{/if}

{#if priorModal}
  <ActualQtyModal
    mode="session"
    unitLabel={priorModal.unit_label || ''}
    currentQty={priorModal.current_qty ?? null}
    priorTaskName={priorModal.prior_task?.name || ''}
    allowComplete={true}
    serverError={modalError}
    onSubmit={submitPrior}
    onClose={() => { priorModal = null; modalError = ''; }}
  />
{/if}

{#if blepModal}
  <BlepEditModal
    open={true}
    mode="create"
    taskId={task.task_id}
    currentUser={user}
    onSaved={onTimeLogged}
    onClose={() => { blepModal = false; }}
  />
{/if}

<style>
  .actions { display: flex; gap: 8px; margin: 8px 0; flex-wrap: wrap; }
  .cancel-work { color: #a8071a; }
</style>
