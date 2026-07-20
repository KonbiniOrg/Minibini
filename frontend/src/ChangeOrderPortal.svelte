<script>
  import PortalDocument from './components/PortalDocument.svelte';

  function fmtDiff(s) {
    const v = Number(s ?? 0);
    if (v === 0) return '$0.00';
    return (v > 0 ? '+' : '−') + `$${Math.abs(v).toFixed(2)}`;
  }
</script>

{#snippet content(data, ctx)}
  <h1>Change order {data.change_order_number}</h1>

  {#if ctx.done === 'requested'}
    <p>Thank you — we've received your request and will send you a revised change order shortly.</p>
  {:else if data.status === 'superseded'}
    <p>A newer version of this change order has been issued.
      {#if data.current_token}
        <a href={`/portal/?token=${data.current_token}&doc=change_order`}>View the current change order</a>.
      {/if}
    </p>
  {:else if data.status === 'expired'}
    <p>This change order expired{#if data.expiration_date}{' '}on {ctx.fmtDate(data.expiration_date)}{/if}. Please contact us.</p>
  {:else if data.status === 'rejected'}
    <p>This change order was declined{#if data.closed_date}{' '}on {ctx.fmtDate(data.closed_date)}{/if}.</p>
  {:else if data.status === 'accepted'}
    <p>You approved this change order{#if data.closed_date}{' '}on {ctx.fmtDate(data.closed_date)}{/if}. Thank you.</p>
  {:else if data.closed_message}
    <p>{data.closed_message}</p>
  {:else}
    <p class="lead">Here is a proposed change to your order. Lines we'd
      <span class="tag-add">add</span>, <span class="tag-chg">change</span>, or
      <span class="tag-rm">remove</span> are marked below.</p>
  {/if}

  {#if data.deliverables && data.deliverables.length}
    <h2>What you'll receive</h2>
    <table border="1">
      <thead><tr><th>Item</th><th>Qty</th><th>Units</th></tr></thead>
      <tbody>
        {#each data.deliverables as d}
          <tr class={`row-${d.kind}`}>
            <td>{#if d.kind === 'added'}<span class="tag-add">+</span>{/if}{d.description}</td>
            <td>{d.qty}</td><td>{d.units}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  <h2>Changes to your order</h2>
  <table border="1">
    <thead><tr><th>#</th><th>Description</th><th>Qty</th><th>Units</th><th>Price</th><th>Amount</th></tr></thead>
    <tbody>
      {#each data.line_rows as r}
        <tr class={`row-${r.kind}`}>
          <td>{r.line_number ?? ''}</td>
          <td>{#if r.kind === 'added'}<span class="tag-add">+</span>{/if}{r.description}</td>
          <td>{r.qty ?? ''}</td><td>{r.units}</td>
          <td>${r.price}</td><td>${r.amount}</td>
        </tr>
      {/each}
    </tbody>
    <tfoot>
      <tr><td colspan="5">Previous total</td><td>${data.prior_total}</td></tr>
      <tr><td colspan="5"><strong>New total</strong></td><td><strong>${data.proposed_total}</strong></td></tr>
      <tr><td colspan="5">Change</td><td>{fmtDiff(data.diff_total)}</td></tr>
    </tfoot>
  </table>
{/snippet}

<PortalDocument
  apiPath="change-orders"
  notAvailableText="This change order is not available."
  loadFailedText="Could not load this change order."
  acceptLabel="Approve change"
  declineLabel="Decline change"
  acceptLegend="Confirm approval"
  acceptMessage="Approving this change order authorizes the adjustments shown above."
  acceptConfirmLabel="Yes, approve"
  changesMessage="Tell us what you'd like changed and we'll send you a revised change order. This keeps the change open — it isn't declined."
  declineMessage="Declining leaves your existing order unchanged. Contact us if you change your mind."
  {content}
/>

<style>
  .lead { color: #444; }
  table { border-collapse: collapse; width: 100%; margin-bottom: 1em; }
  th, td { padding: 0.3em 0.6em; text-align: left; }
  tr.row-changed { background: #fff7ed; }
  tr.row-added { background: #dcfce7; }
  tr.row-removed td, tr.row-changed-orig td { color: #9ca3af; text-decoration: line-through; }
  .tag-add { color: #166534; font-weight: 600; margin-right: 4px; }
  .tag-chg { color: #92400e; font-weight: 600; }
  .tag-rm { color: #991b1b; font-weight: 600; }
</style>
