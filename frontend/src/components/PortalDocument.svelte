<script>
  // Shared shell for the customer-facing token portals (EstimatePortal and
  // ChangeOrderPortal): owns the token load, the confirm/submit state
  // machine, the action-button row, and the three confirmation fieldsets.
  // The document-specific rendering (heading, status messages, tables) comes
  // in as the `content` snippet; per-document copy comes in as props.
  import { api } from '../lib/api.js';

  let {
    apiPath,             // URL segment: /api/portal/<apiPath>/<token>/…
    notAvailableText,    // shown on 404
    loadFailedText,      // shown on any other load failure
    acceptLabel,         // action button, e.g. 'Accept estimate'
    declineLabel,        // action button, e.g. 'Decline estimate'
    acceptLegend,        // e.g. 'Confirm acceptance'
    acceptMessage,       // body of the accept confirmation fieldset
    acceptConfirmLabel,  // e.g. 'Yes, accept'
    changesMessage,      // body of the request-changes fieldset
    declineMessage,      // body of the decline confirmation fieldset
    content,             // snippet(data, ctx: { done, fmtDate })
  } = $props();

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
      data = await api.get(`/api/portal/${apiPath}/${encodeURIComponent(token)}/`);
    } catch (e) {
      error = e.status === 404 ? notAvailableText
                               : (e.message || loadFailedText);
    } finally {
      loading = false;
    }
  }

  async function submit(decision) {
    // decision: 'accept' | 'reject' | 'request-changes'
    submitting = true; error = '';
    try {
      const url = `/api/portal/${apiPath}/${encodeURIComponent(token)}/${decision}/`;
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
    {@render content(data, { done, fmtDate })}

    {#if canAct && !done}
      <p>
        <button type="button" onclick={() => confirming = 'accept'}>{acceptLabel}</button>
        <button type="button" onclick={() => confirming = 'changes'}>Request changes</button>
        <button type="button" onclick={() => confirming = 'reject'}>{declineLabel}</button>
      </p>
    {/if}

    {#if confirming === 'accept'}
      <fieldset>
        <legend><strong>{acceptLegend}</strong></legend>
        <p>{acceptMessage}</p>
        <button type="button" disabled={submitting} onclick={() => submit('accept')}>{acceptConfirmLabel}</button>
        <button type="button" onclick={() => confirming = ''}>Cancel</button>
      </fieldset>
    {:else if confirming === 'changes'}
      <fieldset>
        <legend><strong>Request changes</strong></legend>
        <p>{changesMessage}</p>
        <p><label>What would you like changed?<br><textarea bind:value={changesComment}></textarea></label></p>
        <button type="button" disabled={submitting} onclick={() => submit('request-changes')}>Send request</button>
        <button type="button" onclick={() => confirming = ''}>Cancel</button>
      </fieldset>
    {:else if confirming === 'reject'}
      <fieldset>
        <legend><strong>Confirm decline</strong></legend>
        <p>{declineMessage}</p>
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
</style>
