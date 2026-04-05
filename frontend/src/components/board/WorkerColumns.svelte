<script>
  import TaskCard from './TaskCard.svelte';
  import { onMount } from 'svelte';

  let { workers = [], availableWorkers = [], canManage = false, focusedJobIds = [], onAssign = () => {}, onAddWorker = () => {} } = $props();

  let showDropdown = $state(false);
  let dragOverWorker = $state(null);
  let dragOverIndex = $state(-1);
  let draggingTaskId = $state(null);

  function handleTaskDragOver(e, workerId, taskIndex) {
    if (!canManage) return;
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'move';

    const rect = e.currentTarget.getBoundingClientRect();
    const midY = rect.top + rect.height / 2;
    const index = e.clientY < midY ? taskIndex : taskIndex + 1;

    dragOverWorker = workerId;
    dragOverIndex = index;
  }

  function handleColumnDragOver(e, workerId) {
    if (!canManage) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    // Only update if we're not already tracking a specific card position in this column
    if (dragOverWorker !== workerId) {
      const worker = workers.find(w => w.user.id === workerId);
      dragOverWorker = workerId;
      dragOverIndex = worker ? worker.tasks.length : 0;
    }
  }

  function handleColumnDragLeave(e, workerId) {
    const col = e.currentTarget;
    if (!col.contains(e.relatedTarget)) {
      if (dragOverWorker === workerId) {
        dragOverWorker = null;
        dragOverIndex = -1;
      }
    }
  }

  function handleDrop(e, workerId) {
    e.preventDefault();
    const taskId = parseInt(e.dataTransfer.getData('text/plain'));
    const insertAt = dragOverIndex;
    dragOverWorker = null;
    dragOverIndex = -1;
    draggingTaskId = null;
    if (!taskId || !canManage) return;
    onAssign(taskId, workerId, insertAt);
  }

  function handleGlobalDragStart(e) {
    const card = e.target.closest('[data-task-id]');
    if (card) draggingTaskId = parseInt(card.dataset.taskId);
  }

  function handleGlobalDragEnd() {
    dragOverWorker = null;
    dragOverIndex = -1;
    draggingTaskId = null;
  }

  onMount(() => {
    document.addEventListener('dragstart', handleGlobalDragStart);
    document.addEventListener('dragend', handleGlobalDragEnd);
    return () => {
      document.removeEventListener('dragstart', handleGlobalDragStart);
      document.removeEventListener('dragend', handleGlobalDragEnd);
    };
  });

  function addWorker(user) {
    onAddWorker(user);
    showDropdown = false;
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
        ondragover={(e) => handleColumnDragOver(e, worker.user.id)}
        ondragleave={(e) => handleColumnDragLeave(e, worker.user.id)}
        ondrop={(e) => handleDrop(e, worker.user.id)}
      >
        {#each worker.tasks as task, i (task.task_id)}
          {#if dragOverWorker === worker.user.id && dragOverIndex === i}
            <div class="drop-placeholder"></div>
          {/if}
          <div
            class="task-card-wrapper"
            class:dimmed={focusedJobIds.length > 0 && !focusedJobIds.includes(task.job_id)}
            class:dragging-source={draggingTaskId === task.task_id}
            ondragover={(e) => handleTaskDragOver(e, worker.user.id, i)}
          >
            <TaskCard {task} draggable={canManage} />
          </div>
        {/each}
        {#if dragOverWorker === worker.user.id && dragOverIndex >= worker.tasks.length}
          <div class="drop-placeholder"></div>
        {/if}
      </div>
    </div>
  {/each}

  {#if canManage && availableWorkers.length > 0}
    <div class="add-worker-col">
      <div class="add-worker-btn-wrap">
        <button class="add-worker-btn" onclick={() => showDropdown = !showDropdown} title="Add worker column">+</button>
        {#if showDropdown}
          <div class="add-worker-dropdown">
            {#each availableWorkers as user (user.id)}
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
  .task-card-wrapper { transition: transform 0.15s ease; }
  .task-card-wrapper.dragging-source { opacity: 0.15; }
  .dimmed { opacity: 0.25; transition: opacity 0.2s; }

  .drop-placeholder {
    height: 36px;
    background: #e8f5ec;
    border: 2px dashed #4ade80;
    border-radius: 7px;
    transition: height 0.15s ease;
    flex-shrink: 0;
  }

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
