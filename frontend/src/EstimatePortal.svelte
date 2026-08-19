<script>
  import PortalDocument from './components/PortalDocument.svelte';
</script>

{#snippet content(data, ctx)}
  <h1>Estimate {data.estimate_number}</h1>

  {#if ctx.done === 'requested'}
    <p>Thank you — we've received your request and will send you a revised estimate shortly.</p>
  {:else if data.status === 'superseded'}
    <p>A newer version of this estimate has been issued.
      {#if data.current_token}
        <a href={`/portal/?token=${data.current_token}&doc=estimate`}>View the current estimate</a>.
      {/if}
    </p>
  {:else if data.status === 'expired'}
    <p>This estimate expired{#if data.expiration_date}{' '}on {ctx.fmtDate(data.expiration_date)}{/if}. Please contact us.</p>
  {:else if data.status === 'rejected'}
    <p>This estimate was declined{#if data.closed_date}{' '}on {ctx.fmtDate(data.closed_date)}{/if}.</p>
  {:else if data.status === 'accepted'}
    <p>You accepted this estimate{#if data.closed_date}{' '}on {ctx.fmtDate(data.closed_date)}{/if}. Thank you.</p>
  {:else if data.closed_message}
    <p>{data.closed_message}</p>
  {/if}

  {#if data.deliverables && data.deliverables.length}
    <h2>What you'll receive</h2>
    <table border="1">
      <thead><tr><th>Item</th><th>Qty</th><th>Units</th></tr></thead>
      <tbody>
        {#each data.deliverables as d}
          <tr><td>{d.description}</td><td>{d.qty_ordered}</td><td>{d.units}</td></tr>
        {/each}
      </tbody>
    </table>
  {/if}

  <h2>Estimate detail</h2>
  <table border="1">
    <thead><tr><th>Description</th><th>Qty</th><th>Units</th><th>Price</th><th>Amount</th></tr></thead>
    <tbody>
      {#each data.line_items as li}
        <tr><td class="preserve-breaks">{li.description}</td><td>{li.qty ?? ''}</td><td>{li.units}</td>
          <td>${li.price}</td><td>${li.amount}</td></tr>
      {/each}
    </tbody>
    <tfoot><tr><td colspan="4"><strong>Total</strong></td><td><strong>${data.grand_total}</strong></td></tr></tfoot>
  </table>
{/snippet}

<PortalDocument
  apiPath="estimates"
  notAvailableText="This estimate is not available."
  loadFailedText="Could not load this estimate."
  acceptLabel="Accept estimate"
  declineLabel="Decline estimate"
  acceptLegend="Confirm acceptance"
  acceptMessage="Accepting this estimate authorizes us to begin the work it describes."
  acceptConfirmLabel="Yes, accept"
  changesMessage="Tell us what you'd like changed and we'll send you a revised estimate. This keeps your job open — it isn't declined."
  declineMessage="Declining this estimate closes out this job. Contact us if you change your mind."
  {content}
/>

<style>
  table { border-collapse: collapse; width: 100%; margin-bottom: 1em; }
  th, td { padding: 0.3em 0.6em; text-align: left; }
</style>
