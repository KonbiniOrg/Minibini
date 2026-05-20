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

  // --- Time parsing helpers ---
  // All schedule positioning works in the SERVER's wall-clock, not the
  // browser's local timezone. We parse the date and the hour-of-day out
  // of the ISO strings directly so the layout doesn't depend on whether
  // the server happens to be on UTC, Pacific, or anything else.

  function isoDate(iso) {
    return typeof iso === 'string' ? iso.slice(0, 10) : '';
  }

  function isoMinutesOfDay(iso) {
    if (typeof iso !== 'string') return 0;
    const m = iso.match(/T(\d{2}):(\d{2})/);
    return m ? parseInt(m[1], 10) * 60 + parseInt(m[2], 10) : 0;
  }

  function isoOffsetMinutes(iso) {
    if (typeof iso !== 'string') return 0;
    if (iso.endsWith('Z')) return 0;
    const m = iso.match(/([+-])(\d{2}):?(\d{2})$/);
    if (!m) return 0;
    const sign = m[1] === '-' ? -1 : 1;
    return sign * (parseInt(m[2], 10) * 60 + parseInt(m[3], 10));
  }

  // Render a JS ms-since-epoch moment as an ISO string at the given offset,
  // so timeToX can position it relative to the server's day shape.
  function isoAt(ms, offsetMinutes) {
    const shifted = new Date(ms + offsetMinutes * 60 * 1000);
    const Y = shifted.getUTCFullYear();
    const M = String(shifted.getUTCMonth() + 1).padStart(2, '0');
    const D = String(shifted.getUTCDate()).padStart(2, '0');
    const h = String(shifted.getUTCHours()).padStart(2, '0');
    const m = String(shifted.getUTCMinutes()).padStart(2, '0');
    const sign = offsetMinutes >= 0 ? '+' : '-';
    const abs = Math.abs(offsetMinutes);
    const oh = String(Math.floor(abs / 60)).padStart(2, '0');
    const om = String(abs % 60).padStart(2, '0');
    return `${Y}-${M}-${D}T${h}:${m}:00${sign}${oh}:${om}`;
  }

  function buildPanelLayout(s) {
    if (!s || !s.days || s.days.length === 0) return null;
    const chartWidth = Math.max(200, containerWidth - LANE_LABEL_WIDTH);
    const nonworking = s.days.filter(d => !d.is_working).length;
    const working = s.days.length - nonworking;
    const workingPanelWidth = Math.max(80,
      (chartWidth - nonworking * NONWORKING_WIDTH) / Math.max(working, 1));
    const [wsH, wsM] = s.day_shape.workday_start.split(':').map(n => +n);
    const [weH, weM] = s.day_shape.workday_end.split(':').map(n => +n);
    const [lsH, lsM] = s.day_shape.lunch_start.split(':').map(n => +n);
    const [leH, leM] = s.day_shape.lunch_end.split(':').map(n => +n);
    const workdayStartMins = wsH * 60 + wsM;
    const workdayEndMins = weH * 60 + weM;
    const lunchStartMins = lsH * 60 + lsM;
    const lunchEndMins = leH * 60 + leM;
    const dayMinutes = workdayEndMins - workdayStartMins;
    const serverOffset = isoOffsetMinutes(s.now);

    const panels = [];
    let runningX = 0;
    for (const d of s.days) {
      const w = d.is_working ? workingPanelWidth : NONWORKING_WIDTH;
      panels.push({ date: d.date, is_working: d.is_working, x: runningX, width: w });
      runningX += w;
    }

    // Accepts an ISO string (preferred — server-timezone-aware) or a Date
    // (which is converted to ISO at the server's offset).
    function timeToX(t) {
      const iso = (typeof t === 'string') ? t : isoAt(t.getTime(), serverOffset);
      const key = isoDate(iso);
      const idx = panels.findIndex(p => p.date === key);
      if (idx < 0) {
        if (key < panels[0].date) return 0;
        return chartWidth;
      }
      const p = panels[idx];
      if (!p.is_working) return p.x + p.width / 2;
      const minutesIntoDay = isoMinutesOfDay(iso) - workdayStartMins;
      const fraction = Math.max(0, Math.min(1, minutesIntoDay / dayMinutes));
      return p.x + fraction * p.width;
    }

    // Lunch bands: one per working-day panel.
    const lunchBands = panels
      .filter(p => p.is_working)
      .map(p => {
        const a = (lunchStartMins - workdayStartMins) / dayMinutes;
        const b = (lunchEndMins - workdayStartMins) / dayMinutes;
        return {
          date: p.date,
          left: p.x + Math.max(0, a) * p.width,
          width: Math.max(0, Math.min(1, b) - Math.max(0, a)) * p.width,
        };
      });

    return {
      panels, chartWidth, timeToX, serverOffset, lunchBands,
      start: new Date(s.horizon_start), end: new Date(s.horizon_end),
    };
  }

  let layout = $derived(buildPanelLayout($schedule));

  let nowX = $derived.by(() => {
    if (!$schedule || !layout) return null;
    void nowTick;  // re-derive each tick
    const serverNowMs = new Date($schedule.now).getTime();
    const liveMs = Math.max(serverNowMs, Date.now());
    const liveIso = isoAt(liveMs, layout.serverOffset);
    return layout.timeToX(liveIso);
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
            {#each layout?.lunchBands ?? [] as band (band.date)}
              <div class="lunch-band"
                   style="left: {band.left}px; width: {band.width}px;"></div>
            {/each}
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
  .lunch-band {
    position: absolute;
    top: 0;
    bottom: 0;
    background-image: repeating-linear-gradient(45deg,
      rgba(180,180,180,0.45), rgba(180,180,180,0.45) 4px,
      rgba(238,238,238,0.45) 4px, rgba(238,238,238,0.45) 8px);
    z-index: 1;
  }
  .empty { color: #888; padding: 12px; }
</style>
