<script>
  import { api } from '../../lib/api.js';
  import { refreshSetupStatus } from '../../stores/setupStatus.js';

  // The tenant's mail account (drives both IMAP fetch and SMTP send).
  // Stored in Configuration; env settings remain the fallback until saved.
  let email_imap_server = $state('');
  let email_address = $state('');
  let email_password = $state('');   // never pre-filled; blank = keep current
  let passwordSet = $state(false);
  let email_smtp_host = $state('');
  let email_smtp_port = $state('');

  let saveMessage = $state('');
  let errors = $state({});
  let verifying = $state(false);
  let verifyResult = $state(null);

  async function load() {
    try {
      const data = await api.get('/api/settings/');
      email_imap_server = data.email_imap_server ?? '';
      email_address = data.email_address ?? '';
      passwordSet = Boolean(data.email_password);
      email_smtp_host = data.email_smtp_host ?? '';
      email_smtp_port = data.email_smtp_port ?? '';
    } catch (_) {}
  }

  async function save() {
    saveMessage = '';
    errors = {};
    const payload = {
      email_imap_server, email_address, email_smtp_host, email_smtp_port,
    };
    if (email_password !== '') payload.email_password = email_password;
    try {
      await api.patch('/api/settings/', payload);
      saveMessage = 'Email account saved.';
      if (email_password !== '') { passwordSet = true; email_password = ''; }
      refreshSetupStatus();  // ungrey the Email area immediately
    } catch (err) {
      errors = (err.data && typeof err.data === 'object')
        ? err.data : { _general: err.message || 'Save failed' };
    }
  }

  async function verify() {
    verifying = true;
    verifyResult = null;
    try {
      verifyResult = await api.post('/api/settings/email-verify/', {});
      refreshSetupStatus();
    } catch (err) {
      verifyResult = {
        imap: { ok: false, error: err.message || 'Verify failed' },
        smtp: { ok: false, error: err.message || 'Verify failed' },
      };
    } finally {
      verifying = false;
    }
  }

  load();
</script>

<fieldset class="block">
  <legend><strong>Email account</strong></legend>
  <p><small>The mailbox Minibini fetches from and sends as. One account
    drives both directions.</small></p>
  <p>
    <label><strong>Email address</strong><br>
      <input type="email" bind:value={email_address}>
    </label>
    {#if errors.email_address}<em class="err">{errors.email_address}</em>{/if}
  </p>
  <p>
    <label><strong>Password</strong><br>
      <input type="password" bind:value={email_password}
             placeholder={passwordSet ? '(unchanged)' : ''}>
    </label>
    {#if errors.email_password}<em class="err">{errors.email_password}</em>{/if}
  </p>
  <p>
    <label><strong>IMAP server</strong><br>
      <input type="text" bind:value={email_imap_server} placeholder="imap.gmail.com">
    </label>
    {#if errors.email_imap_server}<em class="err">{errors.email_imap_server}</em>{/if}
  </p>
  <p>
    <label><strong>SMTP host</strong><br>
      <input type="text" bind:value={email_smtp_host} placeholder="smtp.gmail.com">
    </label>
    {#if errors.email_smtp_host}<em class="err">{errors.email_smtp_host}</em>{/if}
  </p>
  <p>
    <label><strong>SMTP port</strong><br>
      <input type="number" class="num" bind:value={email_smtp_port} placeholder="587">
    </label>
    {#if errors.email_smtp_port}<em class="err">{errors.email_smtp_port}</em>{/if}
  </p>
  <p>
    <button type="button" onclick={save}>Save email account</button>
    <button type="button" onclick={verify} disabled={verifying}>
      {verifying ? 'Verifying…' : 'Verify connection'}
    </button>
  </p>
  {#if saveMessage}<p><em class="ok">{saveMessage}</em></p>{/if}
  {#if errors._general}<p><em class="err">{errors._general}</em></p>{/if}
  {#if verifyResult}
    <p>
      IMAP: {#if verifyResult.imap.ok}<em class="ok">OK</em>{:else}<em class="err">failed — {verifyResult.imap.error}</em>{/if}<br>
      SMTP: {#if verifyResult.smtp.ok}<em class="ok">OK</em>{:else}<em class="err">failed — {verifyResult.smtp.error}</em>{/if}
    </p>
  {/if}
</fieldset>

<style>
  .block { margin-bottom: 16px; border: 1px solid #d1d5db; padding: 12px; border-radius: 4px; }
  .num { width: 6em; }
  input:not(.num) { width: 100%; max-width: 360px; box-sizing: border-box; }
  .err { color: #b91c1c; }
  .ok { color: #047857; }
</style>
