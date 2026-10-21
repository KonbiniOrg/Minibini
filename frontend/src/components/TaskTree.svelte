<script>
  import { link } from 'svelte-spa-router';
  import TaskRow from './tasks/TaskRow.svelte';
  import MaterialRow from './materials/MaterialRow.svelte';
  import { fmtMoney as fmt, taskTotal, materialTotal }
    from '../lib/taskTotals.js';
  import { canManageFinancials } from '../stores/permissions.js';
  import SortableList from './SortableList.svelte';

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
    // Drag-and-drop reorder (issue #513): called with the job's task ids in
    // their new order after a drag that moved something. Handles render only
    // when this is wired and the user may reorder (canManage, not read-only,
    // not frozen, not on hold — the server refuses the last two).
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
    onDeleteExpense = null,
    onRejectExpense = null,
    selectedTaskId = $bindable(null),
    // Bundle-selection checkboxes (Task 3) — off by default so every
    // existing consumer of this shared tree renders unchanged.
    bundleMode = false,
    poolByKey = null,
    bundleSelected = [],
    onToggleBundle = () => {},
    // claimed_by_current chip text (Tasks-page CO lens) — pass-through to
    // TaskRow/MaterialRow; their own defaults ('estimated' / 'Already on the
    // draft estimate') keep every other consumer of this tree unchanged.
    bundleClaimedLabel = 'estimated',
    bundleClaimedTitle = 'Already on the draft estimate',
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
    return total;
  });

  const colCount = $derived(6 + (showAssignee ? 1 : 0) + (showStatus ? 1 : 0) + (readonly ? 0 : 1) + (readonly || jobLocked ? 0 : 1) + (bundleMode ? 1 : 0));

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

  // Drag-and-drop reorder (issue #513) — SortableList owns the wiring.
  const canDrag = $derived(!!onReorder && canManage && !readonly && !jobLocked && !jobOnHold);
</script>

