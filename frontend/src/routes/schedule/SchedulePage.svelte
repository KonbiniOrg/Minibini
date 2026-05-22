<script>
  import { onMount, onDestroy } from 'svelte';
  import { schedule, loadSchedule, startAutoRefresh, stopAutoRefresh, scrollDays, resetToToday } from '../../stores/schedule.js';
  import ScheduleHeader from '../../components/schedule/ScheduleHeader.svelte';
  import WorkerLane from '../../components/schedule/WorkerLane.svelte';
  import NowLine from '../../components/schedule/NowLine.svelte';
  import JobChipStrip from '../../components/board/JobChipStrip.svelte';
  import TaskQuickCard from '../../components/schedule/TaskQuickCard.svelte';

  let containerEl;
  let containerWidth = $state(1200);
  let nowTick = $state(Date.now());

  // Job-card focus: clicking job chips dims tasks of other jobs.
  let focusedJobIds = $state([]);

  // Selected task for the quick-card popout.
  let selectedBar = $state(null);
  let selectedAssignee = $state('');

  function handleSelectTask(bar, worker) {
    selectedBar = bar;
    selectedAssignee = worker?.user?.name || '';
  }
  function closeCard() {
    selectedBar = null;
    selectedAssignee = '';
  }
  // Job lookup for the card header (job_number / name).
  let selectedJob = $derived(
    selectedBar && $schedule
      ? $schedule.jobs.find(j => j.job_id === selectedBar.job_id)
      : null
  );
  let resizeObserver = null;
  let tickInterval = null;

  const LANE_LABEL_WIDTH = 150;
  const NONWORKING_WIDTH = 22;

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

    // Structural separation between consecutive working days:
    //
    //   [...workday region of day N...] [pad] [GAP] [pad] [...workday day N+1...]
    //
    // - PANEL_INNER_PAD is unused space inside the panel on sides facing
    //   another working day. Gives bars visible breathing room.
    // - OVERNIGHT_GAP_WIDTH is its own slot between consecutive working-day
    //   panels in the chart layout. Bars cannot enter it by construction —
    //   they are positioned only within the workday region of their panel.
    const OVERNIGHT_GAP_WIDTH = 16;
    const PANEL_INNER_PAD = 12;

    const nonworking = s.days.filter(d => !d.is_working).length;
    const working = s.days.length - nonworking;
    let overnightCount = 0;
    for (let i = 0; i < s.days.length - 1; i++) {
      if (s.days[i].is_working && s.days[i + 1].is_working) overnightCount++;
    }
    const workingPanelWidth = Math.max(80,
      (chartWidth - nonworking * NONWORKING_WIDTH - overnightCount * OVERNIGHT_GAP_WIDTH)
      / Math.max(working, 1));
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

    // Build panels and the dedicated overnight-gap slots in one pass.
    const panels = [];
    const overnightBands = [];
    let runningX = 0;
    for (let i = 0; i < s.days.length; i++) {
      const d = s.days[i];
      const w = d.is_working ? workingPanelWidth : NONWORKING_WIDTH;
      panels.push({ date: d.date, is_working: d.is_working, x: runningX, width: w });
      runningX += w;
      const next = s.days[i + 1];
      if (next && d.is_working && next.is_working) {
        overnightBands.push({
          key: `${d.date}-overnight`,
          left: runningX,
          width: OVERNIGHT_GAP_WIDTH,
        });
        runningX += OVERNIGHT_GAP_WIDTH;
      }
    }

    // Each working-day panel reserves PANEL_INNER_PAD pixels of unused space
    // on any side that faces another working day. Bars are positioned only
    // within this inset workday region.
    function workdayInsets(idx) {
      const leftPad = (idx > 0 && panels[idx - 1].is_working) ? PANEL_INNER_PAD : 0;
      const rightPad = (idx < panels.length - 1 && panels[idx + 1].is_working) ? PANEL_INNER_PAD : 0;
      return { leftPad, rightPad };
    }

    // Lunch gets the same treatment as overnight: its own dedicated slot
    // inside each working-day panel, with inner padding on each side. The
    // panel's "workday content" is the morning stretch plus the afternoon
    // stretch, separated by the lunch slot. Bars only land in the work
    // stretches; the lunch slot is structurally inaccessible.
    const LUNCH_GAP_WIDTH = 16;
    const LUNCH_INNER_PAD = 12;
    const LUNCH_TOTAL_INSET = LUNCH_GAP_WIDTH + 2 * LUNCH_INNER_PAD;
    const morningDuration = lunchStartMins - workdayStartMins;
    const afternoonDuration = workdayEndMins - lunchEndMins;
    const totalWorkDuration = morningDuration + afternoonDuration;

    function panelStretches(p, idx) {
      const { leftPad, rightPad } = workdayInsets(idx);
      const workdayContent = p.width - leftPad - rightPad - LUNCH_TOTAL_INSET;
      const morningWidth = workdayContent * (morningDuration / totalWorkDuration);
      const afternoonWidth = workdayContent * (afternoonDuration / totalWorkDuration);
      const morningLeft = p.x + leftPad;
      const morningRight = morningLeft + morningWidth;
      const lunchLeft = morningRight + LUNCH_INNER_PAD;
      const lunchRight = lunchLeft + LUNCH_GAP_WIDTH;
      const afternoonLeft = lunchRight + LUNCH_INNER_PAD;
      const afternoonRight = afternoonLeft + afternoonWidth;
      return { morningLeft, morningRight, morningWidth,
               lunchLeft, lunchRight,
               afternoonLeft, afternoonRight, afternoonWidth };
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
      const s = panelStretches(p, idx);
      const minutes = isoMinutesOfDay(iso);
      if (minutes <= workdayStartMins) return s.morningLeft;
      if (minutes <= lunchStartMins) {
        const f = (minutes - workdayStartMins) / morningDuration;
        return s.morningLeft + f * s.morningWidth;
      }
      if (minutes < lunchEndMins) {
        // A time inside the lunch slot — shouldn't happen for bars (the
        // server splits them around lunch) but handle defensively.
        return (s.lunchLeft + s.lunchRight) / 2;
      }
      if (minutes <= workdayEndMins) {
        const f = (minutes - lunchEndMins) / afternoonDuration;
        return s.afternoonLeft + f * s.afternoonWidth;
      }
      return s.afternoonRight;
    }

    // Lunch bands live in their dedicated slot inside each working panel.
    const lunchBands = panels
      .map((p, idx) => ({ p, idx }))
      .filter(({ p }) => p.is_working)
      .map(({ p, idx }) => {
        const s = panelStretches(p, idx);
        return {
          date: p.date,
          left: s.lunchLeft,
          width: s.lunchRight - s.lunchLeft,
        };
      });

    // Non-working day columns get the same hatched treatment as overnight.
    const nonWorkingBands = panels
      .filter(p => !p.is_working)
      .map(p => ({ date: p.date, left: p.x, width: p.width }));

    // Off-hours background: the region of each working-day panel between the
    // configured hours and the (possibly widened) display hours — i.e. the
    // early/late margins where only in-progress work appears. Pale grey,
    // drawn behind the bars.
    const cfgStart = s.day_shape.config_workday_start || s.day_shape.workday_start;
    const cfgEnd = s.day_shape.config_workday_end || s.day_shape.workday_end;
    const offHoursBands = [];
    for (const p of panels) {
      if (!p.is_working) continue;
      const dayStartX = timeToX(`${p.date}T${s.day_shape.workday_start}:00`);
      const dayEndX = timeToX(`${p.date}T${s.day_shape.workday_end}:00`);
      const cfgStartX = timeToX(`${p.date}T${cfgStart}:00`);
      const cfgEndX = timeToX(`${p.date}T${cfgEnd}:00`);
      if (cfgStartX > dayStartX + 0.5) {
        offHoursBands.push({ key: `${p.date}-early`, left: dayStartX, width: cfgStartX - dayStartX });
      }
      if (dayEndX > cfgEndX + 0.5) {
        offHoursBands.push({ key: `${p.date}-late`, left: cfgEndX, width: dayEndX - cfgEndX });
      }
    }

    return {
      panels, chartWidth, timeToX, serverOffset,
      lunchBands, overnightBands, nonWorkingBands, offHoursBands,
      start: new Date(s.horizon_start), end: new Date(s.horizon_end),
    };
  }

  let layout = $derived(buildPanelLayout($schedule));

  let nowX = $derived.by(() => {
    if (!$schedule || !layout) return null;
    void nowTick;  // re-derive each tick
    const serverNowMs = new Date($schedule.now).getTime();
    const liveMs = Math.max(serverNowMs, Date.now());
    const live = new Date(liveMs);
    // Hide the now-line when "now" is outside the visible (scrolled) window.
    if (live < layout.start || live >= layout.end) return null;
    const liveIso = isoAt(liveMs, layout.serverOffset);
    return layout.timeToX(liveIso);
  });
