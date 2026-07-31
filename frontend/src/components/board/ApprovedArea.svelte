<script>
  import JobChipStrip from './JobChipStrip.svelte';
  import WorkerColumns from './WorkerColumns.svelte';
  import UnassignedPool from './UnassignedPool.svelte';
  import ResizeHandle from './ResizeHandle.svelte';
  import WorkerTimePromptModal from './WorkerTimePromptModal.svelte';
  import NewJobButton from './NewJobButton.svelte';
  import { api } from '../../lib/api.js';

  let { data = {}, canManage = false, onUpdate = () => {} } = $props();
  let focusedJobIds = $state([]);
  let workerPct = $state(50); // percentage of worker-area given to worker section

  let workers = $state([]);
  let unassigned = $state([]);
  let availableWorkers = $state([]);
  let addedWorkers = $state([]);

  // Holds a pending drop while the worker-time prompt is open:
  // {taskId, targetWorkerId, insertIndex, taskName}
  let workerTimeModal = $state(null);

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

  // Locate a task without mutating any column — used to peek at its
  // estimated worker time before committing an optimistic drop.
  function findTask(taskId) {
    const inU = unassigned.find(t => t.task_id === taskId);
    if (inU) return inU;
    for (const w of [...workers, ...addedWorkers]) {
      const t = w.tasks.find(t => t.task_id === taskId);
      if (t) return t;
    }
    return null;
  }

  // Gatekeeper: a task with no estimated worker time can't be scheduled,
  // so dragging one onto a worker interrupts with a duration prompt before
  // the drop is committed. Unassigning and reordering pass straight through.
  function assignTask(taskId, targetWorkerId, insertIndex = -1) {
    if (targetWorkerId !== null) {
      const task = findTask(taskId);
      if (task && !task.est_worker_time) {
        workerTimeModal = {
          taskId, targetWorkerId, insertIndex, taskName: task.name,
        };
        return;
      }
    }
    doAssign(taskId, targetWorkerId, insertIndex);
  }

  function submitWorkerTime(estWorkerTimeISO) {
    const pending = workerTimeModal;
    workerTimeModal = null;
    if (pending) {
      doAssign(
        pending.taskId, pending.targetWorkerId,
        pending.insertIndex, estWorkerTimeISO,
      );
    }
  }

  async function doAssign(taskId, targetWorkerId, insertIndex = -1,
                          estWorkerTimeISO = null) {
    // Find the task object and remove from its current location
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
          // If reordering within same column, adjust insertIndex for the removal
          if (w.user.id === targetWorkerId && insertIndex > tIdx) {
            insertIndex--;
          }
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
          if (w.user.id === targetWorkerId && insertIndex > tIdx) {
            insertIndex--;
          }
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
        task = {
          ...task, assignee_id: targetWorkerId,
          ...(estWorkerTimeISO ? { est_worker_time: estWorkerTimeISO } : {}),
        };

        // Insert at specified position or append
        if (insertIndex >= 0 && insertIndex <= targetWorker.tasks.length) {
          targetWorker.tasks = [
            ...targetWorker.tasks.slice(0, insertIndex),
            task,
            ...targetWorker.tasks.slice(insertIndex),
          ];
        } else {
          targetWorker.tasks = [...targetWorker.tasks, task];
        }

        // Renumber worker_queue for all tasks in this column
        targetWorker.tasks.forEach((t, i) => {
          t.worker_queue = i + 1;
        });
        // Re-read task reference after renumbering
        task = targetWorker.tasks.find(t => t.task_id === taskId);
      }
    }

    // Trigger reactivity
    workers = [...workers];
    addedWorkers = [...addedWorkers];

    // Fire API calls in background
    try {
      if (targetWorkerId !== null) {
        // Assign (handles assignee change + initial queue position)
        const assignBody = {
          assignee: targetWorkerId,
          worker_queue: task.worker_queue,
        };
        if (estWorkerTimeISO) assignBody.est_worker_time = estWorkerTimeISO;
        const resp = await api.post(`/api/tasks/${taskId}/assign/`, assignBody);
        if (resp && resp.needs_worker_time) {
          // Stale board data — the task actually has no estimate. Revert
          // the optimistic drop by refreshing from the server.
          onUpdate();
          return;
        }

        // Reorder the full column to persist the exact order
        const targetWorker = workers.find(w => w.user.id === targetWorkerId)
          || addedWorkers.find(w => w.user.id === targetWorkerId);
        if (targetWorker) {
          const orderedIds = targetWorker.tasks.map(t => t.task_id);
          await api.post('/api/tasks/reorder/', { task_ids: orderedIds });
        }
      } else {
        await api.post(`/api/tasks/${taskId}/assign/`, {
          assignee: null,
          worker_queue: null,
        });
      }
    } catch (err) {
      console.error('Failed to assign task:', err);
    }
  }
</script>

<div class="approved-header">
  <strong>In Progress</strong>
  <span class="count">{data.jobs?.length || 0}</span>
  <NewJobButton />
</div>
<div class="approved-content">
  <JobChipStrip jobs={data.jobs || []} bind:focusedJobIds />

  <div class="worker-area" id="workerArea">
    <div class="worker-section" style="flex: {workerPct};">
      <WorkerColumns
        workers={allWorkers}
        {canManage}
        {focusedJobIds}
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
        {focusedJobIds}
        onAssign={assignTask}
      />
    </div>
  </div>
</div>

<WorkerTimePromptModal
  open={workerTimeModal !== null}
  taskName={workerTimeModal?.taskName || ''}
  onSubmit={submitWorkerTime}
  onCancel={() => { workerTimeModal = null; }}
/>

<style>
  .approved-header { position: relative; padding: 14px 16px 10px; display: flex; align-items: center; justify-content: center; gap: 10px; border-bottom: 3px solid #4ade80; flex-shrink: 0; }
  .count { font-size: 12px; color: #999; }
  .approved-content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
  .worker-area { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
  .worker-section { display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
  .unassigned-section { display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
</style>
