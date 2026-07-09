<script>
  import { onMount, onDestroy } from 'svelte';
  import { link } from 'svelte-spa-router';
  import { formatSessionDateTime } from '../../lib/format.js';

  // Shared table of blep (time) sessions, used by the home Time tab (own bleps)
  // and the Activity page (all users). Owns the date/duration formatting and the
  // running-duration tick. `actions` is an optional per-row snippet (e.g. Edit).
  let { bleps = [], showWorker = false, actions = undefined } = $props();

  let now = $state(Date.now());


  // Elapsed at minute granularity. Open bleps run to `now` (ticks below).
  function fmtDuration(blep) {
    if (!blep.start_time) return '—';
    const start = new Date(blep.start_time).getTime();
    const end = blep.end_time ? new Date(blep.end_time).getTime() : now;
    const mins = Math.max(0, Math.round((end - start) / 60000));
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  }

  function truncate(s, n = 20) {
    return s && s.length > n ? s.slice(0, n) + '…' : s;
  }

  let tick;
  onMount(() => { tick = setInterval(() => { now = Date.now(); }, 30000); });
  onDestroy(() => { if (tick) clearInterval(tick); });
</script>

<table class="data-table">
  <thead>
    <tr>
      {#if showWorker}<th>Worker</th>{/if}
      <th>Task</th><th>Job</th><th>Start</th><th>End</th><th>Duration</th>
      {#if actions}<th></th>{/if}
    </tr>
  </thead>
  <tbody>
    {#each bleps as blep (blep.blep_id)}
      <tr>
        {#if showWorker}<td>{blep.user_name || '—'}</td>{/if}
        <td>
          {#if blep.job_id}
            <a href={`/jobs/${blep.job_id}/tasks/${blep.task}`} use:link>{blep.task_name}</a>
          {:else}
            {blep.task_name}
          {/if}
        </td>
        <td>
          {#if blep.job_id}
            <a href={`/jobs/${blep.job_id}`} use:link>{blep.job_number} {truncate(blep.job_name)}</a>
          {/if}
        </td>
        <td>{formatSessionDateTime(blep.start_time)}</td>
        <td>{#if blep.end_time}{formatSessionDateTime(blep.end_time)}{:else}<span class="active-tag">active</span>{/if}</td>
        <td>{fmtDuration(blep)}</td>
        {#if actions}<td>{@render actions(blep)}</td>{/if}
      </tr>
    {/each}
  </tbody>
</table>

<style>
  .active-tag { color: #16a34a; font-weight: 600; }
</style>
