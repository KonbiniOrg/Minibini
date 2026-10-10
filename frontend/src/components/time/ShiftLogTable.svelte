<script>
  import { onMount, onDestroy } from 'svelte';
  import { formatSessionDateTime as fmt } from '../../lib/format.js';
  import DataTable from '../DataTable.svelte';
  let { shifts = [], showWorker = false, actions = undefined } = $props();
  let now = $state(Date.now());
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

<DataTable
  rows={shifts}
  key={(s) => s.shift_id}
  columns={[
    ...(showWorker ? [{ id: 'worker', label: 'Worker', cell: workerCell }] : []),
    { id: 'in',       label: 'Clock In',  cell: inCell },
    { id: 'out',      label: 'Clock Out', cell: outCell },
    { id: 'duration', label: 'Duration',  cell: durationCell },
    ...(actions ? [{ id: 'actions', label: '', cell: actions }] : []),
  ]}
/>

{#snippet workerCell(s)}{s.user_name || '—'}{/snippet}
{#snippet inCell(s)}{fmt(s.start_time)}{/snippet}
{#snippet outCell(s)}{#if s.end_time}{fmt(s.end_time)}{:else}<span class="active-tag">open</span>{/if}{/snippet}
{#snippet durationCell(s)}{dur(s)}{/snippet}

<style>.active-tag { color: #16a34a; font-weight: 600; }</style>
