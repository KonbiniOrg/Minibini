<script>
  import { link } from 'svelte-spa-router';
  import { currentBlep } from '../stores/currentBlep.js';
  import { notifyBlepChanged } from '../stores/blepActivity.js';
  import { api } from '../lib/api.js';
  import { onMount, onDestroy } from 'svelte';

  let now = $state(Date.now());
  let working = $state(false);
  let error = $state('');

  let tick;
  onMount(() => {
    tick = setInterval(() => { now = Date.now(); }, 1000);
  });
  onDestroy(() => { if (tick) clearInterval(tick); });

  function elapsedSeconds(startIso) {
    if (!startIso) return 0;
    return Math.max(0, Math.floor((now - new Date(startIso).getTime()) / 1000));
  }

  function elapsedText(startIso) {
    const seconds = elapsedSeconds(startIso);
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `${h}h ${m}m ${s}s`;
    return `${m}m ${s}s`;
  }

  // Below the configured minimum, the only way to end the session is to cancel
  // it (delete + undo). Stop becomes Cancel until the timer crosses the line.
  const underMinimum = $derived.by(() => {
    const cb = $currentBlep;
    if (!cb) return false;
    const threshold = cb.blep_minimum_seconds ?? 60;
    return elapsedSeconds(cb.start_time) < threshold;
  });

  async function act(urlSuffix) {
    const cb = $currentBlep;
    if (!cb || !cb.task) return;
    working = true;
    error = '';
    try {
      await api.post(`/api/tasks/${cb.task.id}/${urlSuffix}/`, {});
      await notifyBlepChanged();
    } catch (e) {
      error = e.message || 'Could not update work.';
    } finally {
      working = false;
    }
  }

  const handleStop = () => act('stop-work');
  const handleCancel = () => act('cancel-work');
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

<style>
  .blep-band {
    position: sticky;
    top: 0;
    z-index: 100;
    background: #fffbe6;
    border-bottom: 2px solid #d4b106;
    padding: 8px 12px;
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
