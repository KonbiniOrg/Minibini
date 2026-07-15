<script>
  import { api } from '../../lib/api.js';
  import { emailApi, resolveSenderToContact } from '../../lib/email.js';
  import SenderResolutionForm from '../../components/email/SenderResolutionForm.svelte';
  import DuplicateContactModal from '../../components/contacts/DuplicateContactModal.svelte';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let loading = $state(true);
  let loadError = $state(null);
  let senderInfo = $state(null);
  let resolutionState = $state(null);

  let submitting = $state(false);
  let submitError = $state(null);
  let duplicateContact = $state(null);

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
    duplicateContact = null;
    submitting = true;
    try {
      const { contactId, businessId } = await resolveSenderToContact(resolutionState);
      let vendorBusinessId = businessId;
      if (!vendorBusinessId) {
        const contact = await api.get(`/api/contacts/${contactId}/`);
        vendorBusinessId = contact.business || contact.business_id;
      }
      if (!vendorBusinessId) {
        throw new Error('A vendor Business is required to create a Bill. Pick or create one for this contact.');
      }
      // Tier 1: if this email was a vendor reply to a PO (reply-correlated),
      // the EmailRecord already carries purchase_order. Fetch it and pre-select
      // the PO on the bill form so the user doesn't have to pick it manually.
      const emailRecord = await emailApi.get(params.id);
      const poId = emailRecord?.purchase_order;
      const poParam = poId ? `&po=${poId}` : '';
      push(`/bills/new?email=${params.id}&vendor=${vendorBusinessId}${poParam}`);
    } catch (err) {
      if (err.status === 409 && err.data?.code === 'duplicate_email') {
        duplicateContact = err.data.existing_contact;
      } else {
        submitError = err.message;
      }
      submitting = false;
    }
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

<div class="page-body">
<h2>Create Bill from Email</h2>

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
        {submitting ? 'Working…' : 'Continue to Bill Details'}
      </button>
      <a href="#/email/{params.id}">Cancel</a>
    </p>
    <p><small>You'll fill in the bill details (amount, dates, line items) on the next page.</small></p>
  </form>
  <DuplicateContactModal
    open={!!duplicateContact}
    contact={duplicateContact}
    onViewExisting={() => push(`/contacts/${duplicateContact.contact_id}`)}
    onClose={() => { duplicateContact = null; }}
  />
{/if}
</div>
