<script>
  import { emailApi } from '../../lib/email.js';
  import { push } from 'svelte-spa-router';
  import BillPicker from '../../components/BillPicker.svelte';

  const { params = {} } = $props();

  let email = $state(null);
  let selectedBillId = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let submitting = $state(false);
  let submitError = $state(null);

  async function load() {
    loading = true;
    loadError = null;
    try {
      email = await emailApi.get(params.id);
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!selectedBillId) {
      submitError = 'Please select a bill.';
      return;
    }
    submitting = true;
    submitError = null;
    try {
      await emailApi.linkToBill(params.id, selectedBillId);
      push(`/email/${params.id}`);
    } catch (err) {
      submitError = err.message;
      submitting = false;
    }
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

<h2>Associate Email with Existing Bill</h2>

<p><a href="#/email/{params.id}">&larr; Back to Email</a></p>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else}
  <h3>Email Summary</h3>
  <table class="data-table">
    <tbody>
      <tr><th>From:</th><td>{email.temp_email?.from_email || email.content?.from || ''}</td></tr>
      <tr><th>Subject:</th><td><strong>{email.temp_email?.subject || email.content?.subject || ''}</strong></td></tr>
    </tbody>
  </table>

  <h3>Select Bill</h3>

  {#if submitError}
    <p><strong>Error:</strong> {submitError}</p>
  {/if}

  <form onsubmit={handleSubmit}>
    <p>
      <label><strong>Bill *</strong></label><br>
      <BillPicker bind:value={selectedBillId} />
    </p>

    <p>
      <button type="submit" disabled={submitting}>
        {submitting ? 'Associating…' : 'Associate Email with Bill'}
      </button>
      <a href="#/email/{params.id}">Cancel</a>
    </p>
  </form>
{/if}
