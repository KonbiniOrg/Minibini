<script>
  import { onMount, onDestroy } from 'svelte';
  let { shifts = [], showWorker = false, actions = undefined } = $props();
  let now = $state(Date.now());
  const DOW = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

  function fmt(iso) {
    if (!iso) return '—';
    const d = new Date(iso); let h = d.getHours(); const ap = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    return `${DOW[d.getDay()]} ${h}:${String(d.getMinutes()).padStart(2,'0')} ${ap}`;
  }
  function dur(s) {
    const end = s.end_time ? new Date(s.end_time).getTime() : now;
    const mins = Math.max(0, Math.round((end - new Date(s.start_time).getTime())/60000));
    const h = Math.floor(mins/60), m = mins % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }
  let tick;
  onMount(() => { tick = setInterval(() => now = Date.now(), 30000); });
  onDestroy(() => tick && clearInterval(tick));
</script>

<table class="data-table">
  <thead><tr>
    {#if showWorker}<th>Worker</th>{/if}
    <th>Clock In</th><th>Clock Out</th><th>Duration</th>{#if actions}<th></th>{/if}
  </tr></thead>
  <tbody>
    {#each shifts as s (s.shift_id)}
      <tr>
        {#if showWorker}<td>{s.user_name || '—'}</td>{/if}
        <td>{fmt(s.start_time)}</td>
        <td>{#if s.end_time}{fmt(s.end_time)}{:else}<span class="active-tag">open</span>{/if}</td>
        <td>{dur(s)}</td>
        {#if actions}<td>{@render actions(s)}</td>{/if}
      </tr>
    {/each}
  </tbody>
</table>

<style>.active-tag { color: #16a34a; font-weight: 600; }</style>
