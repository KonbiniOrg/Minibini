<script>
  import { api } from './lib/api.js';

  let data = $state(null);
  let loading = $state(true);
  let error = $state('');
  let confirming = $state('');   // '' | 'accept' | 'reject' | 'changes'
  let rejectReason = $state('');
  let changesComment = $state('');
  let submitting = $state(false);
  let done = $state('');         // '' | 'accepted' | 'declined' | 'requested'

  const token = new URLSearchParams(window.location.search).get('token') || '';

  async function load() {
    loading = true; error = '';
    try {
      data = await api.get(`/api/portal/change-orders/${encodeURIComponent(token)}/`);
    } catch (e) {
      error = e.status === 404 ? 'This change order is not available.'
                               : (e.message || 'Could not load this change order.');
    } finally {
      loading = false;
    }
  }

  async function submit(decision) {
    // decision: 'accept' | 'reject' | 'request-changes'
    submitting = true; error = '';
    try {
      const url = `/api/portal/change-orders/${encodeURIComponent(token)}/${decision}/`;
      let body = null;
      if (decision === 'reject') body = { reason: rejectReason };
      else if (decision === 'request-changes') body = { reason: changesComment };
      data = await api.post(url, body);
      done = decision === 'accept' ? 'accepted'
           : decision === 'reject' ? 'declined'
           : 'requested';
      confirming = '';
    } catch (e) {
      error = e.message || 'Something went wrong. Please contact us.';
    } finally {
      submitting = false;
    }
  }

  $effect(() => { if (token) load(); else { loading = false; error = 'Missing link token.'; } });

  const canAct = $derived(data && data.actions && data.actions.includes('accept'));

  function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d) ? iso
      : d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
  }

  function fmtDiff(s) {
    const v = Number(s ?? 0);
    if (v === 0) return '$0.00';
    return (v > 0 ? '+' : '−') + `$${Math.abs(v).toFixed(2)}`;
  }
</script>

<main class="portal">
  {#if loading}
    <p>Loading…</p>
  {:else if error}
    <p class="err">{error}</p>
  {:else if data}
    <h1>Change order {data.change_order_number}</h1>

    {#if done === 'requested'}
      <p>Thank you — we've received your request and will send you a revised change order shortly.</p>
    {:else if data.status === 'superseded'}
      <p>A newer version of this change order has been issued.
        {#if data.current_token}
          <a href={`/portal/?token=${data.current_token}&doc=change_order`}>View the current change order</a>.
        {/if}
      </p>
    {:else if data.status === 'expired'}
      <p>This change order expired{#if data.expiration_date}{' '}on {fmtDate(data.expiration_date)}{/if}. Please contact us.</p>
    {:else if data.status === 'rejected'}
      <p>This change order was declined{#if data.closed_date}{' '}on {fmtDate(data.closed_date)}{/if}.</p>
    {:else if data.status === 'accepted'}
      <p>You approved this change order{#if data.closed_date}{' '}on {fmtDate(data.closed_date)}{/if}. Thank you.</p>
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

    {#if canAct && !done}
      <p>
        <button type="button" onclick={() => confirming = 'accept'}>Approve change</button>
        <button type="button" onclick={() => confirming = 'changes'}>Request changes</button>
        <button type="button" onclick={() => confirming = 'reject'}>Decline change</button>
      </p>
    {/if}

    {#if confirming === 'accept'}
      <fieldset>
        <legend><strong>Confirm approval</strong></legend>
        <p>Approving this change order authorizes the adjustments shown above.</p>
        <button type="button" disabled={submitting} onclick={() => submit('accept')}>Yes, approve</button>
        <button type="button" onclick={() => confirming = ''}>Cancel</button>
      </fieldset>
    {:else if confirming === 'changes'}
      <fieldset>
        <legend><strong>Request changes</strong></legend>
        <p>Tell us what you'd like changed and we'll send you a revised change order. This
          keeps the change open — it isn't declined.</p>
        <p><label>What would you like changed?<br><textarea bind:value={changesComment}></textarea></label></p>
        <button type="button" disabled={submitting} onclick={() => submit('request-changes')}>Send request</button>
        <button type="button" onclick={() => confirming = ''}>Cancel</button>
      </fieldset>
    {:else if confirming === 'reject'}
      <fieldset>
        <legend><strong>Confirm decline</strong></legend>
        <p>Declining leaves your existing order unchanged. Contact us if you change your mind.</p>
        <p><label>Reason (optional)<br><textarea bind:value={rejectReason}></textarea></label></p>
        <button type="button" disabled={submitting} onclick={() => submit('reject')}>Yes, decline</button>
        <button type="button" onclick={() => confirming = ''}>Cancel</button>
      </fieldset>
    {/if}
  {/if}
</main>

<style>
  .portal { max-width: 720px; margin: 2em auto; font-family: sans-serif; }
  .err { color: #b00; }
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
