<script>
  import { api } from '../../lib/api.js';
  import { push } from 'svelte-spa-router';
  import DocumentSendForm from '../../components/email/DocumentSendForm.svelte';

  const { params = {} } = $props();

  let estimate = $state(null);
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
      const [est, defaults] = await Promise.all([
        api.get(`/api/estimates/${params.id}/`),
        api.get(`/api/estimates/${params.id}/send-defaults/`),
      ]);
      estimate = est;
      lineItems = est.line_items || [];
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
      // Only include user-uploaded extras; auto-attachments are server-side.
      // (Estimate page has a single auto-attached PDF; unchecking it isn't
      // honored in this round because the backend always attaches the doc
      // PDF. Refine if needed.)
      for (const file of payload.extraFiles) {
        fd.append('attachments', file);
      }
      const result = await api.postMultipart(`/api/estimates/${params.id}/send/`, fd);
      // Success — back to the estimate detail page.
      push(`/estimates/${params.id}`);
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

<div class="page-body">
<p><a href="#/estimates/{params.id}">&larr; Cancel and return to Estimate</a></p>

<h2>Send Estimate</h2>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else if estimate && sendDefaults}
  <DocumentSendForm
    {sendDefaults}
    submitLabel="Send Email"
    {submitting}
    {submitError}
    onSubmit={handleSubmit}
  />

  <hr>

  <section class="doc-ref">
    <h3>Estimate {estimate.estimate_number}</h3>
    <p><strong>Status:</strong> {estimate.status}</p>
    {#if estimate.expiration_date}
      <p><strong>Valid until:</strong> {new Date(estimate.expiration_date).toLocaleDateString()}</p>
    {/if}

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
</div>

<style>
  .doc-ref { color: #555; }
  .doc-ref table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  .doc-ref th, .doc-ref td { padding: 4px 8px; }
</style>
