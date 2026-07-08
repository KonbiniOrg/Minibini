<script>
  import { api } from '../../lib/api.js';
  import { emailApi, resolveSenderToContact } from '../../lib/email.js';
  import SenderResolutionForm from '../../components/email/SenderResolutionForm.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let loading = $state(true);
  let loadError = $state(null);
  let senderInfo = $state(null);
  let resolutionState = $state(null);

  let submitting = $state(false);
  let submitError = $state(null);

  async function load() {
    loading = true;
    loadError = null;
    try {
      senderInfo = await emailApi.senderInfo(params.id);
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    submitError = null;
    submitting = true;
    try {
      const { contactId, businessId } = await resolveSenderToContact(resolutionState);
      // PO requires a Business as vendor. The resolution always produces a
      // Business (either pre-existing on the contact or newly created), so if
      // we have none, surface the gap rather than 500 the API.
      let vendorBusinessId = businessId;
      if (!vendorBusinessId) {
        // Fetch the contact to pick up its business.
        const contact = await api.get(`/api/contacts/${contactId}/`);
        vendorBusinessId = contact.business || contact.business_id;
      }
      if (!vendorBusinessId) {
        throw new Error('A vendor Business is required to create a PO. Pick or create one for this contact.');
      }
      const result = await emailApi.createPo(params.id, { vendor_business_id: vendorBusinessId });
      push(`/purchase-orders/${result.po_id}`);
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

<div class="page-body">
<h2>Create Purchase Order from Email</h2>

<p><a href="#/email/{params.id}">&larr; Back to Email</a></p>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else if senderInfo}
  {#if submitError}
    <p><strong>Error:</strong> {submitError}</p>
  {/if}

  <form onsubmit={handleSubmit}>
    <SenderResolutionForm {senderInfo} bind:state={resolutionState} />

    <p>
      <button type="submit" disabled={submitting}>
        {submitting ? 'Creating…' : 'Create Purchase Order'}
      </button>
      <a href="#/email/{params.id}">Cancel</a>
    </p>
    <p><small>Line items can be added on the PO detail page after creation.</small></p>
  </form>
{/if}
</div>
