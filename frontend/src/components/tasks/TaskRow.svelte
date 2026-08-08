<script>
  // THE task row — one shared fragment for every task (tasks are one flat
  // level since the better-fees subtask removal, 2026-08).
  import TaskActivityIndicator from './TaskActivityIndicator.svelte';
  import {
    fmtMoney, fmtWorkerTime, taskTotalInfo, taskTotal, taskActual,
  } from '../../lib/taskTotals.js';

  let {
    task,
    // Position among the job's tasks, for the reorder arrows' disabled
    // state (the backend swap is job-scoped to match).
    taskIdx = 0,
    taskCount = 1,
    readonly = false,
    jobLocked = false,
    jobOnHold = false,
    canManage = false,
    showAssignee = true,
    showStatus = true,
    selectedTaskId = $bindable(null),
    onTaskClick = () => {},
    onAssignTask = () => {},
    onEditTask = null,
    onDeleteTask = null,
    onCancelTask = null,
    onAddMaterial = null,
    onReorder = null,
  } = $props();

  const TERMINAL = ['complete', 'cancelled'];
  const NON_DELETABLE = ['in_progress', 'complete'];
  const isTerminal = $derived(TERMINAL.includes(task.status));
  const canDelete = $derived(!NON_DELETABLE.includes(task.status));
  const canCancel = $derived(['pending', 'in_progress', 'blocked'].includes(task.status));
  // Serializer-computed editability (C1 matrix: pending open to all;
  // in_progress/blocked manager/PM/assignee). Absent field = older payload
  // shape — default open and let the server enforce.
  const canEditTask = $derived(task.can_edit ?? true);

  function isMaterialAwaitingStock(mat) {
    // Mirrors MaterialService.consume's stock check: only an inventory-item-
    // backed material can be short; a freeform one consumes unconditionally.
    return mat.consumption_state === 'pending'
      && mat.inventory_item != null
      && Number(mat.qty_on_hand) < Number(mat.quantity);
  }

  // Derived, never stored (same doctrine as is_amended): an in-progress
  // task with a pending understocked material refuses further bleps until
  // the stock arrives — surface that here instead of auto-setting the
  // human-owned `blocked` status.
  const awaitingMaterials = $derived(
    task.status === 'in_progress'
    && (task.materials || []).some(isMaterialAwaitingStock)
  );


  // The standalone Units column is gone — the unit rides inline beside the
  // qty values, like Est Time's "h" suffix. Hour-unit tasks show their Est
  // Qty like every other unit, even though it restates Est Time
  // (pair-filled) — the old duplicate-suppression exception read as missing
  // data (RM 2026-08-06).
  function withUnit(val) {
    if (val == null) return '-';
    return task.unit_label ? `${val} ${task.unit_label}` : `${val}`;
  }
</script>

<tr class="task-row">
  {#if !readonly && !jobLocked}
    <td class="move-cell">{#if !isTerminal}<input type="radio" name="move-target" value={task.task_id} bind:group={selectedTaskId}>{/if}</td>
  {/if}
  <td>
    <button type="button" class="link-btn" onclick={() => onTaskClick(task)}>{task.name}</button>
    {#if awaitingMaterials}<span class="badge-awaiting" title="A pending material isn't in stock — bleps are refused until it arrives">waiting on materials</span>{/if}
  </td>
  {#if showAssignee}<td>{task.assignee_name || ''} {#if !readonly && !isTerminal && canManage && !jobOnHold}<button type="button" class="small-btn" onclick={() => onAssignTask(task)}>assign</button>{/if}</td>{/if}
  <td class="text-right">{fmtWorkerTime(task.est_worker_time)}</td>
  {#if showStatus}<td>{#if task.invoice}<a class="badge-invoiced" href={`#/invoices/${task.invoice.id}`} title="Billed on this invoice">INVOICED</a>{:else}<TaskActivityIndicator {task} />{#if task.status === 'blocked' && task.blocked_reason}<br><span class="blocked-reason preserve-breaks">{task.blocked_reason}</span>{/if}{/if}</td>{/if}
  <td class="text-right">{withUnit(task.est_qty)}</td>
  <td class="text-right">{withUnit(taskActual(task))}</td>
  <td class="text-right">{fmtMoney(task.effective_rate)}</td>
  <td class="text-right" class:est-total={taskTotalInfo(task).isEstimate}>{fmtMoney(taskTotal(task))}</td>
  {#if !readonly && !jobLocked}
    <td class="actions-cell row-actions">
      {#if !isTerminal}
        {#if onEditTask && !jobOnHold && canEditTask}<button type="button" onclick={() => onEditTask(task)}>edit</button>{/if}
        {#if onDeleteTask && !jobOnHold && canDelete && !task.has_bleps}<button type="button" onclick={() => onDeleteTask(task)}>del</button>{/if}
        {#if onCancelTask && !jobOnHold && canCancel}<button type="button" onclick={() => onCancelTask(task)}>cancel</button>{/if}
        {#if onAddMaterial && !jobOnHold}<button type="button" onclick={() => onAddMaterial(task)}>+mat</button>{/if}
      {:else if onDeleteTask && !jobOnHold && canDelete && !task.has_bleps}
        <button type="button" onclick={() => onDeleteTask(task)}>del</button>
      {/if}
      {#if canManage && onReorder}
        <button type="button" onclick={() => onReorder(task.task_id, 'up')} disabled={taskIdx === 0}>&#9650;</button>
        <button type="button" onclick={() => onReorder(task.task_id, 'down')} disabled={taskIdx === taskCount - 1}>&#9660;</button>
      {/if}
    </td>
  {:else if !readonly}
    <td class="actions-cell row-actions"></td>
  {/if}
</tr>

<style>
  /* Rows ride the shared .data-table zebra stripe. */
  /* Headerless radio column — just wide enough for the radio button. */
  .move-cell { text-align: center; width: 24px; padding-left: 4px; padding-right: 4px; }
  .text-right { text-align: right; }
  td { padding: 6px 10px; vertical-align: top; }
  .est-total { color: #888; }

  .link-btn {
    background: none; border: none; padding: 0; margin: 0;
    color: #1d4ed8; cursor: pointer; font-size: inherit;
    text-decoration: underline; text-align: left;
  }
  .link-btn:hover { color: #1e40af; }
  .small-btn {
    font-size: 11px; padding: 1px 5px; margin-left: 4px;
    cursor: pointer; border: 1px solid #ccc; background: #fff; border-radius: 3px;
  }
  .small-btn:hover { background: #f0f0f0; }

  .badge-awaiting {
    display: inline-block;
    margin-left: 6px;
    padding: 1px 6px;
    font-size: 11px;
    border-radius: 3px;
    background: #fef3c7;
    border: 1px solid #d97706;
    color: #92400e;
    white-space: nowrap;
  }
  .blocked-reason { font-size: 11px; color: #991b1b; }
  .actions-cell { max-width: 12em; }
  /* .badge-invoiced and .row-actions come from app.css. */
</style>
