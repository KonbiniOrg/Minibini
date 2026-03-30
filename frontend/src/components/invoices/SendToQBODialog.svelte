<!-- frontend/src/components/invoices/SendToQBODialog.svelte -->
<script>
  import { api } from '../../lib/api.js';

  const {
    invoiceId,
    defaultEmail = '',
    onSuccess = null,
    onCancel = null,
  } = $props();

  let sendTo = $state(defaultEmail);
  let cc = $state('');
  let bcc = $state('');
  let sending = $state(false);
  let error = $state(null);

  async function send() {
    if (!sendTo.trim()) {
      error = 'Recipient email is required';
      return;
    }
    sending = true;
    error = null;
    try {
      const result = await api.post(`/api/invoices/${invoiceId}/send-to-qbo/`, {
        send_to: sendTo.trim(),
        cc: cc.trim() || undefined,
        bcc: bcc.trim() || undefined,
      });
      if (onSuccess) onSuccess(result);
    } catch (e) {
      error = e.data?.error || e.message || 'Failed to send to QuickBooks';
    } finally {
      sending = false;
    }
  }
</script>

<fieldset>
  <legend><strong>Send to QuickBooks</strong></legend>

  {#if error}
    <p><strong>Error:</strong> {error}</p>
  {/if}

  <p><label for="send_to"><strong>Send To *</strong></label><br>
    <input type="email" id="send_to" bind:value={sendTo} required></p>

  <p><label for="cc"><strong>CC</strong></label><br>
    <input type="text" id="cc" bind:value={cc} placeholder="Comma-separated emails"></p>

  <p><label for="bcc"><strong>BCC</strong></label><br>
    <input type="text" id="bcc" bind:value={bcc} placeholder="Comma-separated emails"></p>

  <p>
    <button onclick={send} disabled={sending}>
      {sending ? 'Sending...' : 'Send Invoice to QuickBooks'}
    </button>
    {#if onCancel}
      <button onclick={onCancel} disabled={sending}>Cancel</button>
    {/if}
  </p>
</fieldset>
