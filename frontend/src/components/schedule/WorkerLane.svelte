<script>
  import TaskBar from './TaskBar.svelte';
  import { reorderTasksInLane } from '../../stores/schedule.js';

  let { worker, dayShape, panelLayout, laneLabelWidth = 90 } = $props();

  let primaryBars = $derived(worker.bars.filter(b => b.kind !== 'parked'));
  let parkedBars = $derived(worker.bars.filter(b => b.kind === 'parked'));

  function timeToX(t) {
    return panelLayout ? panelLayout.timeToX(t) : 0;
  }

  function handleDragOver(e) {
    if (!e.dataTransfer) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }

  function handleDrop(e) {
    e.preventDefault();
    const draggedId = parseInt(e.dataTransfer.getData('text/plain'), 10);
    if (!draggedId) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const moveable = worker.bars.filter(
      b => b.kind === 'forecast' || b.kind === 'parked'
    );
    let insertAt = moveable.length;
    for (let i = 0; i < moveable.length; i++) {
      const segStart = new Date(moveable[i].segments[0]?.start);
      const bx = timeToX(segStart);
      if (x < bx) { insertAt = i; break; }
    }
    const allIds = moveable.map(b => b.task_id);
    const without = allIds.filter(id => id !== draggedId);
    without.splice(insertAt, 0, draggedId);
    reorderTasksInLane(worker.user.id, without);
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
       ondrop={handleDrop}>
    <div class="primary">
      {#each primaryBars as bar (`${bar.task_id}-${bar.kind}-${bar.segments[0]?.start}`)}
        <TaskBar {bar} {timeToX}
                 panelStart={panelLayout?.start}
                 panelEnd={panelLayout?.end} />
      {/each}
    </div>
    {#if parkedBars.length > 0}
      <div class="parked-strip">
        {#each parkedBars as bar (`${bar.task_id}-parked`)}
          <TaskBar {bar} {timeToX}
                   panelStart={panelLayout?.start}
                   panelEnd={panelLayout?.end} />
        {/each}
      </div>
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
  .parked-strip { position: relative; height: 20px; margin-top: 3px; }
</style>
