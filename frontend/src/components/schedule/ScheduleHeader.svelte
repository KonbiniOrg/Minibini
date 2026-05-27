<script>
  let {
    days = [],
    laneLabelWidth = 90,
    layout = null,
    onPrev = () => {},
    onNext = () => {},
    onToday = () => {},
    atToday = false,
  } = $props();
</script>

<div class="header">
  <div class="lane-label-spacer" style="width: {laneLabelWidth}px;">
    <button class="today-btn" onclick={onToday} disabled={atToday}
            title="Jump to today">Today</button>
  </div>
  <div class="days">
    {#if layout}
      {#each layout.panels as panel, i (panel.date)}
        {@const day = days[i]}
        {@const label = panel.is_working
          ? (day?.label || '')
          : (day?.label || '').split('·')[0].trim()}
        <div class="day" class:nonworking={!panel.is_working}
             style="width: {panel.width}px;">
          {label}
        </div>
      {/each}
    {/if}
  </div>
  <div class="nav-cluster">
    <button class="nav" onclick={onPrev}
            title="Earlier working day" aria-label="Scroll to earlier day">‹</button>
    <button class="nav" onclick={onNext}
            title="Later working day" aria-label="Scroll to later day">›</button>
  </div>
</div>

<style>
  .header { display: flex; align-items: stretch; padding-bottom: 4px; position: relative; }
  .lane-label-spacer {
    background: #f4f5f7; display: flex; align-items: center; justify-content: center;
  }
  .today-btn {
    font-size: 12px; padding: 3px 10px; border: 1px solid #2563eb;
    background: #fff; color: #2563eb; border-radius: 5px; cursor: pointer;
    font-weight: 600;
  }
  .today-btn:hover:not(:disabled) { background: #eff6ff; }
  .today-btn:disabled { border-color: #cbd5e1; color: #9ca3af; cursor: default; }
  .days { display: flex; flex: 1; }
  .day {
    font-size: 12px; color: #333; padding: 4px 6px;
    border-bottom: 1px solid #ccc;
    box-sizing: border-box;
    text-align: center;
  }
  .day.nonworking {
    color: #333; padding: 4px 0; border-bottom: 1px solid #ccc;
    font-size: 10px; overflow: hidden;
  }
  /* Both chevrons cluster at the far-right end of the header bar, overlaying
     the right edge like the next-arrow always did. */
  .nav-cluster {
    position: absolute; right: 0; top: 50%; transform: translateY(-50%);
    display: flex; gap: 2px;
    background: rgba(255,255,255,0.85); border-radius: 4px;
  }
  .nav {
    border: none; background: none; cursor: pointer;
    font-size: 26px; line-height: 1; color: #6b7280;
    padding: 0 4px;
  }
  .nav:hover { color: #1f2937; }
</style>