{#snippet taskRows(task, dragHandle)}
  <TaskRow
    {task}
    {readonly} {jobLocked} {jobOnHold} {canManage}
    {showAssignee} {showStatus}
    bind:selectedTaskId {dragHandle}
    {...taskCallbacks}
    {bundleMode}
    bundleAtom={poolByKey?.get(`task:${task.task_id}`) ?? null}
    bundleChecked={bundleSelected.includes(`task:${task.task_id}`)}
    onToggleBundle={() => onToggleBundle(`task:${task.task_id}`)}
    {bundleClaimedLabel}
    {bundleClaimedTitle}
  />
  {#each (task.materials || []) as mat}
    <MaterialRow
      material={mat} ownerTask={task} ownerTerminal={isTerminal(task)}
      indentClass="indent" {showAssignee} {showStatus}
      {readonly} {jobLocked} {jobOnHold} {selectedTaskId}
      {...materialCallbacks}
      {bundleMode}
      bundleAtom={poolByKey?.get(`material:${mat.material_id}`) ?? null}
      bundleChecked={bundleSelected.includes(`material:${mat.material_id}`)}
      onToggleBundle={() => onToggleBundle(`material:${mat.material_id}`)}
      {bundleClaimedLabel}
      {bundleClaimedTitle}
    />
  {/each}
{/snippet}


{#snippet expenseRow(exp, deep)}
  <tr class="expense-row">
    {#if bundleMode}<td class="bundle-cell"></td>{/if}
    {#if !readonly && !jobLocked}<td class="move-cell"></td>{/if}
    <td class={deep ? 'indent-2' : 'indent'}>
      <span class="expense-marker">$</span> {exp.description || '(expense)'}
      {#if exp.purchased_by_name}<small class="dim">· {exp.purchased_by_name}</small>{/if}
    </td>
    {#if showAssignee}<td></td>{/if}
    <td></td>
    {#if showStatus}<td>{#if exp.invoice}{@render invoicedLink(exp.invoice)}{/if}</td>{/if}
    <td class="text-right figure">-</td>
    <td class="text-right figure">-</td>
    <td></td>
    <td class="text-right figure">{fmt(exp.amount)}</td>
    {#if !readonly}
      <td class="actions-cell row-actions">
        {#if exp.invoice}
          <span class="locked-note">billed — locked</span>
        {:else}
          <button type="button" onclick={() => onEditExpense(exp)}>edit</button>
          {#if onRejectExpense && $canManageFinancials
               && exp.payment_method === 'personal' && exp.status === 'submitted'}
            <button type="button" class="danger" onclick={() => onRejectExpense(exp)}>reject</button>
          {/if}
          {#if onDeleteExpense && $canManageFinancials}
            <button type="button" class="danger" onclick={() => onDeleteExpense(exp)}>delete</button>
          {/if}
        {/if}
      </td>
    {/if}
  </tr>
{/snippet}

{#snippet invoicedLink(inv)}
  <a class="badge-invoiced" href={`#/invoices/${inv.id}`} use:link
     title="Billed on this invoice">Invoiced</a>
{/snippet}

<table class="data-table task-tree-table">
  <thead>
    <tr>
      {#if bundleMode}<th class="bundle-cell" aria-label="Select for bundling"></th>{/if}
      {#if !readonly && !jobLocked}<th class="move-cell" aria-label="Move target"></th>{/if}
      <th>Name</th>
      {#if showAssignee}<th>Assignee</th>{/if}
      <th class="text-right">Est Time</th>
      {#if showStatus}<th>Status</th>{/if}
      <th class="text-right">Est Qty</th>
      <th class="text-right">Actual</th>
      <th class="text-right">Sell Price</th>
      <th class="text-right"><span class="est-label">(Est)</span> Total</th>
      {#if !readonly}<th>Actions</th>{/if}
    </tr>
  </thead>
  <!-- Each task and its materials are one <tbody>, so a drag moves the
       whole group (a table may hold several tbodies). -->
  <SortableList items={tasks} getId={(t) => t.task_id} disabled={!canDrag} {onReorder}>
    {#snippet preview(task)}
      <div class="drag-preview" aria-hidden="true">
        <span class="drag-preview-grip">⠿</span>
        <span class="drag-preview-name">{task.name}</span>
        {#if task.materials?.length}<span class="drag-preview-meta">+{task.materials.length} material{task.materials.length === 1 ? '' : 's'}</span>{/if}
      </div>
    {/snippet}
    {#snippet item(task, index, sortable)}
      <tbody class="task-group" data-task-id={task.task_id}
             data-dragging={sortable.dragging} {@attach sortable.ref}>
        {@render taskRows(task, sortable.handleRef)}
      </tbody>
    {/snippet}
  </SortableList>
  <tbody>
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
          {bundleMode}
          bundleAtom={poolByKey?.get(`material:${mat.material_id}`) ?? null}
          bundleChecked={bundleSelected.includes(`material:${mat.material_id}`)}
          onToggleBundle={() => onToggleBundle(`material:${mat.material_id}`)}
          {bundleClaimedLabel}
          {bundleClaimedTitle}
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
  </tbody>
  <tfoot>
    <tr class="grand-total-row">
      <td colspan={colCount - 1} class="text-right"><strong>Grand Total</strong></td>
      <td class="text-right figure"><strong>{fmt(grandTotal)}</strong></td>
    </tr>
  </tfoot>
</table>

<style>
  /* Base + green header come from the global .data-table class; just tighten padding. */
  .task-tree-table th { padding: 8px 10px; font-size: var(--text-sm); white-space: nowrap; }
  .task-tree-table td { padding: 6px 10px; vertical-align: top; }
  /* Each task is its own <tbody>, which restarts the shared .data-table zebra
     per group; stripe alternate task groups instead (material rows paint
     their own background). */
  .task-tree-table :global(tbody.task-group:nth-of-type(even) > tr.task-row) { background: var(--doc-faint); }
  /* The group being dragged lifts above its neighbours. */
  /* The dragged group stays in the table (dimmed) while the preview follows the cursor. */
  .task-tree-table :global(tbody.task-group[data-dragging="true"]) { opacity: 0.4; }
  .task-tree-table :global(.drag-preview) {
    display: flex; align-items: center; gap: 8px;
    max-width: 420px; padding: 6px 12px;
    font-family: var(--font-sans); font-size: var(--text-sm); color: var(--text-fg);
    background: #fff; border: 1px solid #8f8f8f; border-radius: 6px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15); cursor: grabbing;
  }
  .task-tree-table :global(.drag-preview-grip) { color: var(--text-muted); }
  .task-tree-table :global(.drag-preview-name) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .task-tree-table :global(.drag-preview-meta) { color: var(--text-muted); white-space: nowrap; }
  .text-right { text-align: right; }
  /* Numbers ("2h 54m", "2.90 hour", "$85.00") stay on one line in this table's
     task and material rows; the width they stop wasting goes to the Name
     column, so names wrap less too. Scoped here, not app.css: MaterialRow and
     .text-right are shared with other tables. */
  .task-tree-table :global(.material-row td.text-right) { white-space: nowrap; font-variant-numeric: tabular-nums; }  /* = .figure; MaterialRow is shared, so applied from here */

  /* ── Readability pass (2026-10-21), scoped to this table ───────────────────
     Shared pieces (MaterialRow, TaskActivityIndicator) are adjusted here, not
     in their own files, because they also render in other views. Uses the
     inert tokens in app.css. Rules: one body size, one secondary size, one
     muted grey that passes AA on the yellow bands, bold only in headers,
     tags are borderless pills and buttons are bordered rectangles. */
  /* Inter in this table only: much narrower than the page's Verdana, so cells
     wrap less; buttons inherit it (font-family: inherit below). */
  .task-tree-table { color: var(--text-fg); font-family: var(--font-sans); }
  .task-tree-table :global(td) { font-size: var(--text-sm); }
  .task-tree-table :global(.material-row.consumed),
  .task-tree-table :global(.material-row.released) { color: var(--text-muted); }
  .task-tree-table :global(.material-marker) { color: var(--text-muted); }
  /* One text size across the table (Inter freed the room): MaterialRow's notes,
     code chip, and stock figures come up from 11px to the body size. The ●
     marker stays small — it's a bullet, not text. */
  .task-tree-table :global(.bundle-claimed),
  .task-tree-table :global(.mat-code),
  .task-tree-table :global(.avail-ok),
  .task-tree-table :global(.avail-short) { font-size: var(--text-sm); }
  /* Shared badges from app.css (INVOICED link: 11px bold caps; pill status: 13px). */
  .task-tree-table :global(.badge-invoiced) { font-size: var(--text-sm); font-weight: normal; }
  .task-tree-table :global(.status-badge) { font-size: var(--text-sm); }
  .task-tree-table :global(.mat-status) {
    /* Outlined pill, as shadcn's table badges (dashboard-01: Badge variant="outline"):
       each status keeps its own coloured border; the round shape marks it a tag. */
    border-radius: 999px; padding: 0 8px;
    font-size: var(--text-sm); font-weight: normal;
  }
  .task-tree-table :global(.mat-consumed),
  .task-tree-table :global(.mat-released) { color: var(--text-muted); border-color: #767676; }
  /* Row buttons (edit / del / cancel / +mat, assign): body size, and a border
     dark enough to see as a control (#767676 is 4.5:1 on white; #ccc was 1.6:1). */
  /* Every button in the table (row actions, assign, Order / Attach expense /
     Mark on-hand / Set pricing, Move…) — except the task-name link and the
     drag handle, which are buttons in markup but not styled as buttons. */
  .task-tree-table :global(button:not(.link-btn):not(.drag-handle)) {
    /* shadcn Button variant="outline" size="sm": fixed 28px height, soft
       border (#8f8f8f, 3.3:1 — visible as a control), white, grey on hover. */
    display: inline-flex; align-items: center; box-sizing: border-box; height: 28px;
    font-family: inherit; font-size: var(--text-sm); line-height: 1;
    padding: 0 10px; margin: 2px 4px 2px 0;
    border: 1px solid #8f8f8f; border-radius: 6px; background: #fff;
    color: var(--text-fg); cursor: pointer;
  }
  .task-tree-table :global(button:not(.link-btn):not(.drag-handle):hover) { background: #f4f4f5; }
  .task-tree-table :global(button:not(.link-btn):not(.drag-handle):disabled) { opacity: 0.5; cursor: default; }
  /* shadcn variant="destructive": red tint for del / delete / reject. */
  .task-tree-table :global(button.danger:not(.link-btn):not(.drag-handle)) { color: #b91c1c; background: #fef2f2; border-color: #f87171; }
  .task-tree-table :global(button.danger:not(.link-btn):not(.drag-handle):hover) { background: #fee2e2; }
  /* Actions column shrinks to its content (width: 1%); leftover width goes to Name.
     Task rows' four short buttons stay on one line and set that width; material
     and expense rows (longer buttons: "draw more", "mark used") wrap inside it
     instead of widening the whole column. */
  .task-tree-table :global(td.actions-cell) { width: 1%; }
  .task-tree-table :global(tr.task-row td.actions-cell) { white-space: nowrap; }
  /* Task status as an outlined pill with its coloured dot inside — the same
     family as the material status pills, so the Status column reads as one
     kind of tag (shadcn's table status: Badge variant="outline" + icon). */
  .task-tree-table :global(.ta:not(.pill)) {
    font-weight: normal; text-transform: none; letter-spacing: 0;
    font-size: var(--text-sm);
    border: 1px solid color-mix(in srgb, var(--ta-color) 60%, #fff);
    border-radius: 999px; padding: 0 8px;
    /* Label in body colour, colour only on the dot and border (shadcn pattern);
       the status colours as text failed contrast (Unstarted #94a3b8 ≈ 2.6:1). */
    color: var(--text-fg);
  }
  /* Sentence case for the two shared labels this table can't edit at the
     source (MaterialRow / materialStatus.js render them in other views too). */
  .task-tree-table :global(.badge-invoiced),
  .task-tree-table :global(.mat-on-hand) { display: inline-block; text-transform: lowercase; }
  .task-tree-table :global(.badge-invoiced)::first-letter,
  .task-tree-table :global(.mat-on-hand)::first-letter { text-transform: uppercase; }
  .est-label { color: var(--text-muted); font-size: var(--text-sm); font-weight: normal; }
  .dim { color: var(--text-muted); font-size: var(--text-sm); }
  .indent { padding-left: 28px; }
  .indent-2 { padding-left: 48px; }
  /* Headerless radio column — just wide enough for the radio button. */
  .move-cell { text-align: center; width: 24px; padding-left: 4px; padding-right: 4px; }
  /* Bundle-selection checkbox column (Task 3) — same footprint as move-cell. */
  .bundle-cell { text-align: center; width: 24px; padding-left: 4px; padding-right: 4px; }
  /* .badge-invoiced comes from app.css. */

  /* Task and material rows style themselves in the shared TaskRow /
     MaterialRow fragments; the rules here cover only the rows TaskTree
     still renders itself (expenses, section headers, footer). */
  .expense-row { background: #f0fdf4; }
  .expense-marker { color: #166534; font-weight: 600; margin-right: 4px; }
  /* Colorway-token bands (amber via .cw-tasks on the task pages; teal
     defaults elsewhere). The section-header row is the 60%-soft tier —
     an in-table divider, deliberately lighter than the header band. */
  .grand-total-row { background: var(--doc-soft); border-top: 2px solid var(--doc-border); }
  .job-materials-header td {
    background: color-mix(in srgb, var(--doc-soft) 60%, #fff);
    color: var(--doc-accent); padding-top: 8px;
  }

  /* Buttons in the cell get the shared .row-actions look (app.css). */
  .locked-note { font-size: var(--text-sm); color: var(--text-muted); font-style: italic; }
</style>
