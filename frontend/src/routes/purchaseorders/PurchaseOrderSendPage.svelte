<script>
  import { api } from '../../lib/api.js';
  import { push } from 'svelte-spa-router';
  import DocumentSendForm from '../../components/email/DocumentSendForm.svelte';

  const { params = {} } = $props();

  let po = $state(null);
  let lineItems = $state([]);
  let sendDefaults = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let submitting = $state(false);
  let submitError = $state(null);

  async function load() {
    loading = true;
    loadError = null;
    try {
      const [poData, defaults] = await Promise.all([
        api.get(`/api/purchase-orders/${params.id}/`),
        api.get(`/api/purchase-orders/${params.id}/send-defaults/`),
      ]);
      po = poData;
      lineItems = poData.line_items || [];
      sendDefaults = defaults;
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(payload) {
    submitting = true;
    submitError = null;
    try {
      const fd = new FormData();
      fd.append('to', payload.to);
      fd.append('cc', payload.cc);
      fd.append('bcc', payload.bcc);
      fd.append('subject', payload.subject);
      fd.append('body', payload.body);
      for (const file of payload.extraFiles) {
        fd.append('attachments', file);
      }
      await api.postMultipart(`/api/purchase-orders/${params.id}/send/`, fd);
      push(`/purchase-orders/${params.id}`);
    } catch (e) {
      submitError = e.message;
      submitting = false;
    }
  }

  function total(items) {
    return items.reduce((acc, li) => acc + Number(li.qty || 0) * Number(li.price || 0), 0);
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

<p><a href="#/purchase-orders/{params.id}">&larr; Cancel and return to Purchase Order</a></p>

<h2>Send Purchase Order</h2>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else if po && sendDefaults}
  <DocumentSendForm
    {sendDefaults}
    submitLabel="Send Email"
    {submitting}
    {submitError}
    onSubmit={handleSubmit}
  />

  <hr>

  <section class="doc-ref">
    <h3>Purchase Order {po.po_number}</h3>
    <p><strong>Status:</strong> {po.status}</p>
    <p><strong>Vendor:</strong> {po.business_name || ''}</p>

    <table border="1">
      <thead>
        <tr><th>#</th><th>Description</th><th>Qty</th><th>Unit</th><th>Price</th><th>Total</th></tr>
      </thead>
      <tbody>
        {#each lineItems as li}
          <tr>
            <td>{li.line_number}</td>
            <td>{li.description}</td>
            <td>{li.qty}</td>
            <td>{li.units}</td>
            <td>${Number(li.price).toFixed(2)}</td>
            <td>${(Number(li.qty) * Number(li.price)).toFixed(2)}</td>
          </tr>
        {/each}
        <tr>
          <td colspan="5"><strong>Total</strong></td>
          <td><strong>${total(lineItems).toFixed(2)}</strong></td>
        </tr>
      </tbody>
    </table>
  </section>
{/if}

<style>
  .doc-ref { color: #555; }
  .doc-ref table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  .doc-ref th, .doc-ref td { padding: 4px 8px; }
</style>
