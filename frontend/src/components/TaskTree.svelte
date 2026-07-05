<script>
  import { link } from 'svelte-spa-router';
  import TaskActivityIndicator from './tasks/TaskActivityIndicator.svelte';
  import { materialStatus, costUnconfirmed } from '../lib/materialStatus.js';
  import { canManageFinancials } from '../stores/permissions.js';

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
    onEditTask = () => {},
    onDeleteTask = () => {},
    onAddMaterial = () => {},
    // Material-op callbacks default to NULL and each button renders only when
    // its callback was actually wired (venue rule: JobTaskListPage is the
    // actions venue). A surface that omits a callback gets a passive tree —
    // never a dead button bound to a no-op default (TaskDetailPage's subtask
    // tree wires only onEditMaterial, deliberately).
    onEditMaterial = null,
    onAddSubtask = () => {},
    onReorder = () => {},
    onTaskClick = () => {},
    onAssignTask = () => {},
    onCancelTask = () => {},
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

  function isMaterialPending(mat) {
    return mat.consumption_state === 'pending';
  }

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

  function restockLabel(mat) {
    // "restock" reads as "put my reserved stock back on the shelf" — only
    // honest when there is stock on hand. For a freeform or not-on-hand
    // material the same action is really a release: the job no longer plans
    // to use it (full-quantity restock IS the release path server-side).
    return mat.inventory_item != null && Number(mat.qty_on_hand) > 0
      ? 'restock' : 'release';
  }

  function isMaterialFinalized(mat) {
    // Consumed or released — terminal states with no further material actions.
    // (The expense-bound qty-0 clause covers pre-`released` rows.)
    return mat.consumption_state === 'consumed'
      || mat.consumption_state === 'released'
      || (mat.is_expense_bound && Number(mat.quantity) === 0);
  }

  function isMaterialReleased(mat) {
    // Tombstone styling (struck through) — the released quantity lives in
    // released_qty; the row's own quantity is 0.
    return mat.consumption_state === 'released';
  }
</script>

