<script>
  import { formatQtyUnits } from '../lib/format.js';
  import TaskActivityIndicator from './tasks/TaskActivityIndicator.svelte';

  let {
    tasks = [],
    jobMaterials = [],
    readonly = false,
    jobLocked = false,
    canManage = false,
    showStatus = true,
    showAssignee = true,
    onEditTask = () => {},
    onDeleteTask = () => {},
    onAddMaterial = () => {},
    onEditMaterial = () => {},
    onAddSubtask = () => {},
    onReorder = () => {},
    onTaskClick = () => {},
    onAssignTask = () => {},
    onCancelTask = () => {},
    onConsumeMaterial = () => {},
    onRestockMaterial = () => {},
    onDrawMoreMaterial = () => {},
    onMoveMaterial = () => {},
    expenses = [],
    onEditExpense = () => {},
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
    // actual_qty for entered_qty, est_qty x price for flat_fee). When actuals are absent
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
    // FLAT_FEE → estimated quantity (flat fee bills price x est_qty).
    // Unset/other → no actual to display.
    if (task.scheme_algorithm === 'elapsed_time') {
      const h = Number(task.actual_hours) || 0;
      return h > 0 ? h : null;
    }
    if (task.scheme_algorithm === 'entered_qty') {
      return task.actual_qty != null && task.actual_qty !== '' ? task.actual_qty : null;
    }
    if (task.scheme_algorithm === 'flat_fee') {
      return task.est_qty != null && task.est_qty !== '' ? task.est_qty : 1;
    }
    return null;
  }

  function materialTotal(mat) {
    const qty = Number(mat.quantity) || 0;
    const price = Number(mat.sell_price) || 0;
    return qty * price;
  }

  const TERMINAL = ['complete', 'cancelled'];
  const NON_DELETABLE = ['in_progress', 'complete'];
  function isTerminal(task) { return TERMINAL.includes(task.status); }
  function canDelete(task) { return !NON_DELETABLE.includes(task.status); }
  function canCancel(task) { return ['pending', 'in_progress', 'blocked'].includes(task.status); }

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

  function isMaterialPending(mat) {
    return mat.consumption_state === 'pending';
  }

  function isMaterialFinalized(mat) {
    // Consumed, or expense-bound fully restocked (quantity depleted).
    return mat.consumption_state === 'consumed'
      || (mat.is_expense_bound && Number(mat.quantity) === 0);
  }
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
    {#if showStatus}<td></td>{/if}
    <td class="text-right">-</td>
    <td class="text-right">-</td>
    <td class="text-right">-</td>
    <td></td>
    <td></td>
    <td class="text-right">{fmt(exp.amount)}</td>
    {#if !readonly}
      <td class="actions-cell">
        <button type="button" onclick={() => onEditExpense(exp)}>edit</button>
      </td>
    {/if}
  </tr>
{/snippet}

<table class="data-table task-tree-table">
  <thead>
    <tr>
      {#if !readonly && !jobLocked}<th>Move Material</th>{/if}
      <th>Name</th>
      {#if showAssignee}<th>Assignee</th>{/if}
      <th class="text-right">Scheduled Time</th>
      {#if showStatus}<th>Status</th>{/if}
      <th class="text-right">Units</th>
      <th class="text-right">Est Qty</th>
      <th class="text-right">Actual</th>
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
        </td>
        {#if showAssignee}<td>{task.assignee_name || 'Unassigned'} {#if !readonly && !isTerminal(task) && canManage}<button type="button" class="small-btn" onclick={() => onAssignTask(task)}>assign</button>{/if}</td>{/if}
        <td class="text-right">{fmtWorkerTime(task.est_worker_time)}</td>
        {#if showStatus}<td><TaskActivityIndicator {task} />{#if task.status === 'blocked' && task.blocked_reason}<br><span class="blocked-reason preserve-breaks">{task.blocked_reason}</span>{/if}</td>{/if}
        <td class="text-right">{task.scheme_unit_label || '-'}</td>
        <td class="text-right">{task.est_qty ?? '-'}</td>
        <td class="text-right">{taskActual(task) ?? '-'}</td>
        <td class="text-right">-</td>
        <td class="text-right">{fmt(task.effective_rate)}</td>
        <td class="text-right" class:est-total={taskTotalInfo(task).isEstimate}>{fmt(taskTotal(task))}</td>
        {#if !readonly && !jobLocked}
          <td class="actions-cell">
            {#if !isTerminal(task)}
              <button type="button" onclick={() => onEditTask(task)}>edit</button>
              {#if canDelete(task) && !task.has_bleps}<button type="button" onclick={() => onDeleteTask(task)}>del</button>{/if}
              {#if canCancel(task) && canManage}<button type="button" onclick={() => onCancelTask(task)}>cancel</button>{/if}
              <button type="button" onclick={() => onAddMaterial(task)}>+mat</button>
              <button type="button" onclick={() => onAddSubtask(task)}>+sub</button>
            {:else if canDelete(task) && !task.has_bleps}
              <button type="button" onclick={() => onDeleteTask(task)}>del</button>
            {/if}
            {#if canManage}
              <button type="button" onclick={() => onReorder(task.task_id, 'up')} disabled={taskIdx === 0}>&#9650;</button>
              <button type="button" onclick={() => onReorder(task.task_id, 'down')} disabled={taskIdx === tasks.length - 1}>&#9660;</button>
            {/if}
          </td>
        {:else if !readonly}
          <td class="actions-cell"></td>
        {/if}
      </tr>

      <!-- Materials for this task -->
      {#each (task.materials || []) as mat}
        <tr class="material-row" class:consumed={isMaterialFinalized(mat)}>
          {#if !readonly && !jobLocked}
            <td class="move-cell">{#if isMaterialPending(mat) && !isMaterialFinalized(mat) && selectedTaskId != null}<button type="button" class="small-btn" onclick={() => onMoveMaterial(mat, selectedTaskId)}>Move</button>{/if}</td>
          {/if}
          <td class="indent">
            {#if mat.inventory_item_is_inventoried}<span class="inv-badge" title="inventoried">&#128230;</span>{/if}<span class="material-marker">&#9679;</span> {mat.description || '(no description)'}
          </td>
          {#if showAssignee}<td></td>{/if}
          <td></td>
          {#if showStatus}<td></td>{/if}
          <td class="text-right">-</td>
          <td class="text-right">{formatQtyUnits(mat.quantity, mat.units)}</td>
          <td class="text-right">-</td>
          <td class="text-right">{fmt(mat.unit_cost)}</td>
          <td class="text-right">{fmt(mat.sell_price)}</td>
          <td class="text-right">{fmt(materialTotal(mat))}</td>
          {#if !readonly && !jobLocked && !isTerminal(task) && isMaterialPending(mat) && !isMaterialFinalized(mat)}
            <td class="actions-cell">
              <button type="button" onclick={() => onRestockMaterial(mat, task)}>restock</button>
              {#if !mat.is_expense_bound}
                <button type="button" onclick={() => onDrawMoreMaterial(mat, task)}>draw more</button>
              {/if}
              <button type="button" onclick={() => onEditMaterial(mat, task)}>edit</button>
              <button type="button" onclick={() => onMoveMaterial(mat, null)}>detach</button>
            </td>
          {:else if !readonly}
            <td class="actions-cell"></td>
          {/if}
        </tr>
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
          {#if showAssignee}<td>{sub.assignee_name || 'Unassigned'} {#if !readonly && !isTerminal(sub) && canManage}<button type="button" class="small-btn" onclick={() => onAssignTask(sub)}>assign</button>{/if}</td>{/if}
          <td class="text-right">{fmtWorkerTime(sub.est_worker_time)}</td>
          {#if showStatus}<td><TaskActivityIndicator task={sub} />{#if sub.status === 'blocked' && sub.blocked_reason}<br><span class="blocked-reason preserve-breaks">{sub.blocked_reason}</span>{/if}</td>{/if}
          <td class="text-right">{sub.scheme_unit_label || '-'}</td>
          <td class="text-right">{sub.est_qty ?? '-'}</td>
          <td class="text-right">{taskActual(sub) ?? '-'}</td>
          <td class="text-right">-</td>
          <td class="text-right">{fmt(sub.effective_rate)}</td>
          <td class="text-right" class:est-total={taskTotalInfo(sub).isEstimate}>{fmt(taskTotal(sub))}</td>
          {#if !readonly && !jobLocked}
            <td class="actions-cell">
              {#if !isTerminal(sub)}
                <button type="button" onclick={() => onEditTask(sub)}>edit</button>
                {#if canDelete(sub) && !sub.has_bleps}<button type="button" onclick={() => onDeleteTask(sub)}>del</button>{/if}
                {#if canCancel(sub) && canManage}<button type="button" onclick={() => onCancelTask(sub)}>cancel</button>{/if}
                <button type="button" onclick={() => onAddMaterial(sub)}>+mat</button>
              {:else if canDelete(sub) && !sub.has_bleps}
                <button type="button" onclick={() => onDeleteTask(sub)}>del</button>
              {/if}
            </td>
          {:else if !readonly}
            <td class="actions-cell"></td>
          {/if}
        </tr>

        <!-- Materials for this subtask -->
        {#each (sub.materials || []) as mat}
          <tr class="material-row" class:consumed={isMaterialFinalized(mat)}>
            {#if !readonly && !jobLocked}
              <td class="move-cell">{#if isMaterialPending(mat) && !isMaterialFinalized(mat) && selectedTaskId != null}<button type="button" class="small-btn" onclick={() => onMoveMaterial(mat, selectedTaskId)}>Move</button>{/if}</td>
            {/if}
            <td class="indent-2">
              {#if mat.inventory_item_is_inventoried}<span class="inv-badge" title="inventoried">&#128230;</span>{/if}<span class="material-marker">&#9679;</span> {mat.description || '(no description)'}
            </td>
            {#if showAssignee}<td></td>{/if}
            <td></td>
            {#if showStatus}<td></td>{/if}
            <td class="text-right">-</td>
            <td class="text-right">{formatQtyUnits(mat.quantity, mat.units)}</td>
            <td class="text-right">-</td>
            <td class="text-right">{fmt(mat.unit_cost)}</td>
            <td class="text-right">{fmt(mat.sell_price)}</td>
            <td class="text-right">{fmt(materialTotal(mat))}</td>
            {#if !readonly && !jobLocked && !isTerminal(sub) && isMaterialPending(mat) && !isMaterialFinalized(mat)}
              <td class="actions-cell">
                <button type="button" onclick={() => onRestockMaterial(mat, sub)}>restock</button>
                {#if !mat.is_expense_bound}
                  <button type="button" onclick={() => onDrawMoreMaterial(mat, sub)}>draw more</button>
                {/if}
                <button type="button" onclick={() => onEditMaterial(mat, sub)}>edit</button>
                <button type="button" onclick={() => onMoveMaterial(mat, null)}>detach</button>
              </td>
            {:else if !readonly}
              <td class="actions-cell"></td>
            {/if}
          </tr>
        {/each}
      {/each}
    {/each}
    {#if jobMaterials && jobMaterials.length}
      <tr class="job-materials-header">
        <td colspan={colCount}><strong>Materials (no task)</strong></td>
      </tr>
      {#each jobMaterials as mat}
        <tr class="material-row" class:consumed={isMaterialFinalized(mat)}>
          {#if !readonly && !jobLocked}
            <td class="move-cell">{#if isMaterialPending(mat) && !isMaterialFinalized(mat) && selectedTaskId != null}<button type="button" class="small-btn" onclick={() => onMoveMaterial(mat, selectedTaskId)}>Move</button>{/if}</td>
          {/if}
          <td class="indent">
            {#if mat.inventory_item_is_inventoried}<span class="inv-badge" title="inventoried">&#128230;</span>{/if}<span class="material-marker">&#9679;</span> {mat.description || '(no description)'}
          </td>
          {#if showAssignee}<td></td>{/if}
          <td></td>
          {#if showStatus}<td></td>{/if}
          <td class="text-right">-</td>
          <td class="text-right">{formatQtyUnits(mat.quantity, mat.units)}</td>
          <td class="text-right">-</td>
          <td class="text-right">{fmt(mat.unit_cost)}</td>
          <td class="text-right">{fmt(mat.sell_price)}</td>
          <td class="text-right">{fmt(materialTotal(mat))}</td>
          {#if !readonly && !jobLocked && isMaterialPending(mat) && !isMaterialFinalized(mat)}
            <td class="actions-cell">
              <button type="button" onclick={() => onConsumeMaterial(mat, null)}>consume</button>
              <button type="button" onclick={() => onRestockMaterial(mat, null)}>restock</button>
              {#if !mat.is_expense_bound}
                <button type="button" onclick={() => onDrawMoreMaterial(mat, null)}>draw more</button>
              {/if}
              <button type="button" onclick={() => onEditMaterial(mat, null)}>edit</button>
            </td>
          {:else if !readonly}
            <td class="actions-cell"></td>
          {/if}
        </tr>
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
  .material-marker { color: #aaa; font-size: 8px; vertical-align: middle; margin-right: 4px; }
  .inv-badge { margin-left: 6px; font-size: 11px; }

  /* Top-level task rows use the shared .data-table zebra stripe. */
  .subtask-row { background: #f0f9ff; }
  .material-row { background: #fefce8; }
  .material-row.consumed { color: #9ca3af; }
  .expense-row { background: #f0fdf4; }
  .expense-marker { color: #166534; font-weight: 600; margin-right: 4px; }
  .grand-total-row { background: #ecfdf5; border-top: 2px solid #99f6e4; }
  .job-materials-header td { background: #fef9c3; padding-top: 8px; }

  .blocked-reason { font-size: 11px; color: #991b1b; }

  .actions-cell {
    max-width: 12em;
  }
  .actions-cell button {
    font-size: 11px; padding: 2px 6px;
    margin: 0 2px 2px 0;
    cursor: pointer; border: 1px solid #ccc; background: #fff; border-radius: 3px;
  }
  .actions-cell button:hover { background: #f0f0f0; }
  .actions-cell button:disabled { opacity: 0.4; cursor: default; }

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
