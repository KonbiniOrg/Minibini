<script>
  import TaskBar from './TaskBar.svelte';
  import { reorderTasksInLane, draggingTaskId } from '../../stores/schedule.js';

  let { worker, panelLayout, days = [], laneLabelWidth = 90, focusedJobIds = [], onSelectTask = () => {} } = $props();

  // Every bar renders in the single primary band, in queue order. Blocked
  // tasks are ordinary (styled) forecast bars now — there's no parked strip.
  let primaryBars = $derived(worker.bars);

  // Per-lane off-envelope shading: this worker's envelope_by_day (parallel
  // to days[]/panels[]) inverted against each working panel — the margins
  // before/after their hours and the gaps (breaks) between intervals. An
  // empty day shades the whole panel (their day off, even if others work).
  let laneOffBands = $derived.by(() => {
    const envByDay = worker.envelope_by_day;
    const panels = panelLayout?.panels;
    if (!envByDay || !panels) return [];
    const bands = [];
    for (let i = 0; i < panels.length && i < envByDay.length; i++) {
      const p = panels[i];
      if (!p.is_working) continue;  // non-working columns already hatch
      const intervals = envByDay[i] ?? [];
      if (intervals.length === 0) {
        bands.push({ key: `${p.date}-off`, left: p.x, width: p.width });
        continue;
      }
      let cursorX = p.x;
      for (const [start, end] of intervals) {
        const startX = panelLayout.timeToX(`${p.date}T${start}:00`);
        if (startX > cursorX + 0.5) {
          bands.push({ key: `${p.date}-${start}`, left: cursorX, width: startX - cursorX });
        }
        cursorX = panelLayout.timeToX(`${p.date}T${end}:00`);
      }
      const panelRight = p.x + p.width;
      if (panelRight > cursorX + 0.5) {
        bands.push({ key: `${p.date}-tail`, left: cursorX, width: panelRight - cursorX });
      }
    }
    return bands;
  });

  // Drop indicator: tracks the x-coordinate of the cursor within this
  // lane's .track while a drag is in progress. Cleared when the cursor
  // leaves the lane or when the drop completes.
  let dragOverX = $state(null);

  function timeToX(t) {
    return panelLayout ? panelLayout.timeToX(t) : 0;
  }

  // Reorder positions are driven by FORECAST bars (the rearrangeable future
  // queue); a task's past `actual` pieces don't affect where it drops.
  function taskStartX(id) {
    const xs = worker.bars
      .filter(b => b.task_id === id && b.kind === 'forecast')
      .map(b => timeToX(new Date(b.segments[0]?.start)))
      .filter(v => !Number.isNaN(v));
    return xs.length ? Math.min(...xs) : Infinity;
  }

  function taskEndX(id) {
    const xs = worker.bars
      .filter(b => b.task_id === id && b.kind === 'forecast')
      .flatMap(b => b.segments.map(s => timeToX(new Date(s.end))))
      .filter(v => !Number.isNaN(v));
    return xs.length ? Math.max(...xs) : -Infinity;
  }

  function currentIdsExcluding(excludedId) {
    const seen = new Set();
    const ids = [];
    for (const bar of worker.bars) {
      if (bar.kind !== 'forecast') continue;  // only future work reorders
      if (bar.task_id === excludedId) continue;
      if (seen.has(bar.task_id)) continue;
      seen.add(bar.task_id);
      ids.push(bar.task_id);
    }
    return ids;
  }

  // Position the indicator at the midpoint between the trailing edge of
  // the previous task and the leading edge of the next, given the current
  // cursor x. Returns null when no drag is in progress over this lane,
  // OR when the cursor is in a position that would leave the dragged
  // task in its current queue slot (no-op drop — no indicator).
  let indicatorX = $derived.by(() => {
    if (dragOverX === null) return null;
    const draggedId = $draggingTaskId;

    // Original index of dragged task in the FULL queue (incl. dragged).
    const fullIds = [];
    const seenFull = new Set();
    for (const bar of worker.bars) {
      if (bar.kind !== 'forecast') continue;
      if (seenFull.has(bar.task_id)) continue;
      seenFull.add(bar.task_id);
      fullIds.push(bar.task_id);
    }
    const originalIndex = fullIds.indexOf(draggedId);

    const ids = currentIdsExcluding(draggedId);
    let insertAt = ids.length;
    for (let i = 0; i < ids.length; i++) {
      if (taskStartX(ids[i]) > dragOverX) { insertAt = i; break; }
    }

    // No-op: insertAt in the excluded list corresponds to the dragged
    // task's current slot in the full queue. Don't show the indicator.
    if (originalIndex !== -1 && insertAt === originalIndex) return null;

    // For end-of-row or start-of-row positions, we want the indicator the
    // same visual distance from the adjacent task as it would sit in the
    // middle of a real buffer gap between two tasks. Sample buffer width
    // from any existing pair; fall back to a small constant.
    let halfBuffer = 6;
    for (let i = 0; i < ids.length - 1; i++) {
      const aEnd = taskEndX(ids[i]);
      const bStart = taskStartX(ids[i + 1]);
      if (Number.isFinite(aEnd) && Number.isFinite(bStart) && bStart > aEnd) {
        halfBuffer = (bStart - aEnd) / 2;
        break;
      }
    }

    if (insertAt === 0 && ids.length > 0) {
      // Before everything — half a buffer before the first task.
      return taskStartX(ids[0]) - halfBuffer;
    }
    if (insertAt >= ids.length) {
      // After everything — half a buffer past the last task.
      const prevEnd = ids.length > 0 ? taskEndX(ids[ids.length - 1]) : 0;
      return prevEnd + halfBuffer;
    }
    // Between two tasks — midpoint of the buffer gap.
    const prevEnd = taskEndX(ids[insertAt - 1]);
    const nextStart = taskStartX(ids[insertAt]);
    return (prevEnd + nextStart) / 2;
  });

  function handleDragOver(e) {
    if (!e.dataTransfer) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const rect = e.currentTarget.getBoundingClientRect();
    dragOverX = e.clientX - rect.left;
  }

  function handleDragLeave(e) {
    // Ignore leaves into children; only clear when the cursor truly exits
    // the lane.
    if (!e.currentTarget.contains(e.relatedTarget)) {
      dragOverX = null;
    }
  }

  function handleDrop(e) {
    e.preventDefault();
    dragOverX = null;
    const draggedId = parseInt(e.dataTransfer.getData('text/plain'), 10);
    if (!draggedId) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;

    const ids = currentIdsExcluding(draggedId);
    let insertAt = ids.length;
    for (let i = 0; i < ids.length; i++) {
      if (taskStartX(ids[i]) > x) { insertAt = i; break; }
    }
    ids.splice(insertAt, 0, draggedId);

    reorderTasksInLane(worker.user.id, ids);
  }
