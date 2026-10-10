<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { push } from 'svelte-spa-router';
  import DocumentSendForm from '../../components/email/DocumentSendForm.svelte';
  import LoadState from '../../components/LoadState.svelte';

  const { params = {} } = $props();

  let co = $state(null);
  let sendDefaults = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let submitting = $state(false);
  let submitError = $state(null);

  async function load() {
    loading = true;
    loadError = null;
    try {
      const [order, defaults] = await Promise.all([
        api.get(`/api/change-orders/${params.id}/`),
        api.get(`/api/change-orders/${params.id}/send-defaults/`),
      ]);
      co = order;
      sendDefaults = defaults;
    } catch (e) {
      loadError = errorMessage(e, 'Could not load change order.');
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
      await api.postMultipart(`/api/change-orders/${params.id}/send/`, fd);
      push(`/change-orders/${params.id}`);
    } catch (e) {
      submitError = e.message;
      submitting = false;
    }
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

<div class="page-body">
<p><a href="#/change-orders/{params.id}">&larr; Cancel and return to change order</a></p>

<h2>Send change order to customer</h2>

<LoadState {loading} error={loadError}>
{#if co && sendDefaults}
  <DocumentSendForm
    {sendDefaults}
    submitLabel="Send Email"
    {submitting}
    {submitError}
    onSubmit={handleSubmit}
  />

  <hr>

  <section class="doc-ref">
    <h3>Change order {co.change_order_number}</h3>
    <p><strong>Status:</strong> {co.status}</p>
    <p>The customer receives a link to review and approve the change online,
      plus a PDF of the change order.</p>
  </section>
{/if}
</LoadState>
</div>

<style>
  .doc-ref { color: #555; }
</style>
