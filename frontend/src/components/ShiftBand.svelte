<script>
  import { onMount } from 'svelte';
  import { api, errorMessage } from '../lib/api.js';
  import { currentShift, refreshCurrentShift, notifyShiftChanged } from '../stores/shift.js';
  import { notifyBlepChanged, blepActivityVersion } from '../stores/blepActivity.js';
  import { isPriorSessionConflict, settlePriorSession } from '../lib/priorSession.js';
  import ActualQtyModal from './tasks/ActualQtyModal.svelte';

  let busy = $state(false);
  let error = $state('');
  let now = $state(Date.now());

  onMount(() => {
    refreshCurrentShift();
    const t = setInterval(() => { now = Date.now(); }, 30000);
    return () => clearInterval(t);
  });

  // Starting a task auto-clocks the worker in server-side, so any blep
  // mutation may have opened a shift — re-read on every bump.
  let lastBlepVersion = $state(0);
  $effect(() => {
    const v = $blepActivityVersion;
    if (v !== lastBlepVersion) {
      lastBlepVersion = v;
      refreshCurrentShift();
    }
  });

  function elapsed(iso) {
    const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
    const h = Math.floor(mins / 60), m = mins % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  async function clockIn() {
    busy = true; error = '';
    try { await api.post('/api/shifts/clock-in/', {}); await notifyShiftChanged(); }
    catch (e) { error = e.message || 'Could not clock in.'; } finally { busy = false; }
  }
  // Settle-first: an open session on an entered-qty task comes back as a
  // prior_session_qty conflict — prompt for the count, then re-post with
  // the flag. Cancelling the prompt aborts the clock-out.
  let priorModal = $state(null); // the conflict dict
  let modalError = $state('');

  async function clockOut(priorQtyHandled = false) {
    busy = true; error = '';
    try {
      const body = priorQtyHandled ? { prior_qty_handled: true } : {};
      const resp = await api.post('/api/shifts/clock-out/', body);
      if (isPriorSessionConflict(resp)) {
        modalError = '';
        priorModal = resp;
        return;
      }
      // Clock-out closes any open blep server-side, so refresh the blep band too,
      // not just the shift state.
      await notifyShiftChanged();
      await notifyBlepChanged();
    }
    catch (e) { error = e.message || 'Could not clock out.'; } finally { busy = false; }
  }

  async function submitPrior(qty, { completesTask }) {
    modalError = '';
    try {
      await settlePriorSession(priorModal, qty, completesTask);
    } catch (e) {
      modalError = errorMessage(e, 'Could not settle the open session.');
      return;
    }
    priorModal = null;
    await clockOut(true);
  }
</script>

<div class="shift-band">
  {#if $currentShift}
    <span class="status on">On the clock — {elapsed($currentShift.start_time)}</span>
    <button type="button" onclick={() => clockOut()} disabled={busy}>Clock Out</button>
  {:else}
    <span class="status off">Not clocked in</span>
    <button type="button" onclick={clockIn} disabled={busy}>Clock In</button>
  {/if}
  {#if error}<span class="error">{error}</span>{/if}
</div>

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

<style>
  /* Thin permanent strip; the 120px left padding keeps text clear of the
     fixed hamburger expander in the top-left corner. */
  .shift-band {
    display: flex;
    align-items: center;
    gap: 1em;
    padding: 4px 12px 4px 120px;
    background: #f0f7ff;
    border-bottom: 2px solid #2563eb;
  }
  .status.on { color: #16a34a; font-weight: 700; }
  .status.off { color: #555; }
  .error { color: #b91c1c; }
</style>
