<script>
  import JobChipStrip from './JobChipStrip.svelte';
  import WorkerColumns from './WorkerColumns.svelte';
  import UnassignedPool from './UnassignedPool.svelte';
  import ResizeHandle from './ResizeHandle.svelte';
  import { api } from '../../lib/api.js';

  let { data = {}, canManage = false, onUpdate = () => {} } = $props();
  let focusedJobId = $state(null);
  let workerPct = $state(50); // percentage of worker-area given to worker section

  let workers = $state([]);
  let unassigned = $state([]);
  let availableWorkers = $state([]);
  let addedWorkers = $state([]);

  // Sync from props when data changes
  $effect(() => {
    if (data.workers) workers = data.workers.map(w => ({...w, tasks: [...w.tasks]}));
    if (data.unassigned) unassigned = [...data.unassigned];
    if (data.available_workers) availableWorkers = [...data.available_workers];
  });

  // Merge API workers with manually-added empty workers
  let allWorkers = $derived.by(() => {
    const apiWorkerIds = new Set(workers.map(w => w.user.id));
    const extras = addedWorkers.filter(w => !apiWorkerIds.has(w.user.id));
    return [...workers, ...extras];
  });

  // Available = those not in any column
  let filteredAvailable = $derived.by(() => {
    const shownIds = new Set(allWorkers.map(w => w.user.id));
    return availableWorkers.filter(w => !shownIds.has(w.id));
  });

  function addWorker(user) {
    addedWorkers = [...addedWorkers, { user, tasks: [] }];
  }

  async function assignTask(taskId, targetWorkerId) {
    // Find the task object
    let task = null;

    // Check unassigned
    const uIdx = unassigned.findIndex(t => t.task_id === taskId);
    if (uIdx !== -1) {
      task = unassigned[uIdx];
      unassigned = unassigned.filter((_, i) => i !== uIdx);
    }

    // Check workers
    if (!task) {
      for (const w of workers) {
        const tIdx = w.tasks.findIndex(t => t.task_id === taskId);
        if (tIdx !== -1) {
          task = w.tasks[tIdx];
          w.tasks = w.tasks.filter((_, i) => i !== tIdx);
          break;
        }
      }
    }

    // Check added workers
    if (!task) {
      for (const w of addedWorkers) {
        const tIdx = w.tasks.findIndex(t => t.task_id === taskId);
        if (tIdx !== -1) {
          task = w.tasks[tIdx];
          w.tasks = w.tasks.filter((_, i) => i !== tIdx);
          break;
        }
      }
    }

    if (!task) return;

    if (targetWorkerId === null) {
      // Moving to unassigned
      task = {...task, assignee_id: null, worker_queue: null};
      unassigned = [...unassigned, task];
    } else {
      // Moving to a worker column
      let targetWorker = workers.find(w => w.user.id === targetWorkerId);
      if (!targetWorker) {
        targetWorker = addedWorkers.find(w => w.user.id === targetWorkerId);
      }
      if (targetWorker) {
        const nextQueue = targetWorker.tasks.length > 0
          ? Math.max(...targetWorker.tasks.map(t => t.worker_queue || 0)) + 1
          : 1;
        task = {...task, assignee_id: targetWorkerId, worker_queue: nextQueue};
        targetWorker.tasks = [...targetWorker.tasks, task];
      }
    }

    // Trigger reactivity
    workers = [...workers];
    addedWorkers = [...addedWorkers];

    // Fire API call in background
    try {
      await api.post(`/api/tasks/${taskId}/assign/`, {
        assignee: targetWorkerId,
        worker_queue: task.worker_queue,
      });
    } catch (err) {
      console.error('Failed to assign task:', err);
    }
  }
</script>

<div class="approved-header">
  <span class="col-indicator"></span>
  <strong>Approved</strong>
  <span class="count">{data.jobs?.length || 0}</span>
</div>
<div class="approved-content">
  <JobChipStrip jobs={data.jobs || []} bind:focusedJobId />

  <div class="worker-area" id="workerArea">
    <div class="worker-section" style="flex: {workerPct};">
      <WorkerColumns
        workers={allWorkers}
        {canManage}
        {focusedJobId}
        onAssign={assignTask}
        availableWorkers={filteredAvailable}
        onAddWorker={addWorker}
      />
    </div>
    <ResizeHandle direction="horizontal" onResize={(delta) => {
      const area = document.getElementById('workerArea');
      if (!area) return;
      const totalH = area.offsetHeight;
      if (totalH === 0) return;
      const deltaPct = (delta / totalH) * 100;
      workerPct = Math.max(5, Math.min(95, workerPct + deltaPct));
    }} />
    <div class="unassigned-section" style="flex: {100 - workerPct};">
      <UnassignedPool
        tasks={unassigned}
        {canManage}
        {focusedJobId}
        onAssign={assignTask}
      />
    </div>
  </div>
</div>

<style>
  .approved-header { padding: 14px 16px 10px; display: flex; align-items: center; gap: 10px; border-bottom: 3px solid #4ade80; flex-shrink: 0; }
  .col-indicator { width: 4px; height: 24px; border-radius: 2px; background: #4ade80; }
  .count { font-size: 12px; color: #999; margin-left: auto; }
  .approved-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .worker-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
  .worker-section { display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
  .unassigned-section { display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
</style>
