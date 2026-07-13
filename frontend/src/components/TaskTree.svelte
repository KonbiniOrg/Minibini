<script>
  import { link } from 'svelte-spa-router';
  import TaskActivityIndicator from './tasks/TaskActivityIndicator.svelte';
  import MaterialRow from './materials/MaterialRow.svelte';

  let {
    tasks = [],
    jobMaterials = [],
    readonly = false,
    jobLocked = false,
    // on_hold freezes plan edits (Set pricing / edit / restock) but NOT
    // procurement (Order, receipts, attach) — mirror of the service guards.
    jobOnHold = false,
    canManage = false,
    showStatus = true,
    showAssignee = true,
    // Task-op AND material-op callbacks default to NULL and each button
    // renders only when its callback was actually wired. A surface that
    // omits a callback gets a passive tree — never a dead button bound to
    // a no-op default. Every current surface wires the FULL material
    // action set (the old page-based venue rule is gone); TaskDetailPage's
    // subtask tree stays passive for task ops only (edit/del/cancel live
    // on the subtask's own page).
    onEditTask = null,
    onDeleteTask = null,
    onAddMaterial = null,
    onEditMaterial = null,
    onAddSubtask = null,
    onReorder = null,
    onTaskClick = () => {},
    onAssignTask = () => {},
    onCancelTask = null,
    onConsumeMaterial = null,
    onRestockMaterial = null,
    onDrawMoreMaterial = null,
    onMoveMaterial = null,
    onOrderMaterial = null,
    onMarkOnHand = null,
    onAttachExpense = null,
    expenses = [],
    onEditExpense = () => {},
    fees = [],
    onEditFee = () => {},
    selectedTaskId = $bindable(null),
  } = $props();

  // Expenses that created a material show nested under it; material-less
  // expenses (service costs / stock receipts) show at job level.
  const expenseByMaterial = $derived.by(() => {
    const map = {};
    for (const e of (expenses || [])) {
      if (e.material) map[e.material] = e;
    }
    return map;
  });
  const looseExpenses = $derived((expenses || []).filter((e) => !e.material));

  function taskTotalInfo(task) {
    // Prefer the live computed_charge (driven by actuals: bleps for elapsed_time,
    // actual_qty for entered_qty). When actuals are absent
    // the computed charge is 0 — fall back to est_qty * effective_rate as the
    // estimated total, marked so the UI can render it in grey.
    const actual = Number(task.computed_charge) || 0;
    if (actual > 0) return { value: actual, isEstimate: false };
    const est = (Number(task.est_qty) || 0) * (Number(task.effective_rate) || 0);
    if (est > 0) return { value: est, isEstimate: true };
    return { value: 0, isEstimate: false };
  }

  function taskTotal(task) {
    return taskTotalInfo(task).value;
  }

  function taskActual(task) {
    // ELAPSED_TIME → hours from bleps. ENTERED_QTY → worker-entered qty.
    // Unset/other → no actual to display.
    if (task.scheme_algorithm === 'elapsed_time') {
      const h = Number(task.actual_hours) || 0;
      return h > 0 ? h : null;
    }
    if (task.scheme_algorithm === 'entered_qty') {
      return task.actual_qty != null && task.actual_qty !== '' ? task.actual_qty : null;
    }
    return null;
  }

  function materialTotal(mat) {
    const qty = Number(mat.quantity) || 0;
    const price = Number(mat.sell_price) || 0;
    return qty * price;
  }

  function feeTotal(fee) {
    return (Number(fee.quantity) || 0) * (Number(fee.unit_rate) || 0);
  }

  const TERMINAL = ['complete', 'cancelled'];
  const NON_DELETABLE = ['in_progress', 'complete'];
  function isTerminal(task) { return TERMINAL.includes(task.status); }
  function canDelete(task) { return !NON_DELETABLE.includes(task.status); }
  function canCancel(task) { return ['pending', 'in_progress', 'blocked'].includes(task.status); }
  // Serializer-computed editability (C1 matrix: pending open to all;
  // in_progress/blocked manager/PM/assignee). Absent field = older payload
  // shape — default open and let the server enforce.
  function canEditTask(task) { return task.can_edit ?? true; }

  function taskWithMaterialsTotal(task) {
    let total = taskTotal(task);
    for (const m of (task.materials || [])) {
      total += materialTotal(m);
    }
    return total;
  }

  const grandTotal = $derived.by(() => {
    let total = 0;
    for (const t of tasks) {
      total += taskWithMaterialsTotal(t);
      for (const sub of (t.subtasks || [])) {
        total += taskWithMaterialsTotal(sub);
      }
    }
    for (const m of (jobMaterials || [])) {
      total += materialTotal(m);
    }
    for (const f of (fees || [])) {
      total += feeTotal(f);
    }
    return total;
  });

  function fmt(n) {
    return n ? `$${Number(n).toFixed(2)}` : '-';
  }

  function fmtWorkerTime(value) {
    // Server returns DurationField as either "HH:MM:SS" / "DD HH:MM:SS"
    // or ISO 8601 ("PT1H30M"). Render as "Hh Mm" or "Mm" for compactness.
    if (!value) return '-';
    const str = String(value);
    const iso = str.match(/^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/);
    if (iso) {
      const days = parseInt(iso[1] || '0', 10);
      const h = parseInt(iso[2] || '0', 10) + days * 24;
      const m = parseInt(iso[3] || '0', 10);
      if (h && m) return `${h}h ${m}m`;
      if (h) return `${h}h`;
      if (m) return `${m}m`;
      return '-';
    }
    const hms = str.match(/^(?:(\d+) )?(\d+):(\d+):(\d+)/);
    if (hms) {
      const days = parseInt(hms[1] || '0', 10);
      const h = parseInt(hms[2], 10) + days * 24;
      const m = parseInt(hms[3], 10);
      if (h && m) return `${h}h ${m}m`;
      if (h) return `${h}h`;
      if (m) return `${m}m`;
      return '-';
    }
    return str;
  }

  const colCount = $derived(8 + (showAssignee ? 1 : 0) + (showStatus ? 1 : 0) + (readonly ? 0 : 1) + (readonly || jobLocked ? 0 : 1));

  function isMaterialAwaitingStock(mat) {
    // Mirrors MaterialService.consume's stock check: only an inventory-item-
    // backed material can be short; a freeform one consumes unconditionally.
    return mat.consumption_state === 'pending'
      && mat.inventory_item != null
      && Number(mat.qty_on_hand) < Number(mat.quantity);
  }

  function taskAwaitingMaterials(task) {
    // Derived, never stored (same doctrine as is_amended): an in-progress
    // task with a pending understocked material refuses further bleps until
    // the stock arrives — surface that here instead of auto-setting the
    // human-owned `blocked` status.
    return task.status === 'in_progress'
      && (task.materials || []).some(isMaterialAwaitingStock);
  }

  // Material row rendering (chips, tombstones, the full action set) lives in
  // the shared MaterialRow component — the same fragment every surface uses.
  const materialCallbacks = $derived({
    onMoveMaterial, onEditMaterial, onConsumeMaterial, onRestockMaterial,
    onDrawMoreMaterial, onOrderMaterial, onMarkOnHand, onAttachExpense,
  });
