<script>
  import { link } from 'svelte-spa-router';
  import { currentBlep, stopCurrentBlep } from '../stores/currentBlep.js';
  import { onMount, onDestroy } from 'svelte';

  let now = $state(Date.now());
  let stopping = $state(false);
  let error = $state('');

  let tick;
  onMount(() => {
    tick = setInterval(() => { now = Date.now(); }, 1000);
  });
  onDestroy(() => { if (tick) clearInterval(tick); });

  function elapsedText(startIso) {
    if (!startIso) return '';
    const start = new Date(startIso).getTime();
    const seconds = Math.max(0, Math.floor((now - start) / 1000));
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `${h}h ${m}m ${s}s`;
    return `${m}m ${s}s`;
  }

  async function handleStop() {
    stopping = true;
    error = '';
    try {
      await stopCurrentBlep();
    } catch (e) {
      error = e.message || 'Could not stop work.';
    } finally {
      stopping = false;
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
    <button type="button" onclick={handleStop} disabled={stopping}>
      {stopping ? 'Stopping...' : 'Stop'}
    </button>
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
  .error {
    color: #a8071a;
    margin: 0;
    flex-basis: 100%;
  }
</style>
