<script>
  import { querystring, push } from 'svelte-spa-router';
  import { emailApi } from '../../lib/email.js';
  import DocumentSendForm from '../../components/email/DocumentSendForm.svelte';
  import EmailContent from '../../components/email/EmailContent.svelte';

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
    <EmailContent
      content={parentEmail?.content}
      tempEmail={parentEmail?.temp_email}
      emailRecord={parentEmail}
      contactLinks={parentEmail?.contact_links}
    />
  </section>
{/if}

<style>
  .parent-ref { color: #555; }
</style>
