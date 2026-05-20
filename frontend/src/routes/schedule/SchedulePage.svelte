<script>
  import { onMount, onDestroy } from 'svelte';
  import { schedule, loadSchedule, startAutoRefresh, stopAutoRefresh } from '../../stores/schedule.js';
  import ScheduleHeader from '../../components/schedule/ScheduleHeader.svelte';
  import WorkerLane from '../../components/schedule/WorkerLane.svelte';
  import NowLine from '../../components/schedule/NowLine.svelte';
  import JobChipStrip from '../../components/board/JobChipStrip.svelte';

  let containerEl;
  let containerWidth = $state(1200);
  let nowTick = $state(Date.now());
  let resizeObserver = null;
  let tickInterval = null;

  const LANE_LABEL_WIDTH = 90;
  const NONWORKING_WIDTH = 12;

  onMount(() => {
    loadSchedule();
    startAutoRefresh();
    if (containerEl) {
      resizeObserver = new ResizeObserver(entries => {
        for (const e of entries) containerWidth = e.contentRect.width;
      });
      resizeObserver.observe(containerEl);
      containerWidth = containerEl.clientWidth;
    }
    tickInterval = setInterval(() => { nowTick = Date.now(); }, 60_000);
  });

  onDestroy(() => {
    stopAutoRefresh();
    if (resizeObserver) resizeObserver.disconnect();
    if (tickInterval) clearInterval(tickInterval);
  });

  function buildPanelLayout(s) {
    if (!s || !s.days || s.days.length === 0) return null;
    const chartWidth = Math.max(200, containerWidth - LANE_LABEL_WIDTH);
    const nonworking = s.days.filter(d => !d.is_working).length;
    const working = s.days.length - nonworking;
    const workingPanelWidth = Math.max(80,
      (chartWidth - nonworking * NONWORKING_WIDTH) / Math.max(working, 1));
    const [wsH, wsM] = s.day_shape.workday_start.split(':').map(n => +n);
    const [weH, weM] = s.day_shape.workday_end.split(':').map(n => +n);
    const workdayStartMins = wsH * 60 + wsM;
    const workdayEndMins = weH * 60 + weM;
    const dayMinutes = workdayEndMins - workdayStartMins;

    const panels = [];
    let runningX = 0;
    for (const d of s.days) {
      const w = d.is_working ? workingPanelWidth : NONWORKING_WIDTH;
      panels.push({ date: d.date, is_working: d.is_working, x: runningX, width: w });
      runningX += w;
    }

    function dateKey(t) {
      const tt = (t instanceof Date) ? t : new Date(t);
      const y = tt.getFullYear();
      const m = String(tt.getMonth() + 1).padStart(2, '0');
      const dd = String(tt.getDate()).padStart(2, '0');
      return `${y}-${m}-${dd}`;
    }

    function timeToX(dt) {
      const t = (dt instanceof Date) ? dt : new Date(dt);
      const key = dateKey(t);
      const idx = panels.findIndex(p => p.date === key);
      if (idx < 0) {
        if (t < new Date(s.horizon_start)) return 0;
        return chartWidth;
      }
      const p = panels[idx];
      if (!p.is_working) return p.x + p.width / 2;
      const hh = t.getHours();
      const mm = t.getMinutes();
      const minutesIntoDay = (hh * 60 + mm) - workdayStartMins;
      const fraction = Math.max(0, Math.min(1, minutesIntoDay / dayMinutes));
      return p.x + fraction * p.width;
    }

    return { panels, chartWidth, timeToX,
             start: new Date(s.horizon_start), end: new Date(s.horizon_end) };
  }

  let layout = $derived(buildPanelLayout($schedule));

  let nowX = $derived.by(() => {
    if (!$schedule || !layout) return null;
    void nowTick;  // re-derive each tick
    const serverNow = new Date($schedule.now);
    // Drift forward by client clock since server response arrived. If the
    // client clock is behind the server we use the server's now as a floor.
    const liveNow = new Date(Math.max(serverNow.getTime(), Date.now()));
    return layout.timeToX(liveNow);
  });
</script>

<div class="schedule-page" bind:this={containerEl}>
  <h2>Schedule</h2>
  {#if $schedule === null}
    <p>Loading schedule…</p>
  {:else}
    <JobChipStrip jobs={$schedule.jobs} />
    <div class="chart-area">
      <ScheduleHeader days={$schedule.days} laneLabelWidth={LANE_LABEL_WIDTH} {layout} />
      {#if $schedule.workers.length === 0}
        <p class="empty">No assigned work in the visible horizon.</p>
      {:else}
        <div class="chart">
          <div class="lanes">
            {#each $schedule.workers as worker (worker.user.id)}
              <WorkerLane {worker}
                          dayShape={$schedule.day_shape}
                          panelLayout={layout}
                          laneLabelWidth={LANE_LABEL_WIDTH} />
            {/each}
          </div>
          <div class="now-overlay" style="left: {LANE_LABEL_WIDTH}px; width: calc(100% - {LANE_LABEL_WIDTH}px);">
            <NowLine x={nowX} />
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .schedule-page { padding: 12px; }
  .chart-area { margin-top: 8px; }
  .chart { position: relative; }
  .now-overlay { position: absolute; top: 0; bottom: 0; pointer-events: none; }
  .empty { color: #888; padding: 12px; }
</style>
