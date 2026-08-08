<script>
  // THE material row — one shared fragment for every surface that lists
  // materials (job task list task/loose rows, task detail page). Ported
  // from TaskTree's triplicated blocks
  // (2026-07-13). The FULL action set renders wherever a callback is wired
  // (the old task-view-page-only venue rule is gone); gating is by material
  // status, permissions, and the job's held/locked state only.
  import { link } from 'svelte-spa-router';
  import { materialStatus, costUnconfirmed } from '../../lib/materialStatus.js';
  import { fmtMoney as fmt, materialTotal } from '../../lib/taskTotals.js';
  import { canManageFinancials } from '../../stores/permissions.js';

  let {
    material,
    // The owning task dict (null for loose job materials). ownerTerminal
    // freezes actions when the owning task is complete/cancelled.
    ownerTask = null,
    ownerTerminal = false,
    indentClass = 'indent',
    // taskAligned hosts (TaskTree) carry assignee/scheduled-time/actual
    // filler cells so material rows line up under task rows; a
    // materials-only table (task detail page) omits them.
    taskAligned = true,
    showAssignee = true,
    showStatus = true,
    readonly = false,
    jobLocked = false,
    // on_hold freezes plan edits (Set pricing / edit / restock) but NOT
    // procurement (Order, Attach expense, Mark on-hand/received) — the
    // freeze-plan-not-procurement rule, mirrored from the service guards.
    jobOnHold = false,
    selectedTaskId = null,
    onMoveMaterial = null,
    onEditMaterial = null,
    onConsumeMaterial = null,
    onRestockMaterial = null,
    onDrawMoreMaterial = null,
    onOrderMaterial = null,
    onMarkOnHand = null,
    onAttachExpense = null,
  } = $props();

  function isMaterialPending(mat) {
    return mat.consumption_state === 'pending';
  }

  function isMaterialFinalized(mat) {
    // Consumed or released — terminal states with no further material actions.
    // (The expense-bound qty-0 clause covers pre-`released` rows.)
    return mat.consumption_state === 'consumed'
      || mat.consumption_state === 'released'
      || (mat.is_expense_bound && Number(mat.quantity) === 0);
  }

  function isCustomerSupplied(mat) {
    // Nothing on a customer-supplied material is editable: descriptive
    // fields are lot-locked, pricing is locked at $0 — so no edit button.
    return mat.cost_source === 'customer_supplied';
  }

  function isMaterialReleased(mat) {
    // Tombstone styling (struck through) — the released quantity lives in
    // released_qty; the row's own quantity is 0.
    return mat.consumption_state === 'released';
  }

  function restockLabel(mat) {
    // "restock" reads as "put my reserved stock back on the shelf" — only
    // honest when there is stock on hand. For a freeform or not-on-hand
    // material the same action is really a release: the job no longer plans
    // to use it (full-quantity restock IS the release path server-side).
    return mat.inventory_item != null && Number(mat.qty_on_hand) > 0
      ? 'restock' : 'release';
  }

  function matQtyAvail(mat) {
    if (!mat.inventory_item || mat.qty_available === null || mat.qty_available === undefined) return null;
    return Number(mat.qty_available);
  }

  const actionable = $derived(
    !readonly && !jobLocked && !ownerTerminal
    && isMaterialPending(material) && !isMaterialFinalized(material)
  );
</script>

