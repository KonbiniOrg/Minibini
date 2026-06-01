<script>
  import { api } from '../../lib/api.js';

  let business_email = $state('');
  let saveMessage = $state('');
  let errors = $state({});

  async function load() {
    try {
      const data = await api.get('/api/settings/');
      business_email = data.business_email ?? '';
    } catch (_) {}
  }

  async function save() {
    saveMessage = '';
    errors = {};
    try {
      await api.patch('/api/settings/', { business_email });
      saveMessage = 'Business settings saved.';
    } catch (err) {
      errors = (err.data && typeof err.data === 'object')
        ? err.data : { _general: err.message || 'Save failed' };
    }
  }

  load();
</script>

<h3>Business</h3>
<p>
  <label><strong>Notification email</strong><br>
    <input type="email" bind:value={business_email}
           placeholder="office@yourshop.com">
  </label>
  {#if errors.business_email}<em class="err">{errors.business_email}</em>{/if}
</p>
<p><small>Where customer estimate accept/decline notifications are sent.</small></p>
<p>
  <button type="button" onclick={save}>Save</button>
  {#if saveMessage}<em>{saveMessage}</em>{/if}
  {#if errors._general}<em class="err">{errors._general}</em>{/if}
</p>

<style>
  .err { color: #b91c1c; margin-left: 0.5em; }
</style>
