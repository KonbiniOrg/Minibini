<script>
  let {
    worksheet = null,
    readonly = false,
    onEditTask = () => {},
    onDeleteTask = () => {},
    onReorder = () => {},
    onAddMaterial = () => {},
    onEditMaterial = () => {},
    onDeleteMaterial = () => {},
  } = $props();

  const tasks = $derived(
    [...(worksheet?.tasks || [])].sort(
      (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0)
    )
  );

  function taskTotal(task) {
    const qty = Number(task.est_qty) || 0;
    const rate = Number(task.rate) || 0;
    return qty * rate;
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
      <th>Name / Description</th>
      <th class="text-right">Units</th>
      <th class="text-right">Qty</th>
      <th class="text-right">Rate</th>
      <th class="text-right">Total</th>
      {#if !readonly}<th>Actions</th>{/if}
    </tr>
  </thead>
  <tbody>
    {#each tasks as task, i}
      <tr class="task-row">
        <td>{task.name}{#if task.description}<br><span class="dim">{task.description}</span>{/if}</td>
        <td class="text-right">{task.units || '-'}</td>
        <td class="text-right">{task.est_qty ?? '-'}</td>
        <td class="text-right">{fmt(task.rate)}</td>
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
          <td class="indent"><span class="material-marker">&#9679;</span> {mat.description || '(no description)'}</td>
          <td class="text-right">-</td>
          <td class="text-right">{mat.quantity ?? '-'}</td>
          <td class="text-right">{fmt(mat.sell_price)}</td>
          <td class="text-right">{fmt(materialTotal(mat))}</td>
          {#if !readonly}
            <td class="actions-cell">
              <button type="button" onclick={() => onEditMaterial(mat, task)}>edit</button>
              <button type="button" onclick={() => onDeleteMaterial(mat, task)}>del</button>
            </td>
          {/if}
        </tr>
      {/each}
    {/each}
  </tbody>
  <tfoot>
    <tr class="grand-total-row">
      <td colspan="4" class="text-right"><strong>Grand Total</strong></td>
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
</style>
