<script>
  import { formatQtyUnits } from '../lib/format.js';

  let {
    worksheet = null,
    readonly = false,
    onTaskClick = () => {},
    onEditTask = () => {},
    onDeleteTask = () => {},
    onReorder = () => {},
    onAddMaterial = () => {},
    onEditMaterial = () => {},
    onDeleteMaterial = () => {},
    onMoveMaterial = () => {},
    selectedTaskId = $bindable(null),
  } = $props();

  const tasks = $derived(
    [...(worksheet?.tasks || [])].sort(
      (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)
    )
  );

  function taskTotal(task) {
    return Number(task.amount) || 0;
  }

  function materialTotal(mat) {
    const qty = Number(mat.quantity) || 0;
    const price = Number(mat.sell_price) || 0;
    return qty * price;
  }

  const grandTotal = $derived.by(() => {
    let total = 0;
    for (const t of tasks) {
      total += taskTotal(t);
      for (const m of (t.plan_materials || [])) {
        total += materialTotal(m);
      }
    }
    return total;
  });

  function fmt(n) {
    return n ? `$${Number(n).toFixed(2)}` : '-';
  }
</script>

<table border="1" class="ws-task-table">
  <thead>
    <tr>
      {#if !readonly}<th>Move target</th>{/if}
      <th>Name / Description</th>
      <th class="text-right">Qty</th>
      <th class="text-right">Total</th>
      {#if !readonly}<th>Actions</th>{/if}
    </tr>
  </thead>
  <tbody>
    {#each tasks as task, i}
      <tr class="task-row">
        {#if !readonly}
          <td class="move-cell"><input type="radio" name="ws-move-target" value={task.plan_task_id} bind:group={selectedTaskId}></td>
        {/if}
        <td>
          <button type="button" class="link-btn" onclick={() => onTaskClick(task)}>{task.name}</button>
          {#if task.description}<br><span class="dim">{task.description}</span>{/if}
        </td>
        <td class="text-right">{task.est_qty ?? '-'}</td>
        <td class="text-right">{fmt(taskTotal(task))}</td>
        {#if !readonly}
          <td class="actions-cell">
            <button type="button" onclick={() => onEditTask(task)}>edit</button>
            <button type="button" onclick={() => onDeleteTask(task)}>del</button>
            <button type="button" onclick={() => onAddMaterial(task)}>+mat</button>
            <button type="button" onclick={() => onReorder(task.plan_task_id, 'up')} disabled={i === 0}>&#9650;</button>
            <button type="button" onclick={() => onReorder(task.plan_task_id, 'down')} disabled={i === tasks.length - 1}>&#9660;</button>
          </td>
        {/if}
      </tr>
      {#each (task.plan_materials || []) as mat}
        <tr class="material-row">
          {#if !readonly}
            <td class="move-cell">{#if selectedTaskId != null && selectedTaskId !== (task.plan_task_id ?? null)}<button type="button" class="small-btn" onclick={() => onMoveMaterial(mat, selectedTaskId)}>Move</button>{/if}</td>
          {/if}
          <td class="indent"><span class="material-marker">&#9679;</span> {mat.description || '(no description)'}</td>
          <td class="text-right">{formatQtyUnits(mat.quantity, mat.units)}</td>
          <td class="text-right">{fmt(materialTotal(mat))}</td>
          {#if !readonly}
            <td class="actions-cell">
              <button type="button" onclick={() => onEditMaterial(mat, task)}>edit</button>
              <button type="button" onclick={() => onDeleteMaterial(mat, task)}>del</button>
              <button type="button" onclick={() => onMoveMaterial(mat, null)}>detach</button>
            </td>
          {/if}
        </tr>
      {/each}
    {/each}
  </tbody>
  <tfoot>
    <tr class="grand-total-row">
      {#if !readonly}<td></td>{/if}
      <td colspan="2" class="text-right"><strong>Grand Total</strong></td>
      <td class="text-right"><strong>{fmt(grandTotal)}</strong></td>
      {#if !readonly}<td></td>{/if}
    </tr>
  </tfoot>
</table>

<style>
  .ws-task-table { width: 100%; border-collapse: collapse; font-size: 14px; }
  .ws-task-table th { padding: 8px 10px; text-align: left; background: #f0fdfa; color: #115e59; }
  .ws-task-table td { padding: 6px 10px; vertical-align: top; }
  .text-right { text-align: right; }
  .dim { color: #888; font-size: 13px; }
  .task-row { background: #fff; }
  .material-row { background: #fefce8; }
  .indent { padding-left: 28px; }
  .material-marker { color: #aaa; font-size: 8px; vertical-align: middle; margin-right: 4px; }
  .grand-total-row { background: #ecfdf5; border-top: 2px solid #99f6e4; }
  .actions-cell { white-space: nowrap; }
  .actions-cell button {
    font-size: 11px; padding: 2px 6px; margin-right: 2px;
    cursor: pointer; border: 1px solid #ccc; background: #fff; border-radius: 3px;
  }
  .actions-cell button:hover { background: #f0f0f0; }
  .actions-cell button:disabled { opacity: 0.4; cursor: default; }
  .move-cell { text-align: center; width: 90px; }
  .small-btn {
    font-size: 11px; padding: 2px 6px;
    cursor: pointer; border: 1px solid #ccc; background: #fff; border-radius: 3px;
  }
  .small-btn:hover { background: #f0f0f0; }
  .link-btn {
    background: none; border: none; padding: 0; margin: 0;
    color: #1d4ed8; cursor: pointer; font-size: inherit;
    text-decoration: underline; text-align: left;
  }
  .link-btn:hover { color: #1e40af; }
</style>
