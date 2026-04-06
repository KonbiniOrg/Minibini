<script>
  let {
    worksheet = null,
    readonly = false,
    bundles = [],
    onEditTask = () => {},
    onDeleteTask = () => {},
    onAddMaterial = () => {},
    onEditMaterial = () => {},
    onDeleteMaterial = () => {},
    onEditBundle = () => {},
    onDeleteBundle = () => {},
    onReorder = () => {},
    onReorderInBundle = () => {},
    onMoveToBundle = () => {},
    onRemoveFromBundle = () => {},
  } = $props();

  // Build a flat display list from tasks and bundles
  const displayRows = $derived.by(() => {
    if (!worksheet) return [];
    const tasks = worksheet.tasks || [];
    const wsBundles = worksheet.bundles || [];
    const rows = [];

    // Collect bundled task IDs
    const bundledTaskIds = new Set();
    for (const b of wsBundles) {
      for (const t of (b.plan_tasks || [])) {
        bundledTaskIds.add(t.plan_task_id);
      }
    }

    // Unbundled tasks
    const unbundled = tasks.filter(t => !bundledTaskIds.has(t.plan_task_id));

    // Merge bundles and unbundled tasks, sorted by sort_order
    const items = [];
    for (const b of wsBundles) {
      items.push({ type: 'bundle', sortOrder: b.sort_order, data: b });
    }
    for (const t of unbundled) {
      items.push({ type: 'task', sortOrder: t.sort_order, data: t });
    }
    items.sort((a, b) => (a.sortOrder ?? 0) - (b.sortOrder ?? 0));

    for (const item of items) {
      if (item.type === 'bundle') {
        const b = item.data;
        rows.push({ rowType: 'bundle-header', bundle: b });
        const bundleTasks = [...(b.plan_tasks || [])].sort((a, c) => (a.sort_order ?? 0) - (c.sort_order ?? 0));
        for (const t of bundleTasks) {
          rows.push({ rowType: 'bundled-task', task: t, bundle: b });
          for (const m of (t.plan_materials || [])) {
            rows.push({ rowType: 'material', material: m, task: t, bundled: true });
          }
        }
      } else {
        const t = item.data;
        rows.push({ rowType: 'task', task: t });
        for (const m of (t.plan_materials || [])) {
          rows.push({ rowType: 'material', material: m, task: t, bundled: false });
        }
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

  function bundleTotal(bundle) {
    let total = 0;
    for (const t of (bundle.plan_tasks || [])) {
      total += taskTotal(t);
      for (const m of (t.plan_materials || [])) {
        total += materialTotal(m);
      }
    }
    return total;
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
    return n ? `$${Number(n).toFixed(2)}` : '\u2014';
  }

  // Available bundles for the "move to bundle" dropdown
  const availableBundles = $derived((worksheet?.bundles || []));
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
      {#if row.rowType === 'bundle-header'}
        <tr class="bundle-header-row">
          <td colspan="5">
            <strong>{row.bundle.name}</strong>
          </td>
          <td class="text-right"><strong>{fmt(bundleTotal(row.bundle))}</strong></td>
          {#if !readonly}
            <td class="actions-cell">
              <button type="button" onclick={() => onEditBundle(row.bundle)}>edit</button>
              <button type="button" onclick={() => onDeleteBundle(row.bundle)}>del</button>
              <button type="button" onclick={() => onReorder('bundle', row.bundle.plan_bundle_id, 'up')}>&#9650;</button>
              <button type="button" onclick={() => onReorder('bundle', row.bundle.plan_bundle_id, 'down')}>&#9660;</button>
            </td>
          {/if}
        </tr>
      {:else if row.rowType === 'bundled-task'}
        <tr class="bundled-task-row">
          <td class="indent">{row.task.name}{#if row.task.description}<br><span class="dim">{row.task.description}</span>{/if}</td>
          <td class="text-right">{row.task.units || '\u2014'}</td>
          <td class="text-right">{row.task.est_qty ?? '\u2014'}</td>
          <td class="text-right">{fmt(row.task.rate)}</td>
          <td class="text-right">\u2014</td>
          <td class="text-right">{fmt(taskTotal(row.task))}</td>
          {#if !readonly}
            <td class="actions-cell">
              <button type="button" onclick={() => onEditTask(row.task)}>edit</button>
              <button type="button" onclick={() => onDeleteTask(row.task)}>del</button>
              <button type="button" onclick={() => onAddMaterial(row.task)}>+mat</button>
              <button type="button" onclick={() => onReorderInBundle(row.task, 'up')}>&#9650;</button>
              <button type="button" onclick={() => onReorderInBundle(row.task, 'down')}>&#9660;</button>
              <button type="button" onclick={() => onRemoveFromBundle(row.task, row.bundle)}>unbundle</button>
            </td>
          {/if}
        </tr>
      {:else if row.rowType === 'task'}
        <tr class="task-row">
          <td>{row.task.name}{#if row.task.description}<br><span class="dim">{row.task.description}</span>{/if}</td>
          <td class="text-right">{row.task.units || '\u2014'}</td>
          <td class="text-right">{row.task.est_qty ?? '\u2014'}</td>
          <td class="text-right">{fmt(row.task.rate)}</td>
          <td class="text-right">\u2014</td>
          <td class="text-right">{fmt(taskTotal(row.task))}</td>
          {#if !readonly}
            <td class="actions-cell">
              <button type="button" onclick={() => onEditTask(row.task)}>edit</button>
              <button type="button" onclick={() => onDeleteTask(row.task)}>del</button>
              <button type="button" onclick={() => onAddMaterial(row.task)}>+mat</button>
              <button type="button" onclick={() => onReorder('task', row.task.plan_task_id, 'up')}>&#9650;</button>
              <button type="button" onclick={() => onReorder('task', row.task.plan_task_id, 'down')}>&#9660;</button>
              {#if availableBundles.length > 0}
                <select onchange={(e) => { if (e.target.value) { onMoveToBundle(row.task, e.target.value); e.target.value = ''; } }}>
                  <option value="">bundle...</option>
                  {#each availableBundles as b}
                    <option value={b.plan_bundle_id}>{b.name}</option>
                  {/each}
                </select>
              {/if}
            </td>
          {/if}
        </tr>
      {:else if row.rowType === 'material'}
        <tr class="material-row">
          <td class={row.bundled ? 'indent-2' : 'indent'}>
            <span class="material-marker">&#9679;</span> {row.material.description || '(no description)'}
          </td>
          <td class="text-right">\u2014</td>
          <td class="text-right">{row.material.quantity ?? '\u2014'}</td>
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
  .indent-2 { padding-left: 48px; }
  .material-marker { color: #aaa; font-size: 8px; vertical-align: middle; margin-right: 4px; }

  .bundle-header-row { background: #e0f2fe; }
  .bundled-task-row { background: #f0f9ff; }
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
  .actions-cell select { font-size: 11px; padding: 1px 4px; }
</style>
