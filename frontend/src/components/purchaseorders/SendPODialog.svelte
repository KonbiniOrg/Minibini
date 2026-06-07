<script>
  import { api } from '../../lib/api.js';
  import { modalKeys } from '../../lib/modalKeys.js';

  const {
    poId,
    onSuccess,
    onCancel,
  } = $props();

  let to = $state('');
  let subject = $state('');
  let body = $state('');
  let loading = $state(true);
  let sending = $state(false);
  let error = $state(null);

  async function loadDefaults() {
    loading = true;
    try {
      const defaults = await api.get(`/api/purchase-orders/${poId}/send-defaults/`);
      to = defaults.to || '';
      subject = defaults.subject || '';
      body = defaults.body || '';
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleSend(e) {
    e.preventDefault();
    sending = true;
    error = null;
    try {
      const result = await api.post(`/api/purchase-orders/${poId}/send/`, {
        to, subject, body,
      });
      onSuccess(result);
    } catch (e) {
      error = e.data ? JSON.stringify(e.data) : e.message;
    } finally {
      sending = false;
    }
  }

  loadDefaults();
</script>

<!-- Esc-only: the <form> below already submits on Enter (and its textarea keeps newlines). -->
<div class="dialog-overlay" use:modalKeys={{ onCancel }}>
  <div class="dialog">
    <h3>Send Purchase Order</h3>

    {#if loading}
      <p>Loading...</p>
    {:else}
      <form onsubmit={handleSend}>
        {#if error}
          <p class="error"><strong>Error:</strong> {error}</p>
        {/if}

        <p>
          <label for="send-to"><strong>To *</strong></label><br>
          <input type="text" id="send-to" bind:value={to} required
            placeholder="email@example.com, other@example.com"
            style="width:100%;box-sizing:border-box;">
          <small>Separate multiple addresses with commas</small>
        </p>

        <p>
          <label for="send-subject"><strong>Subject *</strong></label><br>
          <input type="text" id="send-subject" bind:value={subject} required style="width:100%;box-sizing:border-box;">
        </p>

        <p>
          <label for="send-body"><strong>Message</strong></label><br>
          <textarea id="send-body" bind:value={body} rows="6" style="width:100%;box-sizing:border-box;"></textarea>
        </p>

        <p>
          <button type="submit" disabled={sending}>{sending ? 'Sending...' : 'Send'}</button>
          <button type="button" onclick={onCancel} disabled={sending}>Cancel</button>
        </p>
      </form>
    {/if}
  </div>
</div>

<style>
  .dialog-overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0, 0, 0, 0.4); z-index: var(--z-modal);
    display: flex; align-items: center; justify-content: center;
  }
  .dialog {
    background: white; padding: 24px; border-radius: 8px;
    width: 500px; max-width: 90vw; max-height: 90vh; overflow-y: auto;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
  }
  .error { color: #dc2626; }
</style>
