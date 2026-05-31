<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';
  import { currentShift, refreshCurrentShift, notifyShiftChanged } from '../../stores/shift.js';

  let busy = $state(false);
  let error = $state('');
  let now = $state(Date.now());

  onMount(() => {
    refreshCurrentShift();
    const t = setInterval(() => { now = Date.now(); }, 30000);
    return () => clearInterval(t);
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
  async function clockOut() {
    busy = true; error = '';
    try { await api.post('/api/shifts/clock-out/', {}); await notifyShiftChanged(); }
    catch (e) { error = e.message || 'Could not clock out.'; } finally { busy = false; }
  }
</script>

<div class="clock-band">
  {#if $currentShift}
    <span class="status on">On the clock — {elapsed($currentShift.start_time)}</span>
    <button type="button" class="big" onclick={clockOut} disabled={busy}>Clock Out</button>
  {:else}
    <span class="status off">Not clocked in</span>
    <button type="button" class="big" onclick={clockIn} disabled={busy}>Clock In</button>
  {/if}
  {#if error}<span class="error">{error}</span>{/if}
</div>

<style>
  .clock-band { display: flex; align-items: center; gap: 1em; padding: 0.75em 1em;
                background: #f0f7ff; border: 2px solid #2563eb; margin-bottom: 1em; }
  .status.on { color: #16a34a; font-weight: 700; }
  .status.off { color: #555; }
  .big { font-size: 1.1em; padding: 0.5em 1.5em; }
  .error { color: #b91c1c; }
</style>
