<script>
  // Read-only collapsed document rendering — the "what the customer sees"
  // view of an estimate/invoice/change-order: heading, one row per line,
  // grand total. No buttons anywhere; nothing here mutates state.
  //
  // `extraHeader`/`extraCell` are optional snippet props that let a caller
  // (DocReorderView) tack on one trailing column without duplicating this
  // row markup — the DRY seam for kit C.
  import { fmtMoney } from '@/lib/taskTotals.js';
  import QtyUnits from './QtyUnits.svelte';

  let { title, lines = [], grandTotal, extraHeader = null, extraCell = null } = $props();
</script>

<section class="doc-customer-view">
  <h3>{title}</h3>
  <table class="data-table">
    <thead>
      <tr>
        <th>#</th>
        <th>Description</th>
        <th class="text-right">Qty</th>
        <th class="text-right">Price</th>
        <th class="text-right">Amount</th>
        {#if extraHeader}{@render extraHeader()}{/if}
      </tr>
    </thead>
    <tbody>
      {#each lines as line, i (line.line_id ?? line.line_number)}
        <tr>
          <td>{line.line_number}</td>
          <td class="preserve-breaks">{line.description}</td>
          <td class="text-right"><QtyUnits qty={line.qty} units={line.units} /></td>
          <td class="text-right">{fmtMoney(line.price)}</td>
          <td class="text-right">{fmtMoney(line.amount)}</td>
          {#if extraCell}{@render extraCell(line, i)}{/if}
        </tr>
      {/each}
    </tbody>
    <tfoot>
      <tr class="grand">
        <td colspan="4"><strong>Total</strong></td>
        <td class="text-right"><strong>{fmtMoney(grandTotal)}</strong></td>
        {#if extraHeader}<td></td>{/if}
      </tr>
    </tfoot>
  </table>
</section>