</script>

<div class="lane">
  <div class="label" style="width: {laneLabelWidth}px;">
    <span class="avatar">{worker.user.initials}</span>
    <span class="name">{worker.user.name}</span>
  </div>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="track"
       ondragover={handleDragOver}
       ondragleave={handleDragLeave}
       ondrop={handleDrop}>
    {#each laneOffBands as band (band.key)}
      <div class="lane-offhours" style="left: {band.left}px; width: {band.width}px;"></div>
    {/each}
    <div class="primary">
      {#each primaryBars as bar (`${bar.task_id}-${bar.kind}-${bar.segments[0]?.start}`)}
        <TaskBar {bar} {timeToX}
                 panelStart={panelLayout?.start}
                 panelEnd={panelLayout?.end}
                 {focusedJobIds}
                 onSelect={(b) => onSelectTask(b, worker)} />
      {/each}
    </div>
    {#if indicatorX !== null}
      <div class="drop-indicator" style="left: {indicatorX - 1}px;"></div>
    {/if}
  </div>
</div>

<style>
  .lane {
    display: flex; align-items: stretch;
    border-bottom: 1px solid #eee; min-height: 60px;
  }
  .label {
    display: flex; align-items: center; gap: 6px;
    padding: 8px 8px; font-size: 12px; flex-shrink: 0;
    box-sizing: border-box;
    background: #f4f5f7;        /* light tint so the column boundary is visible */
  }
  .avatar {
    width: 22px; height: 22px; border-radius: 50%;
    background: #3b82f6; color: #fff; font-size: 10px; font-weight: 700;
    display: inline-flex; align-items: center; justify-content: center;
    flex-shrink: 0;
  }
  .name { font-weight: 600; }
  .track { position: relative; flex: 1; }
  .primary { position: relative; height: 44px; margin-top: 8px; }
  .lane-offhours {
    position: absolute; top: 0; bottom: 0;
    background: #f1f2f4;
    pointer-events: none;
  }
  .drop-indicator {
    position: absolute;
    top: 4px;
    bottom: 4px;
    width: 3px;
    background: #9ca3af;
    border-radius: 2px;
    pointer-events: none;
    z-index: 3;
  }
</style>