</script>

{#snippet expenseRow(exp, deep)}
  <tr class="expense-row">
    {#if !readonly && !jobLocked}<td class="move-cell"></td>{/if}
    <td class={deep ? 'indent-2' : 'indent'}>
      <span class="expense-marker">$</span> {exp.description || '(expense)'}
      {#if exp.purchased_by_name}<small class="dim">· {exp.purchased_by_name}</small>{/if}
    </td>
    {#if showAssignee}<td></td>{/if}
    <td></td>
    {#if showStatus}<td>{#if exp.invoice}{@render invoicedLink(exp.invoice)}{/if}</td>{/if}
    <td class="text-right">-</td>
    <td class="text-right">-</td>
    <td class="text-right">-</td>
    <td></td>
    <td></td>
    <td class="text-right">{fmt(exp.amount)}</td>
    {#if !readonly}
      <td class="actions-cell row-actions">
        <button type="button" onclick={() => onEditExpense(exp)}>edit</button>
      </td>
    {/if}
  </tr>
{/snippet}

{#snippet invoicedLink(inv)}
  <a class="badge-invoiced" href={`#/invoices/${inv.id}`} use:link
     title="Billed on this invoice">INVOICED</a>
{/snippet}

<table class="data-table task-tree-table">
  <thead>
    <tr>
      {#if !readonly && !jobLocked}<th>Move Material</th>{/if}
      <th>Name</th>
      {#if showAssignee}<th>Assignee</th>{/if}
      <th class="text-right">Scheduled Time</th>
      {#if showStatus}<th>Status</th>{/if}
      <th class="text-right">Est Qty</th>
      <th class="text-right">Actual</th>
      <th class="text-right">Units</th>
      <th class="text-right">Unit Cost</th>
      <th class="text-right">Sell Price</th>
      <th class="text-right"><span class="est-label">(Est)</span><br>Total</th>
      {#if !readonly}<th>Actions</th>{/if}
    </tr>
  </thead>
  <tbody>
    {#each tasks as task, taskIdx}
      <!-- Task row -->
      <tr class="task-row">
        {#if !readonly && !jobLocked}
          <td class="move-cell">{#if !isTerminal(task)}<input type="radio" name="move-target" value={task.task_id} bind:group={selectedTaskId}>{/if}</td>
        {/if}
        <td>
          <button type="button" class="link-btn" onclick={() => onTaskClick(task)}>{task.name}</button>
          {#if taskAwaitingMaterials(task)}<span class="badge-awaiting" title="A pending material isn't in stock — bleps are refused until it arrives">waiting on materials</span>{/if}
        </td>
        {#if showAssignee}<td>{task.assignee_name || 'Unassigned'} {#if !readonly && !isTerminal(task) && canManage && !jobOnHold}<button type="button" class="small-btn" onclick={() => onAssignTask(task)}>assign</button>{/if}</td>{/if}
        <td class="text-right">{fmtWorkerTime(task.est_worker_time)}</td>
        {#if showStatus}<td>{#if task.invoice}{@render invoicedLink(task.invoice)}{:else}<TaskActivityIndicator {task} />{#if task.status === 'blocked' && task.blocked_reason}<br><span class="blocked-reason preserve-breaks">{task.blocked_reason}</span>{/if}{/if}</td>{/if}
        <td class="text-right">{task.est_qty ?? '-'}</td>
        <td class="text-right">{taskActual(task) ?? '-'}</td>
        <td class="text-right">{task.scheme_unit_label || '-'}</td>
        <td class="text-right">-</td>
        <td class="text-right">{fmt(task.effective_rate)}</td>
        <td class="text-right" class:est-total={taskTotalInfo(task).isEstimate}>{fmt(taskTotal(task))}</td>
        {#if !readonly && !jobLocked}
          <td class="actions-cell row-actions">
            {#if !isTerminal(task)}
              {#if onEditTask && !jobOnHold && canEditTask(task)}<button type="button" onclick={() => onEditTask(task)}>edit</button>{/if}
              {#if onDeleteTask && !jobOnHold && canDelete(task) && !task.has_bleps}<button type="button" onclick={() => onDeleteTask(task)}>del</button>{/if}
              {#if onCancelTask && !jobOnHold && canCancel(task)}<button type="button" onclick={() => onCancelTask(task)}>cancel</button>{/if}
              {#if onAddMaterial && !jobOnHold}<button type="button" onclick={() => onAddMaterial(task)}>+mat</button>{/if}
              {#if onAddSubtask && !jobOnHold}<button type="button" onclick={() => onAddSubtask(task)}>+sub</button>{/if}
            {:else if onDeleteTask && !jobOnHold && canDelete(task) && !task.has_bleps}
              <button type="button" onclick={() => onDeleteTask(task)}>del</button>
            {/if}
            {#if canManage && onReorder}
              <button type="button" onclick={() => onReorder(task.task_id, 'up')} disabled={taskIdx === 0}>&#9650;</button>
              <button type="button" onclick={() => onReorder(task.task_id, 'down')} disabled={taskIdx === tasks.length - 1}>&#9660;</button>
            {/if}
          </td>
        {:else if !readonly}
          <td class="actions-cell row-actions"></td>
        {/if}
      </tr>

      <!-- Materials for this task -->
      {#each (task.materials || []) as mat}
        <MaterialRow
          material={mat} ownerTask={task} ownerTerminal={isTerminal(task)}
          indentClass="indent" {showAssignee} {showStatus}
          {readonly} {jobLocked} {jobOnHold} {selectedTaskId}
          {...materialCallbacks}
        />
      {/each}

      <!-- Subtasks for this task -->
      {#each (task.subtasks || []) as sub}
        <tr class="subtask-row">
          {#if !readonly && !jobLocked}
            <td class="move-cell">{#if !isTerminal(sub)}<input type="radio" name="move-target" value={sub.task_id} bind:group={selectedTaskId}>{/if}</td>
          {/if}
          <td class="indent">
            <button type="button" class="link-btn" onclick={() => onTaskClick(sub)}>{sub.name}</button>
          </td>
          {#if showAssignee}<td>{sub.assignee_name || 'Unassigned'} {#if !readonly && !isTerminal(sub) && canManage && !jobOnHold}<button type="button" class="small-btn" onclick={() => onAssignTask(sub)}>assign</button>{/if}</td>{/if}
          <td class="text-right">{fmtWorkerTime(sub.est_worker_time)}</td>
          {#if showStatus}<td>{#if sub.invoice}{@render invoicedLink(sub.invoice)}{:else}<TaskActivityIndicator task={sub} />{#if sub.status === 'blocked' && sub.blocked_reason}<br><span class="blocked-reason preserve-breaks">{sub.blocked_reason}</span>{/if}{/if}</td>{/if}
          <td class="text-right">{sub.est_qty ?? '-'}</td>
          <td class="text-right">{taskActual(sub) ?? '-'}</td>
          <td class="text-right">{sub.scheme_unit_label || '-'}</td>
          <td class="text-right">-</td>
          <td class="text-right">{fmt(sub.effective_rate)}</td>
          <td class="text-right" class:est-total={taskTotalInfo(sub).isEstimate}>{fmt(taskTotal(sub))}</td>
          {#if !readonly && !jobLocked}
            <td class="actions-cell row-actions">
              {#if !isTerminal(sub)}
                {#if onEditTask && !jobOnHold && canEditTask(sub)}<button type="button" onclick={() => onEditTask(sub)}>edit</button>{/if}
                {#if onDeleteTask && !jobOnHold && canDelete(sub) && !sub.has_bleps}<button type="button" onclick={() => onDeleteTask(sub)}>del</button>{/if}
                {#if onCancelTask && !jobOnHold && canCancel(sub)}<button type="button" onclick={() => onCancelTask(sub)}>cancel</button>{/if}
                {#if onAddMaterial && !jobOnHold}<button type="button" onclick={() => onAddMaterial(sub)}>+mat</button>{/if}
              {:else if onDeleteTask && !jobOnHold && canDelete(sub) && !sub.has_bleps}
                <button type="button" onclick={() => onDeleteTask(sub)}>del</button>
              {/if}
            </td>
          {:else if !readonly}
            <td class="actions-cell row-actions"></td>
          {/if}
        </tr>

        <!-- Materials for this subtask -->
        {#each (sub.materials || []) as mat}
          <MaterialRow
            material={mat} ownerTask={sub} ownerTerminal={isTerminal(sub)}
            indentClass="indent-2" {showAssignee} {showStatus}
            {readonly} {jobLocked} {jobOnHold} {selectedTaskId}
            {...materialCallbacks}
          />
        {/each}
      {/each}
    {/each}
    {#if jobMaterials && jobMaterials.length}
      <tr class="job-materials-header">
        <td colspan={colCount}><strong>Materials (no task)</strong></td>
      </tr>
      {#each jobMaterials as mat}
        <MaterialRow
          material={mat} ownerTask={null}
          indentClass="indent" {showAssignee} {showStatus}
          {readonly} {jobLocked} {jobOnHold} {selectedTaskId}
          {...materialCallbacks}
        />
        {#if expenseByMaterial[mat.material_id]}
          {@render expenseRow(expenseByMaterial[mat.material_id], true)}
        {/if}
      {/each}
    {/if}

    {#if looseExpenses.length}
      <tr class="job-materials-header">
        <td colspan={colCount}><strong>Expenses</strong></td>
      </tr>
      {#each looseExpenses as exp (exp.id)}
        {@render expenseRow(exp, false)}
      {/each}
    {/if}

    {#if fees && fees.length}
      <tr class="job-materials-header">
        <td colspan={colCount}><strong>Fees</strong></td>
      </tr>
      {#each fees as fee (fee.fee_id)}
        <tr class="fee-row">
          {#if !readonly && !jobLocked}<td class="move-cell"></td>{/if}
          <td class="indent"><span class="fee-marker">$</span> {fee.description || '(fee)'}</td>
          {#if showAssignee}<td></td>{/if}
          <td></td>
          {#if showStatus}<td>{#if fee.invoice}{@render invoicedLink(fee.invoice)}{/if}</td>{/if}
          <td class="text-right">{fee.quantity ?? '-'}</td>
          <td class="text-right">-</td>
          <td class="text-right">-</td>
          <td class="text-right">-</td>
          <td class="text-right">{fmt(fee.unit_rate)}</td>
          <td class="text-right">{fmt(feeTotal(fee))}</td>
          {#if !readonly}
            <td class="actions-cell row-actions">{#if !jobLocked}<button type="button" onclick={() => onEditFee(fee)}>edit</button>{/if}</td>
          {/if}
        </tr>
      {/each}
    {/if}
  </tbody>
  <tfoot>
    <tr class="grand-total-row">
      <td colspan={colCount - 1} class="text-right"><strong>Grand Total</strong></td>
      <td class="text-right"><strong>{fmt(grandTotal)}</strong></td>
    </tr>
  </tfoot>
</table>

<style>
  /* Base + green header come from the global .data-table class; just tighten padding. */
  .task-tree-table th { padding: 8px 10px; }
  .task-tree-table td { padding: 6px 10px; vertical-align: top; }
  .text-right { text-align: right; }
  .est-label { color: #888; font-size: 11px; font-weight: normal; }
  .est-total { color: #888; }
  .dim { color: #888; font-size: 13px; }
  .indent { padding-left: 28px; }
  .indent-2 { padding-left: 48px; }
  .move-cell { text-align: center; width: 40px; }
  /* Fees are billable but not a task/material — tint them so they read distinctly. */
  .fee-row { background: #f3e8ff; }
  .fee-marker { color: #9333ea; font-weight: bold; margin-right: 4px; }
  /* .badge-invoiced comes from app.css. */

  /* Top-level task rows use the shared .data-table zebra stripe.
     Material rows (background, chips, tombstones) style themselves in the
     shared MaterialRow component. */
  .subtask-row { background: #f0f9ff; }
  .expense-row { background: #f0fdf4; }
  .expense-marker { color: #166534; font-weight: 600; margin-right: 4px; }
  .grand-total-row { background: #ecfdf5; border-top: 2px solid #99f6e4; }
  .job-materials-header td { background: #fef9c3; padding-top: 8px; }

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

  .actions-cell {
    max-width: 12em;
  }
  /* Buttons in the cell get the shared .row-actions look (app.css). */

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
</style>
