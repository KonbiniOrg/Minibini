<script>
  // One source-pool atom row, shared by the estimate and invoice wizards.
  // Expects a normalized atom: {type, id, description, qty, rate, units,
  // amount, state, sub_info?, claiming_*}.
  let { atom, selected = false, onToggle } = $props();

  // "3 hours × $25.00 = $75.00" — the qty × rate breakdown of the total.
  function formatDetail(a) {
    const qty = Number(a.qty);
    const unit = a.units && a.units !== 'none' ? ` ${a.units}` : '';
    return `${qty}${unit} × $${a.rate} = $${a.amount}`;
  }
</script>

{#if atom.state === 'available'}
  <label>
    <input type="checkbox" checked={selected} onchange={onToggle}>
    <small>[{atom.type === 'task' || atom.type === 'plan_task' ? 'task' : atom.type === 'expense' ? 'expense' : 'material'}]</small>
    {atom.description}
    {#if atom.sub_info} <small>&middot; {atom.sub_info}</small>{/if}
    &mdash; {formatDetail(atom)}
  </label>
{:else if atom.state === 'claimed_by_current'}
  <span style="color: #777;">
    <input type="checkbox" checked disabled>
    <em>{atom.description} &mdash; {formatDetail(atom)}</em>
    <small>&rarr; line {atom.claiming_line_number}</small>
  </span>
{:else if atom.state === 'claimed_by_other'}
  <span style="color: #999;">
    <input type="checkbox" disabled>
    <em>{atom.description} &mdash; {formatDetail(atom)}</em>
    {#if atom.claiming_invoice_id}
      <small><a href="#/invoices/{atom.claiming_invoice_id}">&rarr; {atom.claiming_invoice_number}</a></small>
    {:else}
      <small>&rarr; estimate {atom.claiming_estimate_number}</small>
    {/if}
  </span>
{/if}
