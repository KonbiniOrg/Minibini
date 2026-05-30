<script>
  import { querystring, push } from 'svelte-spa-router';
  import { emailApi } from '../../lib/email.js';
  import DocumentSendForm from '../../components/email/DocumentSendForm.svelte';

  const { params = {} } = $props();

  let parentEmail = $state(null);
  let replyDefaults = $state(null);
  let sendDefaults = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let submitting = $state(false);
  let submitError = $state(null);

  // Reply mode vs Reply-All mode is read from the route query string.
  const isReplyAll = $derived(new URLSearchParams($querystring).get('mode') === 'all');

  async function load() {
    loading = true;
    loadError = null;
    try {
      const [email, defaults] = await Promise.all([
        emailApi.get(params.id),
        emailApi.replyDefaults(params.id),
      ]);
      parentEmail = email;
      replyDefaults = defaults;

      // Build the shape DocumentSendForm expects, plugging in either the
      // blank cc (Reply) or the computed reply_all_cc (Reply All).
      sendDefaults = {
        to: defaults.to || '',
        cc: isReplyAll ? defaults.reply_all_cc : (defaults.cc || ''),
        bcc: defaults.bcc || '',
        subject: defaults.subject || '',
        body: defaults.body || '',
        attachments_preview: [],
      };
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
      fd.append('in_reply_to', replyDefaults.in_reply_to || '');
      fd.append('references', replyDefaults.references || '');
      const ia = replyDefaults.inherit_associations || {};
      if (ia.job) fd.append('inherit_job', String(ia.job));
      if (ia.purchase_order) fd.append('inherit_purchase_order', String(ia.purchase_order));
      if (ia.bill) fd.append('inherit_bill', String(ia.bill));
      for (const file of payload.extraFiles) {
        fd.append('attachments', file);
      }
      await emailApi.reply(params.id, fd);
      push(`/email/${params.id}`);
    } catch (e) {
      submitError = e.message;
      submitting = false;
    }
  }

  $effect(() => {
    void params.id;
    void $querystring;
    load();
  });
</script>

<p><a href="#/email/{params.id}">&larr; Cancel and return to email</a></p>

<h2>{isReplyAll ? 'Reply All' : 'Reply'}</h2>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else if sendDefaults}
  <DocumentSendForm
    {sendDefaults}
    submitLabel="Send"
    {submitting}
    {submitError}
    onSubmit={handleSubmit}
  />

  <hr>

  <section class="parent-ref">
    <h3>Original message</h3>
    {#if parentEmail?.temp_email}
      <table border="1">
        <tbody>
          <tr><th>From:</th><td>{parentEmail.temp_email.from_email}</td></tr>
          <tr><th>To:</th><td>{parentEmail.temp_email.to_email}</td></tr>
          {#if parentEmail.temp_email.cc_email}
            <tr><th>CC:</th><td>{parentEmail.temp_email.cc_email}</td></tr>
          {/if}
          <tr><th>Subject:</th><td><strong>{parentEmail.temp_email.subject}</strong></td></tr>
          <tr><th>Date:</th><td>{new Date(parentEmail.temp_email.date_sent).toLocaleString()}</td></tr>
        </tbody>
      </table>
      {#if parentEmail.temp_email.text_body}
        <pre class="original-body">{parentEmail.temp_email.text_body}</pre>
      {/if}
    {:else}
      <p><em>(Original email metadata unavailable.)</em></p>
    {/if}
  </section>
{/if}

<style>
  .parent-ref { color: #555; }
  .parent-ref table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  .parent-ref th, .parent-ref td { padding: 4px 8px; }
  .original-body {
    white-space: pre-wrap;
    margin-top: 8px;
    padding: 8px;
    background: #f5f5f5;
    font-family: inherit;
    font-size: 13px;
  }
</style>
