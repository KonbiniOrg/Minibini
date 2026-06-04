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
      data = await api.get(`/api/portal/estimates/${encodeURIComponent(token)}/`);
    } catch (e) {
      error = e.status === 404 ? 'This estimate is not available.'
                               : (e.message || 'Could not load this estimate.');
    } finally {
      loading = false;
    }
  }

  async function submit(decision) {
    // decision: 'accept' | 'reject' | 'request-changes'
    submitting = true; error = '';
    try {
      const url = `/api/portal/estimates/${encodeURIComponent(token)}/${decision}/`;
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
</script>

<main class="portal">
  {#if loading}
    <p>Loading…</p>
  {:else if error}
    <p class="err">{error}</p>
  {:else if data}
    <h1>Estimate {data.estimate_number}</h1>

    {#if done === 'requested'}
      <p>Thank you — we've received your request and will send you a revised estimate shortly.</p>
    {:else if data.status === 'superseded'}
      <p>A newer version of this estimate has been issued.
        {#if data.current_token}
          <a href={`/portal/?token=${data.current_token}`}>View the current estimate</a>.
        {/if}
      </p>
    {:else if data.status === 'expired'}
      <p>This estimate expired{#if data.expiration_date} on {fmtDate(data.expiration_date)}{/if}. Please contact us.</p>
    {:else if data.status === 'rejected'}
      <p>This estimate was declined{#if data.closed_date} on {fmtDate(data.closed_date)}{/if}.</p>
    {:else if data.status === 'accepted'}
      <p>You accepted this estimate{#if data.closed_date} on {fmtDate(data.closed_date)}{/if}. Thank you.</p>
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
          <tr><td>{li.description}</td><td>{li.qty ?? ''}</td><td>{li.units}</td>
            <td>${li.price}</td><td>${li.amount}</td></tr>
        {/each}
      </tbody>
      <tfoot><tr><td colspan="4"><strong>Total</strong></td><td><strong>${data.grand_total}</strong></td></tr></tfoot>
    </table>

    {#if canAct && !done}
      <p>
        <button type="button" onclick={() => confirming = 'accept'}>Accept estimate</button>
        <button type="button" onclick={() => confirming = 'changes'}>Request changes</button>
        <button type="button" onclick={() => confirming = 'reject'}>Decline estimate</button>
      </p>
    {/if}

    {#if confirming === 'accept'}
      <fieldset>
        <legend><strong>Confirm acceptance</strong></legend>
        <p>Accepting this estimate authorizes us to begin the work it describes.</p>
        <button type="button" disabled={submitting} onclick={() => submit('accept')}>Yes, accept</button>
        <button type="button" onclick={() => confirming = ''}>Cancel</button>
      </fieldset>
    {:else if confirming === 'changes'}
      <fieldset>
        <legend><strong>Request changes</strong></legend>
        <p>Tell us what you'd like changed and we'll send you a revised estimate. This
          keeps your job open — it isn't declined.</p>
        <p><label>What would you like changed?<br><textarea bind:value={changesComment}></textarea></label></p>
        <button type="button" disabled={submitting} onclick={() => submit('request-changes')}>Send request</button>
        <button type="button" onclick={() => confirming = ''}>Cancel</button>
      </fieldset>
    {:else if confirming === 'reject'}
      <fieldset>
        <legend><strong>Confirm decline</strong></legend>
        <p>Declining this estimate closes out this job. Contact us if you change your mind.</p>
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
  table { border-collapse: collapse; width: 100%; margin-bottom: 1em; }
  th, td { padding: 0.3em 0.6em; text-align: left; }
</style>
