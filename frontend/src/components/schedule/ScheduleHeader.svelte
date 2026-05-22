<script>
  let {
    days = [],
    laneLabelWidth = 90,
    layout = null,
    onPrev = () => {},
    onNext = () => {},
  } = $props();
</script>

<div class="header">
  <div class="lane-label-spacer" style="width: {laneLabelWidth}px;">
    <button class="nav prev" onclick={onPrev}
            title="Earlier working day" aria-label="Scroll to earlier day">‹</button>
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
  <button class="nav next" onclick={onNext}
          title="Later working day" aria-label="Scroll to later day">›</button>
</div>

<style>
  .header { display: flex; align-items: stretch; padding-bottom: 4px; position: relative; }
  .lane-label-spacer { background: #f4f5f7; display: flex; align-items: center; justify-content: flex-start; }
  .days { display: flex; flex: 1; }
  .day {
    font-size: 12px; color: #333; padding: 4px 6px;
    border-bottom: 1px solid #ccc;
    box-sizing: border-box;
  }
  .day.nonworking {
    color: #333; padding: 4px 0; border-bottom: 1px solid #ccc;
    font-size: 10px; overflow: hidden; text-align: center;
  }
  .nav {
    border: none; background: none; cursor: pointer;
    font-size: 26px; line-height: 1; color: #6b7280;
    padding: 0 4px;
  }
  .nav:hover { color: #1f2937; }
  .nav.next {
    position: absolute; right: 0; top: 50%; transform: translateY(-50%);
    background: rgba(255,255,255,0.85); border-radius: 4px;
  }
  .nav.prev { font-weight: 700; }
</style>