{#snippet availBadge(mat)}
  {#if matQtyAvail(mat) !== null}
    <span class={matQtyAvail(mat) >= 0 ? 'avail-ok' : 'avail-short'}>({mat.qty_available} avail)</span>
  {/if}
{/snippet}

{#snippet matStatusChip(mat)}
  {@const s = materialStatus(mat)}
  {#if s.key === 'ordered' && mat.po_id}
    <!-- The Ordered pill IS the PO link — navigation, fine on every venue. -->
    <a use:link href="#/purchase-orders/{mat.po_id}" class="mat-status mat-{s.key}" title="Open purchase order">{s.label}</a>
  {:else}
    <span class="mat-status mat-{s.key}">{s.label}</span>
  {/if}
{/snippet}

{#snippet matFulfillActions(mat)}
  {@const s = materialStatus(mat)}
  {#if s.key === 'needs-pricing'}
    <!-- Set pricing edits the plan — frozen while the job is on hold.
         Attach expense records a purchase that already happened (it
         establishes a provisional material) — procurement reality, allowed. -->
    {#if onEditMaterial && !jobOnHold}<button type="button" onclick={() => onEditMaterial(mat, ownerTask)}>Set pricing</button>{/if}
    {#if onAttachExpense}<button type="button" onclick={() => onAttachExpense(mat)}>Attach expense</button>{/if}
  {:else if s.key === 'needed'}
    {#if onOrderMaterial && $canManageFinancials && mat.po_line_item_id == null}<button type="button" onclick={() => onOrderMaterial(mat)}>Order</button>{/if}
    {#if onAttachExpense}<button type="button" onclick={() => onAttachExpense(mat)}>Attach expense</button>{/if}
    {#if onMarkOnHand}<button type="button" onclick={() => onMarkOnHand(mat)}>Mark on-hand</button>{/if}
  {:else if s.key === 'awaiting-customer'}
    {#if onMarkOnHand}<button type="button" onclick={() => onMarkOnHand(mat)}>Mark received</button>{/if}
  {/if}
{/snippet}

<tr class="material-row" class:consumed={isMaterialFinalized(material)} class:released={isMaterialReleased(material)}>
  {#if !readonly && !jobLocked}
    <td class="move-cell">{#if onMoveMaterial && isMaterialPending(material) && !isMaterialFinalized(material) && selectedTaskId != null}<button type="button" class="small-btn" onclick={() => onMoveMaterial(material, selectedTaskId)}>Move</button>{/if}</td>
  {/if}
  <td class={indentClass}>
    <span class="material-marker">&#9679;</span> {material.description || '(no description)'} {@render availBadge(material)}
    {#if !showStatus}{@render matStatusChip(material)}{/if}
  </td>
  {#if taskAligned && showAssignee}<td></td>{/if}
  {#if taskAligned}<td></td>{/if}
  {#if showStatus}<td>{@render matStatusChip(material)}{#if material.invoice} <a class="badge-invoiced" href={`#/invoices/${material.invoice.id}`} use:link title="Billed on this invoice">INVOICED</a>{/if}</td>{/if}
  <!-- taskAligned hosts (TaskTree) dropped their Units and Unit Cost
       columns (RM, 2026-08-06): the unit rides inline beside the qty and
       the cost-unconfirmed ⚠ moves to Sell Price. The materials-only
       table (task detail page) keeps both columns. -->
  <td class="text-right">{material.quantity}{taskAligned && material.units && material.units !== 'none' ? ` ${material.units}` : ''}</td>
  {#if taskAligned}<td class="text-right">-</td>{/if}
  {#if !taskAligned}
    <td class="text-right">{material.units === 'none' ? '-' : material.units}</td>
    <td class="text-right">{fmt(material.unit_cost)}{#if costUnconfirmed(material)}<span class="cost-warn" title="Cost unconfirmed — placeholder from estimate markup">⚠</span>{/if}</td>
  {/if}
  <td class="text-right">{fmt(material.sell_price)}{#if taskAligned && costUnconfirmed(material)}<span class="cost-warn" title="Cost unconfirmed — placeholder from estimate markup">⚠</span>{/if}</td>
  <td class="text-right">{fmt(materialTotal(material))}</td>
  {#if actionable}
    <td class="actions-cell row-actions">
      {@render matFulfillActions(material)}
      {#if onConsumeMaterial && materialStatus(material).key === 'on-hand'}<button type="button" onclick={() => onConsumeMaterial(material, ownerTask)}>mark used</button>{/if}
      {#if onRestockMaterial && !jobOnHold}<button type="button" onclick={() => onRestockMaterial(material, ownerTask)}>{restockLabel(material)}</button>{/if}
      {#if onDrawMoreMaterial && !material.is_expense_bound && material.po_line_item_id == null}
        <button type="button" onclick={() => onDrawMoreMaterial(material, ownerTask)}>draw more</button>
      {/if}
      {#if onEditMaterial && !jobOnHold && !isCustomerSupplied(material)}<button type="button" onclick={() => onEditMaterial(material, ownerTask)}>edit</button>{/if}
      {#if onMoveMaterial && ownerTask}<button type="button" onclick={() => onMoveMaterial(material, null)}>detach</button>{/if}
    </td>
  {:else if !readonly}
    <td class="actions-cell row-actions"></td>
  {/if}
</tr>

<style>
  .material-row { background: #fefce8; }
  .material-row.consumed { color: #9ca3af; }
  /* Released is terminal like consumed, but the quantity has gone back —
     strike the row through so it reads as a tombstone. */
  .material-row.released { color: #9ca3af; text-decoration: line-through; }
  .material-marker { color: #aaa; font-size: 8px; vertical-align: middle; margin-right: 4px; }
  /* Nesting ladder: task 0 → its materials 28. */
  .indent { padding-left: 28px; }
  .indent-2 { padding-left: 60px; }
  /* Headerless radio column — just wide enough for the radio button. */
  .move-cell { text-align: center; width: 24px; padding-left: 4px; padding-right: 4px; }
  .text-right { text-align: right; }
  td { padding: 6px 10px; vertical-align: top; }

  /* Derived material status chip (materialStatus.js). */
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

  .avail-ok { font-size: 11px; color: #166534; margin-left: 4px; }
  .avail-short { font-size: 11px; color: #991b1b; margin-left: 4px; }

  .small-btn {
    font-size: 11px; padding: 1px 5px; margin-left: 4px;
    cursor: pointer; border: 1px solid #ccc; background: #fff; border-radius: 3px;
  }
  .small-btn:hover { background: #f0f0f0; }
  /* .badge-invoiced and .row-actions come from app.css. */
</style>
