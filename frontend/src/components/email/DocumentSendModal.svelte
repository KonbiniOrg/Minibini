<script>
  // The send step for estimates / change orders / invoices, in Modal over
  // the document panel (replaces the three *SendPage routes, 2026-10-10 —
  // the standing "send buttons navigate" exception in CLAUDE.md is now
  // moot). The panel passes URLs; this owns the defaults fetch, the
  // multipart POST, and error rendering. `beforeSubmit` is the invoice
  // panel's hook for its unapplied-deposit-credit confirm — it runs AFTER
  // DocumentSendForm's own "Send this email to …?" confirm.
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import Modal from '../Modal.svelte';
  import LoadState from '../LoadState.svelte';
  import DocumentSendForm from './DocumentSendForm.svelte';

  let {
    open = false,
    label = 'Send',
    title = 'Send',
    defaultsUrl,
    sendUrl,
    submitLabel = 'Send Email',
    beforeSubmit = async () => true,
    onSent = () => {},
    onClose = () => {},
  } = $props();

  let sendDefaults = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let submitting = $state(false);
  let submitError = $state(null);

  async function load() {
    loading = true; loadError = null; sendDefaults = null;
    try { sendDefaults = await api.get(defaultsUrl); }
    catch (e) { loadError = errorMessage(e, 'Could not load the email defaults.'); }
    finally { loading = false; }
  }

  $effect(() => {
    if (open && defaultsUrl) { submitError = null; submitting = false; load(); }
  });

  async function handleSubmit(payload) {
    if (!(await beforeSubmit())) return;
    submitting = true; submitError = null;
    try {
      const fd = new FormData();
      fd.append('to', payload.to);
      fd.append('cc', payload.cc);
      fd.append('bcc', payload.bcc);
      fd.append('subject', payload.subject);
      fd.append('body', payload.body);
      // Only user-uploaded extras; the document's own PDF is attached
      // server-side.
      for (const file of payload.extraFiles) fd.append('attachments', file);
      await api.postMultipart(sendUrl, fd);
      onSent();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay); else submitError = t.message;
    } finally {
      submitting = false;
    }
  }
</script>

<!-- Enter is owned by DocumentSendForm's native <form>; the shell only wires Escape. -->
<Modal {open} onCancel={onClose} maxWidth="780px" {label}>
  <h3 class="modal-title">{title}</h3>
  <LoadState {loading} error={loadError}>
    {#if sendDefaults}
      <DocumentSendForm {sendDefaults} {submitLabel} {submitting} {submitError}
        onSubmit={handleSubmit} onCancel={onClose} />
    {/if}
  </LoadState>
</Modal>

<style>
  .modal-title { margin: 0 0 12px; font-size: 16px; }
</style>
