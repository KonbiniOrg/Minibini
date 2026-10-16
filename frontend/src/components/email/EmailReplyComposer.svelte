<script>
  // Reply composer, in Modal over the email (2026-10-10; was inline above
  // the message) — mounted by EmailDetailPage.svelte while the user has
  // clicked Reply or Reply All in the action panel. Owns the form state
  // directly (via $bindable on DocumentSendForm) so mode-switches between
  // Reply and Reply All update only the CC field, preserving anything the
  // user has already typed in subject / body / to / etc.

  import { emailApi } from '../../lib/email.js';
  import DocumentSendForm from './DocumentSendForm.svelte';
  import Modal from '../Modal.svelte';
  import LoadState from '../LoadState.svelte';
  import { errorMessage } from '../../lib/api.js';

  let {
    emailRecordId,
    mode,                 // 'reply' | 'reply-all'
    onClose,              // () => void
    onSent,               // () => void
    onModeChange = () => {}, // (mode) => void — the in-modal Reply / Reply All toggle
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
      loadError = errorMessage(e, 'Could not load reply defaults.');
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

<!-- Enter is owned by DocumentSendForm's native <form>; the shell only wires Escape. -->
<Modal open={true} onCancel={onClose} maxWidth="780px" label={mode === 'reply-all' ? 'Reply All' : 'Reply'}>
  <div class="composer-header">
    <h3 class="modal-title">{mode === 'reply-all' ? 'Reply All' : 'Reply'}</h3>
    <!-- Mode toggle lives in here now: the action panel's own Reply /
         Reply All buttons sit behind the overlay while composing. -->
    <span class="mode-toggle">
      <button type="button" class="mode" aria-pressed={mode === 'reply'}
        onclick={() => onModeChange('reply')}>Reply</button>
      <button type="button" class="mode" aria-pressed={mode === 'reply-all'}
        onclick={() => onModeChange('reply-all')}>Reply All</button>
    </span>
  </div>

  <LoadState {loading} error={loadError}>
  {#if replyDefaults}
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
      onCancel={onClose}
    />
  {/if}
  </LoadState>
</Modal>

<style>
  .composer-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
  .modal-title { margin: 0; font-size: 16px; }
  .mode-toggle { display: inline-flex; gap: 4px; }
  .mode { font-size: 13px; }
  .mode[aria-pressed="true"] { font-weight: 600; background: #e5e7eb; }
</style>
