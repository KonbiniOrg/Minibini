<script>
  // Inline reply composer — mounted on EmailDetailPage.svelte when the
  // user clicks Reply or Reply All in the action panel. Owns the form
  // state directly (via $bindable on DocumentSendForm) so mode-switches
  // between Reply and Reply All update only the CC field, preserving
  // anything the user has already typed in subject / body / to / etc.

  import { emailApi } from '../../lib/email.js';
  import DocumentSendForm from './DocumentSendForm.svelte';

  let {
    emailRecordId,
    mode,                 // 'reply' | 'reply-all'
    onClose,              // () => void
    onSent,               // () => void
  } = $props();

  let replyDefaults = $state(null);
  let loading = $state(true);
  let loadError = $state(null);

  // Form state lives here, not in DocumentSendForm, so it survives the
  // mode-toggle CC update below.
  let to = $state('');
  let cc = $state('');
  let bcc = $state('');
  let subject = $state('');
  let body = $state('');
  let extraFiles = $state([]);

  let submitting = $state(false);
  let submitError = $state(null);

  async function load() {
    loading = true;
    loadError = null;
    try {
      const defaults = await emailApi.replyDefaults(emailRecordId);
      replyDefaults = defaults;
      to = defaults.to || '';
      cc = mode === 'reply-all' ? (defaults.reply_all_cc || '') : '';
      bcc = defaults.bcc || '';
      subject = defaults.subject || '';
      body = defaults.body || '';
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  // Mid-compose mode switch: only the CC value changes. Everything else
  // the user has typed stays. Tracks the last-applied mode so we only
  // flip CC when the prop actually changes (not on every reactive read).
  let lastAppliedMode = $state(null);
  $effect(() => {
    if (replyDefaults && lastAppliedMode !== null && mode !== lastAppliedMode) {
      cc = mode === 'reply-all' ? (replyDefaults.reply_all_cc || '') : '';
    }
    lastAppliedMode = mode;
  });

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
      fd.append('in_reply_to', replyDefaults?.in_reply_to || '');
      fd.append('references', replyDefaults?.references || '');
      const ia = replyDefaults?.inherit_associations || {};
      if (ia.job) fd.append('inherit_job', String(ia.job));
      if (ia.purchase_order) fd.append('inherit_purchase_order', String(ia.purchase_order));
      for (const file of payload.extraFiles) {
        fd.append('attachments', file);
      }
      await emailApi.reply(emailRecordId, fd);
      if (onSent) onSent();
    } catch (e) {
      submitError = e.message;
      submitting = false;
    }
  }

  $effect(() => {
    void emailRecordId;
    load();
  });
</script>

<section class="composer">
  <div class="composer-header">
    <h3>{mode === 'reply-all' ? 'Reply All' : 'Reply'}</h3>
    <button type="button" class="cancel" onclick={onClose}>Cancel</button>
  </div>

  {#if loading}
    <p>Loading…</p>
  {:else if loadError}
    <p class="error"><strong>Error:</strong> {loadError}</p>
  {:else if replyDefaults}
    <DocumentSendForm
      sendDefaults={{
        cc: '',
        bcc: '',
        subject: '',
        body: '',
        attachments_preview: [],
      }}
      bind:to
      bind:cc
      bind:bcc
      bind:subject
      bind:body
      bind:extraFiles
      submitLabel="Send"
      {submitting}
      {submitError}
      onSubmit={handleSubmit}
    />
  {/if}
</section>

<style>
  .composer {
    border: 1px solid #d1d5db;
    border-radius: 4px;
    padding: 12px;
    background: #fff;
    margin-bottom: 16px;
  }
  .composer-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
  }
  .composer-header h3 {
    margin: 0;
    font-size: 16px;
  }
  .cancel {
    font-size: 13px;
  }
  .error { color: #b91c1c; }
</style>
