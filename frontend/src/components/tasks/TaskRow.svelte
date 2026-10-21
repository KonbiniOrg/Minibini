<script>
  // THE task row — one shared fragment for every task (tasks are one flat
  // level since the better-fees subtask removal, 2026-08).
  import TaskActivityIndicator from './TaskActivityIndicator.svelte';
  import DragHandle from '../DragHandle.svelte';
  import {
    fmtMoney, fmtWorkerTime, taskTotalInfo, taskTotal, taskActual,
  } from '../../lib/taskTotals.js';

  let {
    task,
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
    // Drag-to-reorder (issue #513): the task group's sortable handleRef,
    // passed only when this row may be dragged (TaskTree decides). Null =
    // no handle.
    dragHandle = null,
    // Bundle-selection checkbox (Task 3) — off by default so every other
    // consumer of this shared row renders unchanged.
    bundleMode = false,
    bundleAtom = null,
    bundleChecked = false,
    onToggleBundle = null,
    // claimed_by_current chip text (Tasks-page CO lens): the estimate lens's
    // wording is the default so every other surface renders unchanged.
    bundleClaimedLabel = 'estimated',
    bundleClaimedTitle = 'Already on the draft estimate',
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

  // A claimed_by_other atom is claimed on one of two lenses: a change-order
  // add line or another estimate — never both. CO wins the branch since
  // it's the more specific claim (mirrors EstimateEditView's unselectableNote).
  function bundleClaimNote(atom) {
    if (atom.claiming_change_order_number) {
      return `Claimed by change order ${atom.claiming_change_order_number}`;
    }
    return `Claimed by estimate ${atom.claiming_estimate_number || ''}`.trim();
  }

  // Same CO-wins-then-estimate branch as bundleClaimNote, just the short
  // chip label instead of the full hover sentence — "Est"/"CO" mirror the
  // table's own "Est Qty"/"Est Time" header shorthand.
  function bundleClaimLabel(atom) {
    return atom.claiming_change_order_number ? 'on CO' : 'on est';
  }
</script>

<tr class="task-row">
  {#if bundleMode}
    <td class="bundle-cell">
      {#if bundleAtom?.state === 'available'}
        <input type="checkbox" checked={bundleChecked}
               onchange={onToggleBundle}
               aria-label={`Select ${task.name} for bundling`}>
      {:else if bundleAtom?.state === 'claimed_by_current'}
        <span class="bundle-claimed" title={bundleClaimedTitle}>{bundleClaimedLabel}</span>
      {:else if bundleAtom?.state === 'claimed_by_other'}
        <span class="bundle-claimed" title={bundleClaimNote(bundleAtom)}>{bundleClaimLabel(bundleAtom)}</span>
      {/if}
    </td>
  {/if}
  {#if !readonly && !jobLocked}
    <td class="move-cell">{#if !isTerminal}<input type="radio" name="move-target" value={task.task_id} bind:group={selectedTaskId}>{/if}</td>
  {/if}
  <td>
    <!-- Handle beside the name, not inline with it: a long name wraps next to the
         handle instead of dropping below it (the name button is one unbreakable box). -->
    <div class="name-cell">
      {#if dragHandle}<DragHandle attach={dragHandle} label={`Drag to reorder ${task.name}`} />{/if}
      <div class="name-main">
        <button type="button" class="link-btn" onclick={() => onTaskClick(task)}>{task.name}</button>
        {#if awaitingMaterials}<span class="badge-awaiting" title="A pending material isn't in stock — bleps are refused until it arrives">Waiting on materials</span>{/if}
      </div>
    </div>
  </td>
  {#if showAssignee}<td class="assignee-cell">{task.assignee_name || ''} {#if !readonly && !isTerminal && canManage && !jobOnHold}<button type="button" class="small-btn" onclick={() => onAssignTask(task)}>assign</button>{/if}</td>{/if}
  <td class="text-right figure">{fmtWorkerTime(task.est_worker_time)}</td>
  {#if showStatus}<td>{#if task.invoice}<a class="badge-invoiced" href={`#/invoices/${task.invoice.id}`} title="Billed on this invoice">Invoiced</a>{:else}<TaskActivityIndicator {task} />{#if task.status === 'blocked' && task.blocked_reason}<br><span class="blocked-reason preserve-breaks">{task.blocked_reason}</span>{/if}{/if}</td>{/if}
  <td class="text-right figure">{withUnit(task.est_qty)}</td>
  <td class="text-right figure">{withUnit(taskActual(task))}</td>
  <td class="text-right figure">{fmtMoney(task.effective_rate)}</td>
  <td class="text-right figure" class:est-total={taskTotalInfo(task).isEstimate}>{fmtMoney(taskTotal(task))}</td>
  {#if !readonly && !jobLocked}
    <td class="actions-cell row-actions">
      {#if !isTerminal}
        {#if onEditTask && !jobOnHold && canEditTask}<button type="button" onclick={() => onEditTask(task)}>edit</button>{/if}
        {#if onDeleteTask && !jobOnHold && canDelete && !task.has_bleps}<button type="button" class="danger" onclick={() => onDeleteTask(task)}>del</button>{/if}
        {#if onCancelTask && !jobOnHold && canCancel}<button type="button" onclick={() => onCancelTask(task)}>cancel</button>{/if}
        {#if onAddMaterial && !jobOnHold}<button type="button" onclick={() => onAddMaterial(task)}>+mat</button>{/if}
      {:else if onDeleteTask && !jobOnHold && canDelete && !task.has_bleps}
        <button type="button" class="danger" onclick={() => onDeleteTask(task)}>del</button>
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
  /* Bundle-selection checkbox column (Task 3) — same footprint as move-cell. */
  .bundle-cell { text-align: center; width: 24px; padding-left: 4px; padding-right: 4px; }
  .bundle-claimed { font-size: var(--text-sm); color: var(--text-muted); font-style: italic; }
  .text-right { text-align: right; }
  td { padding: 6px 10px; vertical-align: top; }
  .name-cell { display: flex; align-items: flex-start; }
  /* Assignee and its "assign" button share one line; Name gives up the width. */
  .assignee-cell { white-space: nowrap; }
  .name-main { flex: 1; min-width: 0; }
  .est-total { color: var(--text-muted); }

  .link-btn {
    background: none; border: none; padding: 0; margin: 0;
    color: #1d4ed8; cursor: pointer; font: inherit;  /* the table's font, not the button default */
    text-decoration: underline; text-align: left;
  }
  .link-btn:hover { color: #1e40af; }
  /* Buttons (incl. .small-btn) are styled by TaskTree's table-wide button rule. */

  .badge-awaiting {
    display: inline-block;
    margin-left: 6px;
    /* A tag: outlined pill (shadcn table-badge style) — the round shape sets it apart from buttons. */
    padding: 0 8px;
    font-size: var(--text-sm);
    border-radius: 999px;
    background: #fef3c7;
    border: 1px solid #d97706;
    color: #92400e;
    white-space: nowrap;
  }
  .blocked-reason { font-size: var(--text-sm); color: #991b1b; }
  /* .badge-invoiced and .row-actions come from app.css. */
</style>
