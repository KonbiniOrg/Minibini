<script>
  import TaskCard from './TaskCard.svelte';
  import { api } from '../../lib/api.js';

  let { workers = [], availableWorkers = [], canManage = false, focusedJobId = null, onUpdate = () => {} } = $props();

  let addedWorkers = $state([]);
  let showDropdown = $state(false);

  let allWorkers = $derived([
    ...workers,
    ...addedWorkers.filter(aw => !workers.some(w => w.user.id === aw.user.id)),
  ]);

  let filteredAvailable = $derived(
    availableWorkers.filter(aw => !addedWorkers.some(added => added.user.id === aw.id))
  );

  function addWorker(user) {
    addedWorkers = [...addedWorkers, { user, tasks: [] }];
    showDropdown = false;
  }

  async function handleDrop(e, workerId) {
    e.preventDefault();
    const taskId = e.dataTransfer.getData('text/plain');
    if (!taskId || !canManage) return;

    try {
      // Find the worker's current tasks to determine next queue position
      const worker = allWorkers.find(w => w.user.id === workerId);
      const nextQueue = worker && worker.tasks.length > 0
        ? Math.max(...worker.tasks.map(t => t.worker_queue || 0)) + 1
        : 1;

      await api.post(`/api/tasks/${taskId}/assign/`, {
        assignee: workerId,
        worker_queue: nextQueue,
      });
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
  {#each allWorkers as worker (worker.user.id)}
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

  {#if canManage && filteredAvailable.length > 0}
    <div class="add-worker-col">
      <div class="add-worker-btn-wrap">
        <button class="add-worker-btn" onclick={() => showDropdown = !showDropdown} title="Add worker column">+</button>
        {#if showDropdown}
          <div class="add-worker-dropdown">
            {#each filteredAvailable as user (user.id)}
              <button class="add-worker-option" onclick={() => addWorker(user)}>
                <span class="option-avatar">{user.initials}</span>
                {user.name}
              </button>
            {/each}
          </div>
        {/if}
      </div>
    </div>
  {/if}
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

  .add-worker-col { display: flex; flex-direction: column; border-left: 1px solid #e8e8e8; flex-shrink: 0; }
  .add-worker-btn-wrap { position: relative; padding: 8px 6px; }
  .add-worker-btn {
    width: 28px; height: 28px; border-radius: 50%; border: 2px dashed #ccc; background: none;
    font-size: 16px; color: #999; cursor: pointer; display: flex; align-items: center; justify-content: center;
    padding: 0; line-height: 1;
  }
  .add-worker-btn:hover { border-color: #4ade80; color: #4ade80; }

  .add-worker-dropdown {
    position: absolute; top: 40px; left: 6px; z-index: 10;
    background: #fff; border: 1px solid #ddd; border-radius: 4px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.12); min-width: 160px;
    display: flex; flex-direction: column;
  }
  .add-worker-option {
    display: flex; align-items: center; gap: 8px; padding: 8px 12px;
    border: none; background: none; cursor: pointer; font-size: 13px; text-align: left;
    white-space: nowrap;
  }
  .add-worker-option:hover { background: #f0fdf4; }
  .option-avatar {
    width: 22px; height: 22px; border-radius: 50%; font-size: 9px; font-weight: 700;
    display: inline-flex; align-items: center; justify-content: center; color: #fff; background: #3b82f6;
    flex-shrink: 0;
  }
</style>
