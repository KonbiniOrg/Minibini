<script>
  // Read-only "what the customer sees" view of a CHANGE (not the whole
  // amended agreement): only the lines this change order touches, each
  // reduced to a single delta-amount row — replaced lines show the revised
  // description with (new − old), removed lines show the struck line's
  // amount negated, added lines show their own amount. A sibling of
  // DocCustomerView (same table/footer visual grammar — data-table, grand
  // footer rows) rather than a wrapper: DocCustomerView's one-line-one-amount
  // props don't fit a delta document with two footer totals.
  import { fmtMoney } from '@/lib/taskTotals.js';
  import { formatQtyUnits } from '../../lib/format.js';

  let { title, rows = [], coDelta = 0, revisedTotal = 0 } = $props();

  function fmtSigned(n) {
    const v = Number(n ?? 0);
    const sign = v < 0 ? '-' : '';
    return `${sign}$${Math.abs(v).toFixed(2)}`;
  }

  // Reduce the amended-agreement rows to the changed-lines-only delta list.
  // 'agreement' (untouched baseline) rows are dropped entirely — this is a
  // change document, not the whole agreement.
  let deltaRows = $derived(
    rows
      .filter((r) => r.kind !== 'agreement')
      .map((r) => {
        if (r.kind === 'removed') {
          return {
            key: `r-${r.co_line_id}`,
            description: r.original.description,
            qty_display: formatQtyUnits(r.original.qty, r.original.units),
            price: r.original.price,
            delta: -Number(r.original.amount || 0),
          };
        }
        if (r.kind === 'replaced') {
          return {
            key: `p-${r.co_line_id}`,
            description: r.line.description,
            qty_display: formatQtyUnits(r.line.qty, r.line.units),
            price: r.line.price,
            delta: Number(r.line.amount || 0) - Number(r.original.amount || 0),
          };
        }
        // 'added'
        return {
          key: `d-${r.co_line_id}`,
          description: r.line.description,
          qty_display: formatQtyUnits(r.line.qty, r.line.units),
          price: r.line.price,
          delta: Number(r.line.amount || 0),
        };
      })
  );
</script>

<section class="doc-customer-view co-customer-view">
  <h3>{title}</h3>
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
      {#each deltaRows as row (row.key)}
        <tr>
          <td>{row.description}</td>
          <td class="text-right">{row.qty_display}</td>
          <td class="text-right">{fmtMoney(row.price)}</td>
          <td class="text-right">{fmtSigned(row.delta)}</td>
        </tr>
      {/each}
    </tbody>
    <tfoot>
      <tr class="grand">
        <td colspan="3">Change total</td>
        <td class="text-right">{fmtSigned(coDelta)}</td>
      </tr>
      <tr class="grand">
        <td colspan="3"><strong>Revised agreement total</strong></td>
        <td class="text-right"><strong>{fmtMoney(revisedTotal)}</strong></td>
      </tr>
    </tfoot>
  </table>
</section>
