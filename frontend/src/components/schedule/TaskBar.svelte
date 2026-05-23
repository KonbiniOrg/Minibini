<script>
  import { draggingTaskId } from '../../stores/schedule.js';

  let { bar, timeToX, panelStart, panelEnd, onDragStart = null, onSelect = null, focusedJobIds = [] } = $props();

  // When a job is focused via the chip strip, bars of other jobs dim and
  // lose their interactivity (no click-to-open, no drag).
  let dimmed = $derived(focusedJobIds.length > 0 && !focusedJobIds.includes(bar.job_id));

  function darken(hex, pct = 0.3) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    const f = 1 - pct;
    return '#' + [r, g, b]
      .map(c => Math.round(c * f).toString(16).padStart(2, '0'))
      .join('');
  }

  let lightColor = $derived(bar.accent_color || '#888');
  let darkColor = $derived(darken(lightColor));

  // No estimate layer anywhere (a non-assignee's bar) → there is no top
  // half, so the label sits on the dark bottom-half stripe instead.
  let hasEst = $derived(bar.segments.some(s => s.est_fill_to));

  // Keep both ISO strings (for TZ-agnostic positioning via timeToX) and
  // Date objects (for absolute-moment range filtering against panelStart/End).
  let segs = $derived(bar.segments
    .map(s => ({
      start_iso: s.start,
      end_iso: s.end,
      est_iso: s.est_fill_to,
      actual_iso: s.actual_fill_to,
      start: new Date(s.start),
      end: new Date(s.end),
      continues_left: s.continues_left,
      continues_right: s.continues_right,
    }))
    .filter(s => s.end > panelStart && s.start < panelEnd)
  );

  function handleDragStart(e) {
    e.dataTransfer.setData('text/plain', String(bar.task_id));
    e.dataTransfer.effectAllowed = 'move';
    // Build a small custom chip as the drag image so the ghost is always
    // a clean rectangle. Using e.currentTarget directly let some browsers
    // capture a wider region including neighboring bars or gap bands.
    const ghost = document.createElement('div');
    ghost.textContent = bar.name;
    ghost.style.cssText = `
      position: absolute; top: -1000px; left: -1000px;
      background: ${bar.accent_color || '#888'};
      color: #fff; padding: 4px 10px;
      font: 11px ui-monospace, Menlo, monospace;
      border-radius: 3px; white-space: nowrap;
      pointer-events: none; opacity: 0.92;
      box-shadow: 0 2px 6px rgba(0,0,0,0.25);
      max-width: 240px; overflow: hidden; text-overflow: ellipsis;
    `;
    document.body.appendChild(ghost);
    e.dataTransfer.setDragImage(ghost, 12, 12);
    setTimeout(() => document.body.removeChild(ghost), 0);
    draggingTaskId.set(bar.task_id);
    if (onDragStart) onDragStart(bar.task_id);
  }

  function handleDragEnd() {
    draggingTaskId.set(null);
  }

  let isDraggable = $derived(bar.kind === 'forecast' && !dimmed);
</script>

{#each segs as seg, i (i)}
  {@const left = timeToX(seg.start < panelStart ? panelStart : seg.start_iso)}
  {@const right = timeToX(seg.end > panelEnd ? panelEnd : seg.end_iso)}
  {@const width = Math.max(2, right - left)}
  {@const estWidth = seg.est_iso ? Math.max(0, timeToX(seg.est_iso) - left) : 0}
  {@const actWidth = seg.actual_iso ? Math.max(0, timeToX(seg.actual_iso) - left) : 0}
  {@const zigClass = seg.continues_left && seg.continues_right
                     ? 'zig-both'
                     : seg.continues_left ? 'zig-left'
                     : seg.continues_right ? 'zig-right' : ''}
  <!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
  <div class="task-bar {zigClass} kind-{bar.kind}"
       class:dimmed
       class:blocked={bar.status === 'blocked'}
       draggable={isDraggable}
       ondragstart={handleDragStart}
       ondragend={handleDragEnd}
       onclick={() => { if (!dimmed && onSelect) onSelect(bar); }}
       data-task-id={bar.task_id}
       style="left: {left}px; width: {width}px; cursor: {dimmed ? 'default' : 'pointer'};"
       title="{bar.name}{bar.status === 'blocked' && bar.blocked_reason ? ' · BLOCKED: ' + bar.blocked_reason : ''} · est {bar.est_minutes}m · elapsed {bar.elapsed_minutes}m">
    {#if estWidth > 0}
      <div class="layer-est" style="width: {estWidth}px; background: {lightColor};"></div>
    {/if}
    {#if actWidth > 0}
      <!-- Actuals are the dark, bottom-half layer. The top (estimate) half
           only appears for the assignee — a non-assignee's bar is just
           this dark blep stripe, no estimate. -->
      <div class="layer-actual" style="width: {actWidth}px; background: {darkColor};"></div>
    {/if}
    {#if bar.status === 'blocked'}
      <!-- Blocked: a red diagonal hatch over the forecast, echoing the
           board's red treatment. -->
      <div class="blocked-overlay"></div>
    {/if}
    {#if i === 0}
      <span class="label" class:bottom={!hasEst}>{bar.name}</span>
    {/if}
  </div>
{/each}

<style>
  .task-bar {
    position: absolute;
    top: 0;
    height: 100%;
    overflow: hidden;
  }
  .layer-est, .layer-actual { position: absolute; left: 0; }
  .layer-est    { top: 0;    height: 50%; }
  .layer-actual { bottom: 0; height: 50%; }
  .blocked-overlay {
    position: absolute; inset: 0;
    pointer-events: none;
    background-image: repeating-linear-gradient(45deg,
      rgba(239,68,68,0.5), rgba(239,68,68,0.5) 3px,
      transparent 3px, transparent 7px);
  }
  /* A red ring so a blocked bar reads as blocked at a glance (mirrors the
     job board's red treatment). */
  .task-bar.blocked { box-shadow: inset 0 0 0 2px #ef4444; }
  .label {
    position: absolute; left: 4px; top: 2px;
    font-size: 10px; color: #fff;
    text-shadow: 0 0 2px rgba(0,0,0,0.5);
    pointer-events: none; white-space: nowrap;
  }
  /* No estimate layer: label rides the dark bottom-half stripe. */
  .label.bottom { top: auto; bottom: 2px; }
  .kind-historical { opacity: 0.55; }
  .task-bar.dimmed { opacity: 0.18; }

  .zig-right { clip-path: polygon(
    0 0, 100% 0,
    calc(100% - 5px) 25%, 100% 50%,
    calc(100% - 5px) 75%, 100% 100%,
    0 100%); }
  .zig-left  { clip-path: polygon(
    5px 0, 100% 0, 100% 100%, 5px 100%,
    0 75%, 5px 50%, 0 25%); }
  .zig-both  { clip-path: polygon(
    5px 0, 100% 0, calc(100% - 5px) 25%, 100% 50%,
    calc(100% - 5px) 75%, 100% 100%, 5px 100%,
    0 75%, 5px 50%, 0 25%); }
</style>
