<script>
  let {
    tasks = [],
    readonly = false,
    showStatus = true,
    showAssignee = true,
    onEditTask = () => {},
    onDeleteTask = () => {},
    onAddMaterial = () => {},
    onEditMaterial = () => {},
    onDeleteMaterial = () => {},
    onAddSubtask = () => {},
    onReorder = () => {},
    onTaskClick = () => {},
    onAssignTask = () => {},
  } = $props();

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

  const TERMINAL = ['complete', 'cancelled'];
  const NON_DELETABLE = ['in_progress', 'complete'];
  function isTerminal(task) { return TERMINAL.includes(task.status); }
  function canDelete(task) { return !NON_DELETABLE.includes(task.status); }

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
    return total;
  });

  function fmt(n) {
    return n ? `$${Number(n).toFixed(2)}` : '-';
  }

  const colCount = $derived(6 + (showAssignee ? 1 : 0) + (showStatus ? 1 : 0) + (readonly ? 0 : 1));
</script>

<table border="1" class="task-tree-table">
  <thead>
    <tr>
      <th>Name</th>
      {#if showAssignee}<th>Assignee</th>{/if}
      {#if showStatus}<th>Status</th>{/if}
      <th class="text-right">Units</th>
      <th class="text-right">Est Qty</th>
      <th class="text-right">Unit Cost</th>
      <th class="text-right">Sell Price</th>
      <th class="text-right">Total</th>
      {#if !readonly}<th>Actions</th>{/if}
    </tr>
  </thead>
  <tbody>
    {#each tasks as task, taskIdx}
      <!-- Task row -->
      <tr class="task-row">
        <td>
          <button type="button" class="link-btn" onclick={() => onTaskClick(task)}>{task.name}</button>
          {#if task.description}<br><span class="dim">{task.description}</span>{/if}
        </td>
        {#if showAssignee}<td>{task.assignee_name || 'Unassigned'} {#if !readonly && !isTerminal(task)}<button type="button" class="small-btn" onclick={() => onAssignTask(task)}>assign</button>{/if}</td>{/if}
        {#if showStatus}<td><span class="status-pill status-{task.status}">{task.status}</span></td>{/if}
        <td class="text-right">{task.units || '-'}</td>
        <td class="text-right">{task.est_qty ?? '-'}</td>
        <td class="text-right">-</td>
        <td class="text-right">{fmt(task.rate)}</td>
        <td class="text-right">{fmt(taskTotal(task))}</td>
        {#if !readonly}
          <td class="actions-cell">
            {#if !isTerminal(task)}
              <button type="button" onclick={() => onEditTask(task)}>edit</button>
              {#if canDelete(task)}<button type="button" onclick={() => onDeleteTask(task)}>del</button>{/if}
              <button type="button" onclick={() => onAddMaterial(task)}>+mat</button>
              <button type="button" onclick={() => onAddSubtask(task)}>+sub</button>
            {:else if canDelete(task)}
              <button type="button" onclick={() => onDeleteTask(task)}>del</button>
            {/if}
            <button type="button" onclick={() => onReorder(task.task_id, 'up')} disabled={taskIdx === 0}>&#9650;</button>
            <button type="button" onclick={() => onReorder(task.task_id, 'down')} disabled={taskIdx === tasks.length - 1}>&#9660;</button>
          </td>
        {/if}
      </tr>

      <!-- Materials for this task -->
      {#each (task.materials || []) as mat}
        <tr class="material-row">
          <td class="indent">
            <span class="material-marker">&#9679;</span> {mat.description || '(no description)'}
          </td>
          {#if showAssignee}<td></td>{/if}
          {#if showStatus}<td></td>{/if}
          <td class="text-right">-</td>
          <td class="text-right">{mat.quantity ?? '-'}</td>
          <td class="text-right">{fmt(mat.unit_cost)}</td>
          <td class="text-right">{fmt(mat.sell_price)}</td>
          <td class="text-right">{fmt(materialTotal(mat))}</td>
          {#if !readonly && !isTerminal(task)}
            <td class="actions-cell">
              <button type="button" onclick={() => onEditMaterial(mat, task)}>edit</button>
              <button type="button" onclick={() => onDeleteMaterial(mat, task)}>del</button>
            </td>
          {:else if !readonly}
            <td class="actions-cell"></td>
          {/if}
        </tr>
      {/each}

      <!-- Subtasks for this task -->
      {#each (task.subtasks || []) as sub}
        <tr class="subtask-row">
          <td class="indent">
            <button type="button" class="link-btn" onclick={() => onTaskClick(sub)}>{sub.name}</button>
            {#if sub.description}<br><span class="dim indent">{sub.description}</span>{/if}
          </td>
          {#if showAssignee}<td>{sub.assignee_name || 'Unassigned'} {#if !readonly && !isTerminal(sub)}<button type="button" class="small-btn" onclick={() => onAssignTask(sub)}>assign</button>{/if}</td>{/if}
          {#if showStatus}<td><span class="status-pill status-{sub.status}">{sub.status}</span></td>{/if}
          <td class="text-right">{sub.units || '-'}</td>
          <td class="text-right">{sub.est_qty ?? '-'}</td>
          <td class="text-right">-</td>
          <td class="text-right">{fmt(sub.rate)}</td>
          <td class="text-right">{fmt(taskTotal(sub))}</td>
          {#if !readonly}
            <td class="actions-cell">
              {#if !isTerminal(sub)}
                <button type="button" onclick={() => onEditTask(sub)}>edit</button>
                {#if canDelete(sub)}<button type="button" onclick={() => onDeleteTask(sub)}>del</button>{/if}
                <button type="button" onclick={() => onAddMaterial(sub)}>+mat</button>
              {:else if canDelete(sub)}
                <button type="button" onclick={() => onDeleteTask(sub)}>del</button>
              {/if}
            </td>
          {/if}
        </tr>

        <!-- Materials for this subtask -->
        {#each (sub.materials || []) as mat}
          <tr class="material-row">
            <td class="indent-2">
              <span class="material-marker">&#9679;</span> {mat.description || '(no description)'}
            </td>
            {#if showAssignee}<td></td>{/if}
            {#if showStatus}<td></td>{/if}
            <td class="text-right">-</td>
            <td class="text-right">{mat.quantity ?? '-'}</td>
            <td class="text-right">{fmt(mat.unit_cost)}</td>
            <td class="text-right">{fmt(mat.sell_price)}</td>
            <td class="text-right">{fmt(materialTotal(mat))}</td>
            {#if !readonly && !isTerminal(sub)}
              <td class="actions-cell">
                <button type="button" onclick={() => onEditMaterial(mat, sub)}>edit</button>
                <button type="button" onclick={() => onDeleteMaterial(mat, sub)}>del</button>
              </td>
            {:else if !readonly}
              <td class="actions-cell"></td>
            {/if}
          </tr>
        {/each}
      {/each}
    {/each}
  </tbody>
  <tfoot>
    <tr class="grand-total-row">
      <td colspan={colCount - 1} class="text-right"><strong>Grand Total</strong></td>
      <td class="text-right"><strong>{fmt(grandTotal)}</strong></td>
    </tr>
  </tfoot>
</table>

<style>
  .task-tree-table { width: 100%; border-collapse: collapse; font-size: 14px; }
  .task-tree-table th { padding: 8px 10px; text-align: left; background: #f0fdfa; color: #115e59; }
  .task-tree-table td { padding: 6px 10px; vertical-align: top; }
  .text-right { text-align: right; }
  .dim { color: #888; font-size: 13px; }
  .indent { padding-left: 28px; }
  .indent-2 { padding-left: 48px; }
  .material-marker { color: #aaa; font-size: 8px; vertical-align: middle; margin-right: 4px; }

  .task-row { background: #fff; }
  .task-row:nth-child(even) { background: #fafafa; }
  .subtask-row { background: #f0f9ff; }
  .material-row { background: #fefce8; }
  .grand-total-row { background: #ecfdf5; border-top: 2px solid #99f6e4; }

  .status-pill {
    padding: 2px 8px; border-radius: 10px; font-size: 12px;
    font-weight: 600; text-transform: capitalize;
  }
  .status-pending { background: #f3f4f6; color: #374151; }
  .status-in_progress { background: #dbeafe; color: #1e40af; }
  .status-complete { background: #d1fae5; color: #065f46; }
  .status-blocked { background: #fee2e2; color: #991b1b; }
  .status-cancelled { background: #f3f4f6; color: #9ca3af; }

  .actions-cell { white-space: nowrap; }
  .actions-cell button {
    font-size: 11px; padding: 2px 6px; margin-right: 2px;
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
