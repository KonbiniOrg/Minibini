<script>
  import TaskCard from './TaskCard.svelte';
  import { onMount } from 'svelte';

  let { tasks = [], canManage = false, focusedJobId = null, onAssign = () => {} } = $props();
  let draggingTaskId = $state(null);

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
    if (!taskId) return;
    onAssign(taskId, null, -1);
  }
</script>

<div class="unassigned-header">
  Unassigned <span class="ua-count">&middot; {tasks.length} tasks</span>
</div>
<div
  class="unassigned-body"
  ondragover={handleDragOver}
  ondrop={handleDrop}
>
  {#each tasks as task (task.task_id)}
    <div
      class:dimmed={focusedJobId !== null && task.job_id !== focusedJobId}
      class:dragging-source={draggingTaskId === task.task_id}
    >
      <TaskCard {task} draggable={canManage} />
    </div>
  {/each}
  {#if tasks.length === 0}
    <p class="empty">All tasks assigned</p>
  {/if}
</div>

<style>
  .unassigned-header { padding: 8px 12px; background: #fff; display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: #666; flex-shrink: 0; }
  .ua-count { font-weight: 400; color: #999; }
  .unassigned-body {
    padding: 8px; background: #f5f5f5; overflow-y: auto; flex: 1;
    display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 5px; align-content: start;
  }
  .dimmed { opacity: 0.25; transition: opacity 0.2s; }
  .dragging-source { opacity: 0.15; }
  .empty { font-size: 13px; color: #999; text-align: center; padding: 20px 0; grid-column: 1 / -1; }
</style>
