<script>
  import { link } from 'svelte-spa-router';
  import TaskRow from './tasks/TaskRow.svelte';
  import MaterialRow from './materials/MaterialRow.svelte';
  import { fmtMoney as fmt, taskTotal, materialTotal, feeTotal }
    from '../lib/taskTotals.js';

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
    // action set (the old page-based venue rule is gone).
    onEditTask = null,
    onDeleteTask = null,
    onAddMaterial = null,
    onEditMaterial = null,
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

  // Row math/formatting comes from lib/taskTotals.js — the same source the
  // shared TaskRow/MaterialRow fragments use, so rows and this footer's
  // grand total cannot diverge.
  function isTerminal(task) {
    return task.status === 'complete' || task.status === 'cancelled';
  }

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
    }
    for (const m of (jobMaterials || [])) {
      total += materialTotal(m);
    }
    for (const f of (fees || [])) {
      total += feeTotal(f);
    }
    return total;
  });

  const colCount = $derived(6 + (showAssignee ? 1 : 0) + (showStatus ? 1 : 0) + (readonly ? 0 : 1) + (readonly || jobLocked ? 0 : 1));

  // Row rendering lives in the shared TaskRow / MaterialRow fragments —
  // the same components every surface uses.
  const taskCallbacks = $derived({
    onTaskClick, onAssignTask, onEditTask, onDeleteTask, onCancelTask,
    onAddMaterial,
  });
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
      {#if !readonly && !jobLocked}<th class="move-cell" aria-label="Move target"></th>{/if}
      <th>Name</th>
      {#if showAssignee}<th>Assignee</th>{/if}
      <th class="text-right">Est Time</th>
      {#if showStatus}<th>Status</th>{/if}
      <th class="text-right">Est Qty</th>
      <th class="text-right">Actual</th>
      <th class="text-right">Sell Price</th>
      <th class="text-right"><span class="est-label">(Est)</span><br>Total</th>
      {#if !readonly}<th>Actions</th>{/if}
    </tr>
  </thead>
  <tbody>
    {#each tasks as task, taskIdx}
      <!-- Task row -->
      <TaskRow
        {task} {taskIdx} taskCount={tasks.length}
        {readonly} {jobLocked} {jobOnHold} {canManage}
        {showAssignee} {showStatus}
        bind:selectedTaskId {onReorder}
        {...taskCallbacks}
      />

      <!-- Materials for this task -->
      {#each (task.materials || []) as mat}
        <MaterialRow
          material={mat} ownerTask={task} ownerTerminal={isTerminal(task)}
          indentClass="indent" {showAssignee} {showStatus}
          {readonly} {jobLocked} {jobOnHold} {selectedTaskId}
          {...materialCallbacks}
        />
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
  .dim { color: #888; font-size: 13px; }
  .indent { padding-left: 28px; }
  .indent-2 { padding-left: 48px; }
  /* Headerless radio column — just wide enough for the radio button. */
  .move-cell { text-align: center; width: 24px; padding-left: 4px; padding-right: 4px; }
  /* Fees are billable but not a task/material — tint them so they read distinctly. */
  .fee-row { background: #f3e8ff; }
  .fee-marker { color: #9333ea; font-weight: bold; margin-right: 4px; }
  /* .badge-invoiced comes from app.css. */

  /* Task and material rows style themselves in the shared TaskRow /
     MaterialRow fragments; the rules here cover only the rows TaskTree
     still renders itself (fees, expenses, section headers, footer). */
  .expense-row { background: #f0fdf4; }
  .expense-marker { color: #166534; font-weight: 600; margin-right: 4px; }
  .grand-total-row { background: #ecfdf5; border-top: 2px solid #99f6e4; }
  .job-materials-header td { background: #fef9c3; padding-top: 8px; }

  .actions-cell {
    max-width: 12em;
  }
  /* Buttons in the cell get the shared .row-actions look (app.css). */
</style>
