<script>
  let { days = [], laneLabelWidth = 90, layout = null } = $props();
</script>

<div class="header">
  <div class="lane-label-spacer" style="width: {laneLabelWidth}px;"></div>
  <div class="days">
    {#if layout}
      {#each layout.panels as panel, i (panel.date)}
        {@const day = days[i]}
        <div class="day" class:nonworking={!panel.is_working}
             style="width: {panel.width}px;">
          {day?.label || ''}
        </div>
      {/each}
    {/if}
  </div>
</div>

<style>
  .header { display: flex; align-items: stretch; padding-bottom: 4px; }
  .lane-label-spacer { background: #f4f5f7; }
  .days { display: flex; flex: 1; }
  .day {
    font-size: 12px; color: #333; padding: 4px 6px;
    border-bottom: 1px solid #ccc;
    box-sizing: border-box;
  }
  .day.nonworking {
    color: #999; padding: 4px 0; border-bottom: 1px solid #ddd;
    font-size: 9px; overflow: hidden; text-align: center;
  }
</style>