</script>

<div class="schedule-page" bind:this={containerEl}>
  <div class="page-head">
    <h2>Schedule</h2>
    {#if $schedule !== null}
      <div class="days-control" role="group" aria-label="Days to show">
        <span class="days-label">Working days:</span>
        {#each [1, 2, 3, 5, 10] as n}
          <button type="button"
                  class:active={$schedule.horizon_days === n}
                  onclick={() => loadSchedule(n)}>{n}</button>
        {/each}
      </div>
      {#if $schedule.offset}
        <button type="button" class="today-btn" onclick={() => resetToToday()}>Today</button>
      {/if}
    {/if}
  </div>
  {#if $schedule === null}
    <p>Loading schedule…</p>
  {:else}
    <JobChipStrip jobs={$schedule.jobs} bind:focusedJobIds />
    <div class="chart-area">
      <ScheduleHeader days={$schedule.days} laneLabelWidth={LANE_LABEL_WIDTH} {layout}
                      onPrev={() => scrollDays(-1)}
                      onNext={() => scrollDays(1)} />
      {#if $schedule.workers.length === 0}
        <p class="empty">No assigned work in the visible horizon.</p>
      {:else}
        <div class="chart">
          <div class="bg-overlay" style="left: {LANE_LABEL_WIDTH}px; width: calc(100% - {LANE_LABEL_WIDTH}px);">
            {#each layout?.offHoursBands ?? [] as band (band.key)}
              <div class="offhours-band"
                   style="left: {band.left}px; width: {band.width}px;"></div>
            {/each}
          </div>
          <div class="lanes">
            {#each $schedule.workers as worker (worker.user.id)}
              <WorkerLane {worker}
                          dayShape={$schedule.day_shape}
                          panelLayout={layout}
                          laneLabelWidth={LANE_LABEL_WIDTH}
                          {focusedJobIds}
                          onSelectTask={handleSelectTask} />
            {/each}
          </div>
          <div class="now-overlay" style="left: {LANE_LABEL_WIDTH}px; width: calc(100% - {LANE_LABEL_WIDTH}px);">
            {#each layout?.nonWorkingBands ?? [] as band (band.date)}
              <div class="overnight-band"
                   style="left: {band.left}px; width: {band.width}px;"></div>
            {/each}
            {#each layout?.overnightBands ?? [] as band (band.key)}
              <div class="overnight-band"
                   style="left: {band.left}px; width: {band.width}px;"></div>
            {/each}
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

  {#if selectedBar}
    <TaskQuickCard
      bar={selectedBar}
      assigneeName={selectedAssignee}
      jobNumber={selectedJob?.job_number || ''}
      jobName={selectedJob?.name || ''}
      onClose={closeCard}
      onChanged={() => loadSchedule()} />
  {/if}
</div>

<style>
  .schedule-page { padding: 12px; }
  .page-head { display: flex; align-items: baseline; gap: 16px; }
  .days-control { display: flex; align-items: center; gap: 4px; }
  .days-label { font-size: 12px; color: #6b7280; margin-right: 2px; }
  .days-control button {
    font-size: 12px; min-width: 26px; padding: 3px 7px;
    border: 1px solid #d1d5db; background: #fff; color: #374151;
    border-radius: 5px; cursor: pointer;
  }
  .days-control button:hover { background: #f3f4f6; }
  .days-control button.active {
    background: #2563eb; border-color: #2563eb; color: #fff; font-weight: 600;
  }
  .today-btn {
    font-size: 12px; padding: 3px 10px; border: 1px solid #2563eb;
    background: #fff; color: #2563eb; border-radius: 5px; cursor: pointer;
    font-weight: 600;
  }
  .today-btn:hover { background: #eff6ff; }
  .chart-area { margin-top: 8px; }
  .chart { position: relative; }
  /* Stacking: off-hours background (0) < lanes/bars (1) < bands & now-line (2) */
  .lanes { position: relative; z-index: 1; }
  .now-overlay { position: absolute; top: 0; bottom: 0; pointer-events: none; z-index: 2; }
  .bg-overlay { position: absolute; top: 0; bottom: 0; pointer-events: none; z-index: 0; }
  .offhours-band {
    position: absolute; top: 0; bottom: 0;
    background: #f1f2f4;
  }
  .lunch-band {
    position: absolute;
    top: 0;
    bottom: 0;
    background-image: repeating-linear-gradient(45deg,
      rgba(180,180,180,0.45), rgba(180,180,180,0.45) 4px,
      rgba(238,238,238,0.45) 4px, rgba(238,238,238,0.45) 8px);
    z-index: 1;
  }
  /* Overnight: denser, darker hatching at the day boundary. Reads as a
     bigger break than lunch even though it's only a sliver of pixels. */
  .overnight-band {
    position: absolute;
    top: 0;
    bottom: 0;
    background-image: repeating-linear-gradient(-45deg,
      rgba(60,60,90,0.55), rgba(60,60,90,0.55) 3px,
      rgba(150,150,180,0.55) 3px, rgba(150,150,180,0.55) 6px);
    z-index: 1;
  }
  .empty { color: #888; padding: 12px; }
</style>
