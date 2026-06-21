<script>
  import { emailApi } from '../../lib/email.js';
  import { push } from 'svelte-spa-router';
  import PurchaseOrderPicker from '../../components/PurchaseOrderPicker.svelte';

  const { params = {} } = $props();

  let email = $state(null);
  let selectedPoId = $state('');
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
    if (!selectedPoId) {
      submitError = 'Please select a purchase order.';
      return;
    }
    submitting = true;
    submitError = null;
    try {
      await emailApi.linkToPo(params.id, selectedPoId);
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

<h2>Associate Email with Existing Purchase Order</h2>

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

  <h3>Select Purchase Order</h3>

  {#if submitError}
    <p><strong>Error:</strong> {submitError}</p>
  {/if}

  <form onsubmit={handleSubmit}>
    <p>
      <label><strong>Purchase Order *</strong></label><br>
      <PurchaseOrderPicker bind:value={selectedPoId} />
    </p>

    <p>
      <button type="submit" disabled={submitting}>
        {submitting ? 'Associating…' : 'Associate Email with PO'}
      </button>
      <a href="#/email/{params.id}">Cancel</a>
    </p>
  </form>
{/if}
