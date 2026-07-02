<script>
  import { api } from '../../lib/api.js';

  let markup = $state('0');
  let saveMessage = $state('');
  let error = $state('');

  async function load() {
    try {
      const data = await api.get('/api/settings/');
      markup = data.default_material_markup_percent ?? '0';
    } catch (_) {}
  }

  async function save() {
    saveMessage = '';
    error = '';
    const n = Number(markup);
    if (Number.isNaN(n) || n < 0) {
      error = 'Enter a non-negative number.';
      return;
    }
    try {
      await api.patch('/api/settings/', {
        default_material_markup_percent: String(markup),
      });
      saveMessage = 'Markup saved.';
    } catch (err) {
      error = err.message || 'Save failed.';
    }
  }

  load();
</script>

<h3>Standard material markup</h3>
<p>The default markup applied to a new inventory item's selling price <em>at
creation</em>.  Changing this never re-prices existing items.</p>

<p>
  <label for="mat-markup"><strong>Default markup (%)</strong></label><br>
  <input id="mat-markup" type="number" step="0.01" min="0" bind:value={markup}>
  <button type="button" onclick={save}>Save</button>
  {#if saveMessage}<em>{saveMessage}</em>{/if}
  {#if error}<em class="err">{error}</em>{/if}
</p>

<style>
  .err { color: #c00; }
</style>
