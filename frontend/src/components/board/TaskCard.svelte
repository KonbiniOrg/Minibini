<script>
  let { task, draggable = false } = $props();

  const STATUS_LABELS = {
    pending: 'Pending',
    in_progress: 'Active',
    blocked: 'Blocked',
  };

  function dotClass() {
    if (task.status === 'blocked') return 'dot-blocked';
    if (task.status === 'in_progress') return 'dot-in-progress';
    return 'dot-pending';
  }

  function labelClass() {
    if (task.status === 'blocked') return 'tsb-blocked';
    if (task.status === 'in_progress') return 'tsb-in-progress';
    return 'tsb-pending';
  }

  function isUrgent() {
    return task.status === 'blocked' && task.job_due_date && new Date(task.job_due_date) < new Date();
  }

  function deadlineLabel() {
    if (!task.job_due_date) return task.job_name;
    const due = new Date(task.job_due_date);
    const now = new Date();
    if (due < now) return `${task.job_name} · overdue`;
    return `${task.job_name} · ${due.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;
  }

  function handleDragStart(e) {
    e.dataTransfer.setData('text/plain', String(task.task_id));
    e.dataTransfer.effectAllowed = 'move';
  }
</script>

<div
  class="task-card"
  class:urgent={isUrgent()}
  draggable={draggable ? 'true' : 'false'}
  ondragstart={draggable ? handleDragStart : null}
  style="border-left-color: {task.accent_color || '#94a3b8'};"
  data-task-id={task.task_id}
  data-job-id={task.job_id}
>
  <span class="task-dot {dotClass()}"></span>
  <div class="task-info">
    <div class="task-name">{task.name}</div>
    <div class="task-job-label">{deadlineLabel()}</div>
  </div>
  {#if STATUS_LABELS[task.status]}
    <span class="task-status-badge {labelClass()}">{STATUS_LABELS[task.status]}</span>
  {/if}
</div>

<style>
  .task-card {
    background: #fff; border-radius: 7px; padding: 7px 8px 7px 12px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04); border-left: 4px solid #94a3b8;
    display: flex; align-items: center; gap: 6px;
    cursor: grab; user-select: none; transition: opacity 0.15s, box-shadow 0.15s;
  }
  .task-card:hover { box-shadow: 0 2px 6px rgba(0,0,0,0.08); }
  .task-card.urgent { background: #fff5f5; }
  .task-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .dot-pending { background: #cbd5e1; }
  .dot-in-progress { background: #3b82f6; box-shadow: 0 0 4px rgba(59,130,246,0.27); }
  .dot-blocked { background: #ef4444; box-shadow: 0 0 4px rgba(239,68,68,0.27); }
  .task-info { flex: 1; min-width: 0; }
  .task-name { font-size: 11px; font-weight: 500; color: #333; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .task-job-label { font-size: 9px; color: #999; }
  .task-status-badge { font-size: 8px; text-transform: uppercase; letter-spacing: 0.3px; font-weight: 700; flex-shrink: 0; }
  .tsb-pending { color: #94a3b8; }
  .tsb-in-progress { color: #3b82f6; }
  .tsb-blocked { color: #ef4444; }
</style>
