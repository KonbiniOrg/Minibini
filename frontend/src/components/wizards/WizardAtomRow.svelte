<script>
  // One source-pool atom row, shared by the estimate and invoice wizards.
  // Expects a normalized atom: {type, id, description, qty, rate, units,
  // amount, state, sub_info?, claiming_*}.
  let { atom, selected = false, onToggle } = $props();

  function fmtMoney(n) {
    return Number(n).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  }

  // "3 hours × $25.00 = $75.00" — the qty × rate breakdown of the total.
  // Deposit credit atoms have no meaningful qty × rate breakdown (they're
  // a negated total pulled solo), so they render as a plain credit amount.
  function formatDetail(a) {
    if (a.type === 'deposit') {
      return `${fmtMoney(Math.abs(Number(a.amount)))} credit`;
    }
    const qty = Number(a.qty);
    const unit = a.units && a.units !== 'none' ? ` ${a.units}` : '';
    // fmtMoney (not raw "$" concatenation) so a negative fee/credit renders
    // "-$80.00" rather than the mangled "$-80.00".
    return `${qty}${unit} × ${fmtMoney(a.rate)} = ${fmtMoney(a.amount)}`;
  }
</script>

{#if atom.state === 'not_billable'}
  <span class="atom-not-billable">
    {atom.description} — {atom.not_billable_reason === 'task_incomplete' ? 'task not complete' : 'not used'}
  </span>
{:else if atom.state === 'available'}
  <label>
    <input type="checkbox" checked={selected} onchange={onToggle}>
    <small>[{atom.type === 'task' ? 'task' : atom.type === 'expense' ? 'expense' : atom.type === 'fee' ? 'fee / credit' : atom.type === 'deposit' ? 'deposit' : 'material'}]</small>
    {atom.description}
    {#if atom.task_cancelled}<span class="atom-cancelled" title="This task was cancelled; its recorded work is still billable.">cancelled — work done</span>{/if}
    {#if atom.struck_from_agreement}<span class="atom-cancelled" title="An accepted change order removed this from the agreement, but the work or material remains on the job. Bill it consciously, or reconcile the job.">struck from agreement</span>{/if}
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

<style>
  .atom-not-billable {
    color: #aaa;
    font-style: italic;
    cursor: default;
    user-select: none;
  }
  /* Cancelled-but-billable marker (C3) — amber, so the biller notices. */
  .atom-cancelled {
    display: inline-block; margin-left: 4px; padding: 0 6px;
    font-size: 11px; font-weight: 600; border-radius: 3px;
    background: #fef3c7; border: 1px solid #d97706; color: #92400e;
    white-space: nowrap;
  }
</style>
