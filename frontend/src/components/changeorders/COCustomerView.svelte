<script>
  // Read-only "what the customer sees" view of the WHOLE amended agreement
  // (RM 2026-08-11 — previously a changed-lines-only delta list): every
  // amended-agreement row renders, mirroring the customer portal's grammar
  // (ChangeOrderPortal.svelte over compose_change_order_diff): untouched
  // lines plain, a replacement tinted above its struck original, removed
  // lines struck, adds tinted with a "+" tag, and a Previous / New / Change
  // totals footer. A sibling of DocCustomerView (same table/footer visual
  // grammar) rather than a wrapper: its one-line-one-amount props don't fit
  // struck originals and three footer totals.
  import { fmtMoney } from '@/lib/taskTotals.js';
  import QtyUnits from '../docsurface/QtyUnits.svelte';

  // `deliverables`: compose_deliverable_diff rows (GET .../deliverables-diff/)
  // — {kind, description, qty, units}, kinds unchanged / changed /
  // changed-orig / removed / added, same grammar as the portal's "What
  // you'll receive" table.
  let { title, rows = [], deliverables = [], originalTotal = 0, coDelta = 0, revisedTotal = 0 } = $props();

  function fmtSigned(n) {
    const v = Number(n ?? 0);
    if (v === 0) return '$0.00';
    return (v > 0 ? '+' : '-') + `$${Math.abs(v).toFixed(2)}`;
  }

  // Flatten amended-agreement rows into display rows. `cls` mirrors the
  // portal's row-<kind> classes so the two customer surfaces stay visually
  // aligned.
  let displayRows = $derived(
    rows.flatMap((r) => {
      if (r.kind === 'agreement') {
        return [{ key: `a-${r.line.estimate_line_id ?? r.line.description}`, cls: 'row-unchanged', line: r.line }];
      }
      if (r.kind === 'removed') {
        return [{ key: `r-${r.co_line_id}`, cls: 'row-removed', line: r.original }];
      }
      if (r.kind === 'replaced') {
        return [
          { key: `p-${r.co_line_id}`, cls: 'row-changed', line: r.line },
          { key: `po-${r.co_line_id}`, cls: 'row-changed-orig', line: r.original },
        ];
      }
      // 'added'
      return [{ key: `d-${r.co_line_id}`, cls: 'row-added', added: true, line: r.line }];
    })
  );
</script>

<section class="doc-customer-view co-customer-view">
  <h3>{title}</h3>

  {#if deliverables.length}
    <h4>What you'll receive</h4>
    <table class="data-table co-customer-deliverables">
      <thead>
        <tr>
          <th>Item</th>
          <th class="text-right">Qty</th>
        </tr>
      </thead>
      <tbody>
        {#each deliverables as d, i (i)}
          <tr class={`row-${d.kind}`}>
            <td>{#if d.kind === 'added'}<span class="tag-add">+</span>{/if}{d.description}</td>
            <td class="text-right"><QtyUnits qty={d.qty} units={d.units} /></td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  <table class="data-table">
    <thead>
      <tr>
        <th>Description</th>
        <th class="text-right">Qty</th>
        <th class="text-right">Price</th>
        <th class="text-right">Amount</th>
      </tr>
    </thead>
    <tbody>
      {#each displayRows as row (row.key)}
        <tr class={row.cls}>
          <td class="preserve-breaks">{#if row.added}<span class="tag-add">+</span>{/if}{row.line.description}</td>
          <td class="text-right"><QtyUnits qty={row.line.qty} units={row.line.units} /></td>
          <td class="text-right">{fmtMoney(row.line.price)}</td>
          <td class="text-right">{fmtMoney(row.line.amount)}</td>
        </tr>
      {/each}
    </tbody>
    <tfoot>
      <tr class="grand">
        <td colspan="3">Previous total</td>
        <td class="text-right">{fmtMoney(originalTotal)}</td>
      </tr>
      <tr class="grand">
        <td colspan="3"><strong>New total</strong></td>
        <td class="text-right"><strong>{fmtMoney(revisedTotal)}</strong></td>
      </tr>
      <tr class="grand">
        <td colspan="3">Change</td>
        <td class="text-right">{fmtSigned(coDelta)}</td>
      </tr>
    </tfoot>
  </table>
</section>

<style>
  /* Breathing room between the deliverables table and the line-items table. */
  table.co-customer-deliverables { margin-bottom: 1.5em; }

  /* Mirrors ChangeOrderPortal.svelte's row styling so shop Customer mode and
     the portal read the same. */
  tr.row-changed { background: #fff7ed; }
  tr.row-added { background: #dcfce7; }
  tr.row-removed td, tr.row-changed-orig td { color: #9ca3af; text-decoration: line-through; }
  .tag-add { color: #166534; font-weight: 600; margin-right: 4px; }
</style>
