<script>
  import { link } from 'svelte-spa-router';
  import { currentBlep } from '../stores/currentBlep.js';
  import { notifyBlepChanged } from '../stores/blepActivity.js';
  import { api, errorMessage } from '../lib/api.js';
  import { onMount, onDestroy } from 'svelte';
  import ActualQtyModal from './tasks/ActualQtyModal.svelte';

  let now = $state(Date.now());
  let working = $state(false);
  let error = $state('');

  let tick;
  onMount(() => {
    tick = setInterval(() => { now = Date.now(); }, 1000);
  });
  onDestroy(() => { if (tick) clearInterval(tick); });

  // The timer contract: count SECONDS from zero at the moment the user
  // clicked Start — never from the server's minute-floored start_time,
  // which would make a fresh timer read ~47s. Once the displayed count
  // reaches 5:00, switch to minutes-only realigned to the floored
  // start_time (the short fifth minute is invisible). The click-zero
  // lives in sessionStorage so a same-tab reload keeps counting; a blep
  // first seen already >75s old has no knowable zero and skips the
  // seconds phase entirely.
  const SECONDS_PHASE_MS = 5 * 60 * 1000;
  const FRESHLY_STARTED_MS = 75 * 1000;

  let clickZero = $state(null);

  $effect(() => {
    const cb = $currentBlep;
    if (!cb?.id) {
      clickZero = null;
      return;
    }
    const key = `blep_zero_${cb.id}`;
    const stored = Number(sessionStorage.getItem(key));
    if (stored) {
      clickZero = stored;
      return;
    }
    if (Date.now() - new Date(cb.start_time).getTime() < FRESHLY_STARTED_MS) {
      // Just started here — this instant is the timer's zero. Old bleps'
      // keys are garbage; sweep them while we're writing.
      for (const k of Object.keys(sessionStorage)) {
        if (k.startsWith('blep_zero_')) sessionStorage.removeItem(k);
      }
      clickZero = Date.now();
      sessionStorage.setItem(key, String(clickZero));
    } else {
      clickZero = null;
    }
  });

  function elapsedText(startIso) {
    if (clickZero && now - clickZero < SECONDS_PHASE_MS) {
      const seconds = Math.max(0, Math.floor((now - clickZero) / 1000));
      return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    }
    const minutes = Math.max(0, Math.floor((now - new Date(startIso).getTime()) / 60000));
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }

  // Below the configured minimum, the only way to end the session is to cancel
  // it (delete + undo). Stop becomes Cancel until the timer crosses the line.
  const underMinimum = $derived.by(() => {
    const cb = $currentBlep;
    if (!cb || !cb.start_time) return false;
    const minMinutes = cb.blep_minimum_minutes ?? 1;
    const wholeMinutes = Math.floor((now - new Date(cb.start_time).getTime()) / 60000);
    return wholeMinutes < minMinutes;
  });

  // Settle-first stop: the conflict response means NOTHING happened —
  // the blep is still running and the band stays up (honest UI) while
  // the modal asks for the session count. The task id is still captured
  // so the settle posts target the right task even if the store shifts.
  let sessionModal = $state(null); // {taskId, unitLabel, currentQty}
  let modalError = $state('');

  async function act(urlSuffix) {
    const cb = $currentBlep;
    if (!cb || !cb.task) return;
    const taskId = cb.task.id;
    working = true;
    error = '';
    try {
      const resp = await api.post(`/api/tasks/${taskId}/${urlSuffix}/`, {});
      if (resp && resp.conflict === 'prior_session_qty') {
        modalError = '';
        sessionModal = {
          taskId,
          unitLabel: resp.unit_label || '',
          currentQty: resp.current_qty ?? null,
        };
        return;
      }
      await notifyBlepChanged();
    } catch (e) {
      error = e.message || 'Could not update work.';
    } finally {
      working = false;
    }
  }

  const handleStop = () => act('stop-work');
  const handleCancel = () => act('cancel-work');

  // One call per outcome, atomic server-side: checkbox = complete with
  // add_qty (closes the blep too); otherwise a flagged stop carrying the
  // optional count. On failure the modal stays open, the session still
  // running — nothing half-done.
  async function submitSession(qty, { completesTask }) {
    modalError = '';
    try {
      if (completesTask) {
        await api.post(`/api/tasks/${sessionModal.taskId}/complete/`, { add_qty: qty ?? 0 });
      } else {
        const body = { prior_qty_handled: true };
        if (qty != null) body.add_qty = qty;
        await api.post(`/api/tasks/${sessionModal.taskId}/stop-work/`, body);
      }
      sessionModal = null;
      await notifyBlepChanged();
    } catch (e) {
      modalError = errorMessage(e, 'Could not save the quantity.');
    }
  }
</script>

{#if $currentBlep}
  <div class="blep-band">
    <div class="blep-info">
      <strong>Working on:</strong> {$currentBlep.task.name}
      {#if $currentBlep.job}
        — <a href={`/jobs/${$currentBlep.job.id}`} use:link>
          {$currentBlep.job.job_number} {$currentBlep.job.name}
        </a>
      {/if}
      <span class="elapsed">({elapsedText($currentBlep.start_time)})</span>
    </div>
    {#if underMinimum}
      <button type="button" class="cancel" onclick={handleCancel} disabled={working}>
        {working ? 'Cancelling…' : 'Cancel'}
      </button>
    {:else}
      <button type="button" onclick={handleStop} disabled={working}>
        {working ? 'Stopping…' : 'Stop'}
      </button>
    {/if}
    {#if error}
      <p class="error">{error}</p>
    {/if}
  </div>
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

<style>
  /* Sticky positioning lives on App.svelte's .app-bands wrapper (shared
     with the shift strip above). The 120px left padding keeps text clear
     of the fixed hamburger expander in the top-left corner. */
  .blep-band {
    background: #fffbe6;
    border-bottom: 2px solid #d4b106;
    padding: 8px 12px 8px 120px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
  .blep-info {
    flex: 1;
    min-width: 0;
  }
  .elapsed {
    color: #666;
    margin-left: 4px;
  }
  .cancel {
    color: #a8071a;
  }
  .error {
    color: #a8071a;
    margin: 0;
    flex-basis: 100%;
  }
</style>
