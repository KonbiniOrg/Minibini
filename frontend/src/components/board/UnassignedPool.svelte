<script>
  import TaskCard from './TaskCard.svelte';
  import { api } from '../../lib/api.js';

  let { tasks = [], canManage = false, focusedJobId = null, onUpdate = () => {} } = $props();

  function handleDragOver(e) {
    if (canManage) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
    }
  }

  async function handleDrop(e) {
    e.preventDefault();
    if (!canManage) return;
    const taskId = e.dataTransfer.getData('text/plain');
    if (!taskId) return;

    try {
      // Unassign: set worker_queue to null via reorder with empty list
      // The board reload will pick up the change
      await api.post('/api/tasks/reorder/', { task_ids: [parseInt(taskId)] });
      onUpdate();
    } catch (err) {
      console.error('Failed to unassign task:', err);
    }
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
    <div class:dimmed={focusedJobId !== null && task.job_id !== focusedJobId}>
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
  .empty { font-size: 13px; color: #999; text-align: center; padding: 20px 0; grid-column: 1 / -1; }
</style>
