<script>
  import TaskCard from './TaskCard.svelte';
  import { api } from '../../lib/api.js';

  let { workers = [], canManage = false, focusedJobId = null, onUpdate = () => {} } = $props();

  async function handleDrop(e, workerId) {
    e.preventDefault();
    const taskId = e.dataTransfer.getData('text/plain');
    if (!taskId || !canManage) return;

    try {
      // Find the worker's current task list to determine queue position
      const worker = workers.find(w => w.user.id === workerId);
      const existingIds = worker ? worker.tasks.map(t => t.task_id) : [];
      const newOrder = [...existingIds, parseInt(taskId)];

      await api.post('/api/tasks/reorder/', { task_ids: newOrder });
      onUpdate();
    } catch (err) {
      console.error('Failed to assign task:', err);
    }
  }

  function handleDragOver(e) {
    if (canManage) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
    }
  }
</script>

<div class="worker-columns">
  {#each workers as worker (worker.user.id)}
    <div class="worker-col">
      <div class="worker-header">
        <div class="worker-avatar">{worker.user.initials}</div>
        <span class="worker-name">{worker.user.name}</span>
        <span class="worker-task-count">{worker.tasks.length}</span>
      </div>
      <div
        class="worker-tasks"
        ondragover={handleDragOver}
        ondrop={(e) => handleDrop(e, worker.user.id)}
      >
        {#each worker.tasks as task (task.task_id)}
          <div class:dimmed={focusedJobId !== null && task.job_id !== focusedJobId}>
            <TaskCard {task} draggable={canManage} />
          </div>
        {/each}
      </div>
    </div>
  {/each}
</div>

<style>
  .worker-columns { display: flex; flex: 1; overflow: hidden; }
  .worker-col { flex: 1; display: flex; flex-direction: column; border-right: 1px solid #e8e8e8; min-width: 0; }
  .worker-col:last-child { border-right: none; }
  .worker-header { padding: 8px 10px; background: #fff; border-bottom: 2px solid #4ade80; display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
  .worker-avatar {
    width: 24px; height: 24px; border-radius: 50%; font-size: 10px; font-weight: 700;
    display: flex; align-items: center; justify-content: center; color: #fff; background: #3b82f6;
  }
  .worker-name { font-size: 13px; font-weight: 600; }
  .worker-task-count { font-size: 11px; color: #999; margin-left: auto; }
  .worker-tasks { flex: 1; padding: 6px; display: flex; flex-direction: column; gap: 5px; background: #f8faf9; overflow-y: auto; min-height: 40px; }
  .dimmed { opacity: 0.25; transition: opacity 0.2s; }
</style>
