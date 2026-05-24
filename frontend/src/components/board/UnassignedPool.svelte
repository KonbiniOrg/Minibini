<script>
  import TaskCard from './TaskCard.svelte';
  import { onMount } from 'svelte';

  let { tasks = [], canManage = false, focusedJobIds = [], onAssign = () => {} } = $props();
  let draggingTaskId = $state(null);

  let visibleTasks = $derived(
    focusedJobIds.length === 0
      ? tasks
      : tasks.filter(t => focusedJobIds.includes(t.job_id))
  );

  onMount(() => {
    function onDragStart(e) {
      const card = e.target.closest('[data-task-id]');
      if (card) draggingTaskId = parseInt(card.dataset.taskId);
    }
    function onDragEnd() { draggingTaskId = null; }
    document.addEventListener('dragstart', onDragStart);
    document.addEventListener('dragend', onDragEnd);
    return () => {
      document.removeEventListener('dragstart', onDragStart);
      document.removeEventListener('dragend', onDragEnd);
    };
  });

  function handleDragOver(e) {
    if (canManage) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
    }
  }

  function handleDrop(e) {
    e.preventDefault();
    if (!canManage) return;
    const taskId = parseInt(e.dataTransfer.getData('text/plain'));
    draggingTaskId = null;
    if (!taskId) return;
    onAssign(taskId, null, -1);
  }
</script>

<div class="unassigned-header">
  Unassigned <span class="ua-count">&middot; {visibleTasks.length} task{visibleTasks.length === 1 ? '' : 's'}{focusedJobIds.length > 0 && visibleTasks.length !== tasks.length ? ` (of ${tasks.length})` : ''}</span>
</div>
<!-- drag-and-drop drop zone: HTML5 DnD is mouse-only, no keyboard equivalent -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="unassigned-body"
  ondragover={handleDragOver}
  ondrop={handleDrop}
>
  {#each visibleTasks as task (task.task_id)}
    <div
      class:dragging-source={draggingTaskId === task.task_id}
    >
      <TaskCard {task} draggable={canManage} />
    </div>
  {/each}
  {#if visibleTasks.length === 0}
    <p class="empty">{tasks.length === 0 ? 'All tasks assigned' : 'No unassigned tasks for focused jobs'}</p>
  {/if}
</div>

<style>
  .unassigned-header { padding: 8px 12px; background: #fff; display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: #666; flex-shrink: 0; }
  .ua-count { font-weight: 400; color: #999; }
  .unassigned-body {
    padding: 8px; background: #f5f5f5; overflow-y: auto; flex: 1;
    display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 5px; align-content: start;
  }
  .dragging-source { opacity: 0.15; }
  .empty { font-size: 13px; color: #999; text-align: center; padding: 20px 0; grid-column: 1 / -1; }
</style>
