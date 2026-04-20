<script>
  let {
    worksheet = null,
    readonly = false,
    onEditTask = () => {},
    onDeleteTask = () => {},
    onAddMaterial = () => {},
    onEditMaterial = () => {},
    onDeleteMaterial = () => {},
    onReorder = () => {},
  } = $props();

  // Build a flat display list from tasks
  const displayRows = $derived.by(() => {
    if (!worksheet) return [];
    const tasks = [...(worksheet.tasks || [])].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
    const rows = [];

    for (const t of tasks) {
      rows.push({ rowType: 'task', task: t });
      for (const m of (t.plan_materials || [])) {
        rows.push({ rowType: 'material', material: m, task: t });
      }
    }
    return rows;
  });

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
    if (!worksheet) return 0;
    let total = 0;
    const allTasks = worksheet.tasks || [];
    for (const t of allTasks) {
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
      <th class="text-right">Rate / Unit Cost</th>
      <th class="text-right">Sell Price</th>
      <th class="text-right">Total</th>
      {#if !readonly}<th>Actions</th>{/if}
    </tr>
  </thead>
  <tbody>
    {#each displayRows as row}
      {#if row.rowType === 'task'}
        <tr class="task-row">
          <td>{row.task.name}{#if row.task.description}<br><span class="dim">{row.task.description}</span>{/if}</td>
          <td class="text-right">{row.task.units || '-'}</td>
          <td class="text-right">{row.task.est_qty ?? '-'}</td>
          <td class="text-right">-</td>
          <td class="text-right">{fmt(row.task.rate)}</td>
          <td class="text-right">{fmt(taskTotal(row.task))}</td>
          {#if !readonly}
            <td class="actions-cell">
              <button type="button" onclick={() => onEditTask(row.task)}>edit</button>
              <button type="button" onclick={() => onDeleteTask(row.task)}>del</button>
              <button type="button" onclick={() => onAddMaterial(row.task)}>+mat</button>
              <button type="button" onclick={() => onReorder('task', row.task.plan_task_id, 'up')}>&#9650;</button>
              <button type="button" onclick={() => onReorder('task', row.task.plan_task_id, 'down')}>&#9660;</button>
            </td>
          {/if}
        </tr>
      {:else if row.rowType === 'material'}
        <tr class="material-row">
          <td class="indent">
            <span class="material-marker">&#9679;</span> {row.material.description || '(no description)'}
          </td>
          <td class="text-right">-</td>
          <td class="text-right">{row.material.quantity ?? '-'}</td>
          <td class="text-right">{fmt(row.material.unit_cost)}</td>
          <td class="text-right">{fmt(row.material.sell_price)}</td>
          <td class="text-right">{fmt(materialTotal(row.material))}</td>
          {#if !readonly}
            <td class="actions-cell">
              <button type="button" onclick={() => onEditMaterial(row.material, row.task)}>edit</button>
              <button type="button" onclick={() => onDeleteMaterial(row.material, row.task)}>del</button>
            </td>
          {/if}
        </tr>
      {/if}
    {/each}
  </tbody>
  <tfoot>
    <tr class="grand-total-row">
      <td colspan="5" class="text-right"><strong>Grand Total</strong></td>
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
  .indent { padding-left: 28px; }
  .material-marker { color: #aaa; font-size: 8px; vertical-align: middle; margin-right: 4px; }

  .task-row { background: #fff; }
  .task-row:nth-child(even) { background: #fafafa; }
  .material-row { background: #fefce8; }

  .grand-total-row { background: #ecfdf5; border-top: 2px solid #99f6e4; }

  .actions-cell { white-space: nowrap; }
  .actions-cell button {
    font-size: 11px; padding: 2px 6px; margin-right: 2px;
    cursor: pointer; border: 1px solid #ccc; background: #fff; border-radius: 3px;
  }
  .actions-cell button:hover { background: #f0f0f0; }
</style>