{#snippet matStatusChip(mat)}
  {@const s = materialStatus(mat)}
  {#if s.key === 'ordered' && mat.po_id}
    <!-- The Ordered pill IS the PO link — navigation, so fine on every
         venue (the venue rule bans actions, not links). -->
    <a use:link href="#/purchase-orders/{mat.po_id}" class="mat-status mat-{s.key}" title="Open purchase order">{s.label}</a>
  {:else}
    <span class="mat-status mat-{s.key}">{s.label}</span>
  {/if}
{/snippet}

{#snippet matUnitCost(mat)}
  {fmt(mat.unit_cost)}{#if costUnconfirmed(mat)}<span class="cost-warn" title="Cost unconfirmed — placeholder from estimate markup">⚠</span>{/if}
{/snippet}

{#snippet matFulfillActions(mat, task)}
  {@const s = materialStatus(mat)}
  {#if s.key === 'needs-pricing'}
    <!-- Set pricing edits the plan — frozen while the job is on hold.
         Attach expense records a purchase that already happened (it
         establishes a provisional material) — procurement reality, allowed. -->
    {#if onEditMaterial && !jobOnHold}<button type="button" onclick={() => onEditMaterial(mat, task)}>Set pricing</button>{/if}
    {#if onAttachExpense}<button type="button" onclick={() => onAttachExpense(mat)}>Attach expense</button>{/if}
  {:else if s.key === 'needed'}
    {#if onOrderMaterial && $canManageFinancials}<button type="button" onclick={() => onOrderMaterial(mat)}>Order</button>{/if}
    {#if onAttachExpense}<button type="button" onclick={() => onAttachExpense(mat)}>Attach expense</button>{/if}
    {#if onMarkOnHand}<button type="button" class="quiet-link" onclick={() => onMarkOnHand(mat)}>Mark on-hand</button>{/if}
  {:else if s.key === 'awaiting-customer'}
    {#if onMarkOnHand}<button type="button" onclick={() => onMarkOnHand(mat)}>Mark received</button>{/if}
  {/if}
{/snippet}

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
      <td class="actions-cell">
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
        {#if showAssignee}<td>{task.assignee_name || 'Unassigned'} {#if !readonly && !isTerminal(task) && canManage}<button type="button" class="small-btn" onclick={() => onAssignTask(task)}>assign</button>{/if}</td>{/if}
        <td class="text-right">{fmtWorkerTime(task.est_worker_time)}</td>
        {#if showStatus}<td>{#if task.invoice}{@render invoicedLink(task.invoice)}{:else}<TaskActivityIndicator {task} />{#if task.status === 'blocked' && task.blocked_reason}<br><span class="blocked-reason preserve-breaks">{task.blocked_reason}</span>{/if}{/if}</td>{/if}
        <td class="text-right">{task.est_qty ?? '-'}</td>
        <td class="text-right">{taskActual(task) ?? '-'}</td>
        <td class="text-right">{task.scheme_unit_label || '-'}</td>
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
        <tr class="material-row" class:consumed={isMaterialFinalized(mat)} class:released={isMaterialReleased(mat)}>
          {#if !readonly && !jobLocked}
            <td class="move-cell">{#if onMoveMaterial && isMaterialPending(mat) && !isMaterialFinalized(mat) && selectedTaskId != null}<button type="button" class="small-btn" onclick={() => onMoveMaterial(mat, selectedTaskId)}>Move</button>{/if}</td>
          {/if}
          <td class="indent">
            <span class="material-marker">&#9679;</span> {mat.description || '(no description)'}
            {#if !showStatus}{@render matStatusChip(mat)}{/if}
          </td>
          {#if showAssignee}<td></td>{/if}
          <td></td>
          {#if showStatus}<td>{@render matStatusChip(mat)}{#if mat.invoice} {@render invoicedLink(mat.invoice)}{/if}</td>{/if}
          <td class="text-right">{mat.quantity}</td>
          <td class="text-right">-</td>
          <td class="text-right">{mat.units === 'none' ? '-' : mat.units}</td>
          <td class="text-right">{@render matUnitCost(mat)}</td>
          <td class="text-right">{fmt(mat.sell_price)}</td>
          <td class="text-right">{fmt(materialTotal(mat))}</td>
          {#if !readonly && !jobLocked && !isTerminal(task) && isMaterialPending(mat) && !isMaterialFinalized(mat)}
            <td class="actions-cell">
              {@render matFulfillActions(mat, task)}
              {#if onConsumeMaterial && materialStatus(mat).key === 'on-hand'}<button type="button" onclick={() => onConsumeMaterial(mat, task)}>consume</button>{/if}
              {#if onRestockMaterial && !jobOnHold}<button type="button" onclick={() => onRestockMaterial(mat, task)}>{restockLabel(mat)}</button>{/if}
              {#if onDrawMoreMaterial && !mat.is_expense_bound}
                <button type="button" onclick={() => onDrawMoreMaterial(mat, task)}>draw more</button>
              {/if}
              {#if onEditMaterial && !jobOnHold}<button type="button" onclick={() => onEditMaterial(mat, task)}>edit</button>{/if}
              {#if onMoveMaterial}<button type="button" onclick={() => onMoveMaterial(mat, null)}>detach</button>{/if}
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
          {#if showStatus}<td>{#if sub.invoice}{@render invoicedLink(sub.invoice)}{:else}<TaskActivityIndicator task={sub} />{#if sub.status === 'blocked' && sub.blocked_reason}<br><span class="blocked-reason preserve-breaks">{sub.blocked_reason}</span>{/if}{/if}</td>{/if}
          <td class="text-right">{sub.est_qty ?? '-'}</td>
          <td class="text-right">{taskActual(sub) ?? '-'}</td>
          <td class="text-right">{sub.scheme_unit_label || '-'}</td>
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
          <tr class="material-row" class:consumed={isMaterialFinalized(mat)} class:released={isMaterialReleased(mat)}>
            {#if !readonly && !jobLocked}
              <td class="move-cell">{#if onMoveMaterial && isMaterialPending(mat) && !isMaterialFinalized(mat) && selectedTaskId != null}<button type="button" class="small-btn" onclick={() => onMoveMaterial(mat, selectedTaskId)}>Move</button>{/if}</td>
            {/if}
            <td class="indent-2">
              <span class="material-marker">&#9679;</span> {mat.description || '(no description)'}
              {#if !showStatus}{@render matStatusChip(mat)}{/if}
            </td>
            {#if showAssignee}<td></td>{/if}
            <td></td>
            {#if showStatus}<td>{@render matStatusChip(mat)}{#if mat.invoice} {@render invoicedLink(mat.invoice)}{/if}</td>{/if}
            <td class="text-right">{mat.quantity}</td>
            <td class="text-right">-</td>
            <td class="text-right">{mat.units === 'none' ? '-' : mat.units}</td>
            <td class="text-right">{@render matUnitCost(mat)}</td>
            <td class="text-right">{fmt(mat.sell_price)}</td>
            <td class="text-right">{fmt(materialTotal(mat))}</td>
            {#if !readonly && !jobLocked && !isTerminal(sub) && isMaterialPending(mat) && !isMaterialFinalized(mat)}
              <td class="actions-cell">
                {@render matFulfillActions(mat, sub)}
                {#if onConsumeMaterial && materialStatus(mat).key === 'on-hand'}<button type="button" onclick={() => onConsumeMaterial(mat, sub)}>consume</button>{/if}
                {#if onRestockMaterial && !jobOnHold}<button type="button" onclick={() => onRestockMaterial(mat, sub)}>{restockLabel(mat)}</button>{/if}
                {#if onDrawMoreMaterial && !mat.is_expense_bound}
                  <button type="button" onclick={() => onDrawMoreMaterial(mat, sub)}>draw more</button>
                {/if}
                {#if onEditMaterial && !jobOnHold}<button type="button" onclick={() => onEditMaterial(mat, sub)}>edit</button>{/if}
                {#if onMoveMaterial}<button type="button" onclick={() => onMoveMaterial(mat, null)}>detach</button>{/if}
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
        <tr class="material-row" class:consumed={isMaterialFinalized(mat)} class:released={isMaterialReleased(mat)}>
          {#if !readonly && !jobLocked}
            <td class="move-cell">{#if onMoveMaterial && isMaterialPending(mat) && !isMaterialFinalized(mat) && selectedTaskId != null}<button type="button" class="small-btn" onclick={() => onMoveMaterial(mat, selectedTaskId)}>Move</button>{/if}</td>
          {/if}
          <td class="indent">
            <span class="material-marker">&#9679;</span> {mat.description || '(no description)'}
            {#if !showStatus}{@render matStatusChip(mat)}{/if}
          </td>
          {#if showAssignee}<td></td>{/if}
          <td></td>
          {#if showStatus}<td>{@render matStatusChip(mat)}{#if mat.invoice} {@render invoicedLink(mat.invoice)}{/if}</td>{/if}
          <td class="text-right">{mat.quantity}</td>
          <td class="text-right">-</td>
          <td class="text-right">{mat.units === 'none' ? '-' : mat.units}</td>
          <td class="text-right">{@render matUnitCost(mat)}</td>
          <td class="text-right">{fmt(mat.sell_price)}</td>
          <td class="text-right">{fmt(materialTotal(mat))}</td>
          {#if !readonly && !jobLocked && isMaterialPending(mat) && !isMaterialFinalized(mat)}
            <td class="actions-cell">
              {@render matFulfillActions(mat, null)}
              {#if onConsumeMaterial && materialStatus(mat).key === 'on-hand'}<button type="button" onclick={() => onConsumeMaterial(mat, null)}>consume</button>{/if}
              {#if onRestockMaterial && !jobOnHold}<button type="button" onclick={() => onRestockMaterial(mat, null)}>{restockLabel(mat)}</button>{/if}
              {#if onDrawMoreMaterial && !mat.is_expense_bound}
                <button type="button" onclick={() => onDrawMoreMaterial(mat, null)}>draw more</button>
              {/if}
              {#if onEditMaterial && !jobOnHold}<button type="button" onclick={() => onEditMaterial(mat, null)}>edit</button>{/if}
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
            <td class="actions-cell">{#if !jobLocked}<button type="button" onclick={() => onEditFee(fee)}>edit</button>{/if}</td>
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
  .material-marker { color: #aaa; font-size: 8px; vertical-align: middle; margin-right: 4px; }
  /* Fees are billable but not a task/material — tint them so they read distinctly. */
  .fee-row { background: #f3e8ff; }
  .fee-marker { color: #9333ea; font-weight: bold; margin-right: 4px; }
  .badge-invoiced {
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.3px; color: #047857; text-decoration: none;
  }
  .badge-invoiced:hover { text-decoration: underline; }

  /* Top-level task rows use the shared .data-table zebra stripe. */
  .subtask-row { background: #f0f9ff; }
  .material-row { background: #fefce8; }
  .material-row.consumed { color: #9ca3af; }
  /* Released is terminal like consumed, but the quantity has gone back —
     strike the row through so it reads as a tombstone. */
  .material-row.released { color: #9ca3af; text-decoration: line-through; }

  /* Derived material status chip (materialStatus.js) — one per material row,
     shown in every venue (passive on the read-only pillar). */
  .mat-status {
    display: inline-block; margin-left: 6px;
    padding: 1px 6px; font-size: 11px; font-weight: 600;
    border-radius: 3px; white-space: nowrap; vertical-align: middle;
    text-decoration: none;
  }
  .mat-needed { background: #f3f4f6; border: 1px solid #9ca3af; color: #374151; }
  .mat-needs-pricing { background: #fef3c7; border: 1px solid #d97706; color: #92400e; }
  .mat-ordered { background: #dbeafe; border: 1px solid #2563eb; color: #1e40af; }
  .mat-awaiting-customer { background: #ede9fe; border: 1px solid #7c3aed; color: #5b21b6; }
  .mat-on-hand { background: #dcfce7; border: 1px solid #16a34a; color: #166534; }
  .mat-consumed, .mat-released { background: #f3f4f6; border: 1px solid #d1d5db; color: #6b7280; }

  /* Cost-unconfirmed warning beside the unit-cost cell (estimate placeholder). */
  .cost-warn { margin-left: 3px; color: #d97706; cursor: help; }

  /* Quiet secondary affordance ("Mark on-hand") — a button styled as a link. */
  .quiet-link {
    background: none; border: none; padding: 2px 4px; margin: 0 2px 2px 0;
    color: #6b7280; cursor: pointer; font-size: 11px; text-decoration: underline;
  }
  .quiet-link:hover { color: #374151; }
  .po-link { font-size: 11px; color: #1d4ed8; text-decoration: underline; }
  .po-link:hover { color: #1e40af; }
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
