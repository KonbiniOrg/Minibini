<script>
  let { task, draggable = false } = $props();

  const STATUS_LABELS = {
    pending: 'Pending',
    in_progress: 'Active',
    blocked: 'Blocked',
  };

  let popupVisible = $state(false);
  let popupPos = $state({ anchor: 'below', y: 0, left: 0 });
  let showTimer = null;
  let hideTimer = null;

  function scheduleShow(el) {
    clearTimeout(hideTimer); hideTimer = null;
    clearTimeout(showTimer); showTimer = null;
    if (popupVisible) return;
    showTimer = setTimeout(() => {
      const rect = el.getBoundingClientRect();
      const popupWidth = 260;
      const popupHeightEst = 100;
      let left = rect.left;
      if (left + popupWidth > window.innerWidth - 8) {
        left = Math.max(8, window.innerWidth - popupWidth - 8);
      }
      // Anchor to card's bottom edge (below) or top edge (above).
      // Using bottom-anchor when flipping above ensures the gap stays
      // 4px regardless of the popup's actual height.
      if (rect.bottom + 4 + popupHeightEst > window.innerHeight - 8) {
        popupPos = { anchor: 'above', y: window.innerHeight - rect.top + 4, left };
      } else {
        popupPos = { anchor: 'below', y: rect.bottom + 4, left };
      }
      popupVisible = true;
    }, 300);
  }

  function scheduleHide() {
    clearTimeout(showTimer); showTimer = null;
    hideTimer = setTimeout(() => { popupVisible = false; }, 100);
  }

  function cancelHide() {
    clearTimeout(hideTimer); hideTimer = null;
  }

  $effect(() => () => {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
  });

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

  function popupDeadlineText() {
    if (!task.job_due_date) return '';
    const due = new Date(task.job_due_date);
    const now = new Date();
    const fmt = due.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    if (due < now) return `Overdue — was ${fmt}`;
    return `Due ${fmt}`;
  }

  function handleDragStart(e) {
    // Hide popup immediately when dragging starts
    clearTimeout(showTimer); showTimer = null;
    clearTimeout(hideTimer); hideTimer = null;
    popupVisible = false;
    e.dataTransfer.setData('text/plain', String(task.task_id));
    e.dataTransfer.effectAllowed = 'move';
  }
</script>

<div
  class="task-card"
  class:urgent={isUrgent()}
  draggable={draggable ? 'true' : 'false'}
  ondragstart={draggable ? handleDragStart : null}
  onmouseenter={(e) => scheduleShow(e.currentTarget)}
  onmouseleave={scheduleHide}
  data-task-id={task.task_id}
  data-job-id={task.job_id}
>
  <div class="task-border" style="background: {task.accent_color || '#94a3b8'};"></div>
  <div class="task-body">
    <span class="task-dot {dotClass()}"></span>
    <div class="task-info">
      <div class="task-name">{task.name}</div>
      <div class="task-job-label">{deadlineLabel()}</div>
      {#if task.status === 'blocked' && task.blocked_reason}
        <div class="task-blocked-reason">{task.blocked_reason}</div>
      {/if}
    </div>
    {#if STATUS_LABELS[task.status]}
      <span class="task-status-badge {labelClass()}">{STATUS_LABELS[task.status]}</span>
    {/if}
  </div>
</div>

{#if popupVisible}
  <a
    class="task-popup"
    href="#/jobs/{task.job_id}/tasks/{task.task_id}"
    style="{popupPos.anchor === 'above' ? 'bottom' : 'top'}: {popupPos.y}px; left: {popupPos.left}px;"
    onmouseenter={cancelHide}
    onmouseleave={scheduleHide}
  >
    <div class="tp-border" style="background: {task.accent_color || '#94a3b8'};"></div>
    <div class="tp-body">
      <div class="tp-head">
        <div class="tp-name">{task.name}</div>
        {#if STATUS_LABELS[task.status]}
          <span class="tp-status {labelClass()}">{STATUS_LABELS[task.status]}</span>
        {/if}
      </div>
      {#if task.status === 'blocked' && task.blocked_reason}
        <div class="tp-blocked-reason">{task.blocked_reason}</div>
      {/if}
      {#if popupDeadlineText()}
        <div class="tp-deadline">{popupDeadlineText()}</div>
      {/if}
    </div>
  </a>
{/if}

<style>
  .task-card {
    background: #fff; border-radius: 7px; overflow: hidden;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    display: flex;
    cursor: grab; user-select: none; transition: opacity 0.15s, box-shadow 0.15s;
  }
  .task-card:hover { box-shadow: 0 2px 6px rgba(0,0,0,0.08); }
  .task-card.urgent { background: #fff5f5; }
  .task-border { width: 8px; flex-shrink: 0; border-radius: 7px 0 0 7px; }
  .task-body { flex: 1; min-width: 0; padding: 7px 8px; display: flex; align-items: center; gap: 6px; }
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

  .task-popup {
    position: fixed;
    width: 260px;
    z-index: 1000;
    background: #fff;
    border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.15);
    display: flex;
    overflow: hidden;
    text-decoration: none;
    color: inherit;
  }
  .tp-border { width: 8px; flex-shrink: 0; border-radius: 8px 0 0 8px; }
  .tp-body { flex: 1; padding: 10px 12px; min-width: 0; }
  .tp-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 4px; }
  .tp-name { font-size: 13px; font-weight: 600; color: #333; flex: 1; line-height: 1.3; }
  .tp-status { font-size: 9px; text-transform: uppercase; letter-spacing: 0.3px; font-weight: 700; flex-shrink: 0; }
  .tp-deadline { font-size: 11px; color: #888; }
  .task-blocked-reason { font-size: 9px; color: #ef4444; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tp-blocked-reason { font-size: 11px; color: #ef4444; margin-bottom: 2px; }
</style>
