<script>
  import { api } from '../../lib/api.js';

  // User-settable Configuration keys that had no editor before. Document-number
  // *patterns* live here (the counters are machine state in AppState and are not
  // editable from the UI by design).
  let est_expire_days = $state('');
  let board_closed_retention_days = $state('');
  let average_labor_cost = $state('');
  let job_number_sequence = $state('');
  let invoice_number_sequence = $state('');
  let po_number_sequence = $state('');

  let saveMessage = $state('');
  let errors = $state({});

  async function load() {
    try {
      const data = await api.get('/api/settings/');
      est_expire_days = data.est_expire_days ?? '';
      board_closed_retention_days = data.board_closed_retention_days ?? '';
      average_labor_cost = data.average_labor_cost ?? '';
      job_number_sequence = data.job_number_sequence ?? '';
      invoice_number_sequence = data.invoice_number_sequence ?? '';
      po_number_sequence = data.po_number_sequence ?? '';
    } catch (_) {}
  }

  async function save(payload, label) {
    saveMessage = '';
    errors = {};
    try {
      await api.patch('/api/settings/', payload);
      saveMessage = `${label} saved.`;
    } catch (err) {
      errors = (err.data && typeof err.data === 'object')
        ? err.data : { _general: err.message || 'Save failed' };
    }
  }

  load();
</script>

<fieldset class="block">
  <legend><strong>Defaults</strong></legend>
  <p>
    <label><strong>Estimate expiry</strong><br>
      <input type="number" min="1" class="num" bind:value={est_expire_days}> days
    </label>
    {#if errors.est_expire_days}<em class="err">{errors.est_expire_days}</em>{/if}
  </p>
  <p><small>Default window before a sent estimate expires.</small></p>
  <p>
    <label><strong>Job Board retention</strong><br>
      <input type="number" min="1" class="num" bind:value={board_closed_retention_days}> days
    </label>
    {#if errors.board_closed_retention_days}<em class="err">{errors.board_closed_retention_days}</em>{/if}
  </p>
  <p><small>How long closed jobs stay visible on the Job Board.</small></p>
  <p>
    <label><strong>Average labor cost</strong><br>
      $ <input type="number" min="0" step="0.01" class="num" bind:value={average_labor_cost}> / hour
    </label>
    {#if errors.average_labor_cost}<em class="err">{errors.average_labor_cost}</em>{/if}
  </p>
  <p><small>Approximate cost per hour of logged time, used for a job's Spent
    total. Leave blank to value labor at $0 until you set a rate.</small></p>
  <p>
    <button type="button"
            onclick={() => save({ est_expire_days, board_closed_retention_days, average_labor_cost }, 'Defaults')}>Save defaults</button>
  </p>
</fieldset>

<fieldset class="block">
  <legend><strong>Document numbering</strong></legend>
  <p><small>Format patterns for generated numbers. Placeholders:
    <code>{'{year}'}</code>, <code>{'{month:02d}'}</code>, <code>{'{day:02d}'}</code>,
    <code>{'{counter:04d}'}</code>. (Counters themselves are managed automatically.)</small></p>
  <p>
    <label><strong>Job number</strong><br>
      <input type="text" class="pattern" bind:value={job_number_sequence}
             placeholder="JOB-{'{year}'}-{'{counter:04d}'}">
    </label>
    {#if errors.job_number_sequence}<em class="err">{errors.job_number_sequence}</em>{/if}
  </p>
  <p>
    <label><strong>Invoice number</strong><br>
      <input type="text" class="pattern" bind:value={invoice_number_sequence}
             placeholder="INV-{'{year}'}-{'{counter:04d}'}">
    </label>
    {#if errors.invoice_number_sequence}<em class="err">{errors.invoice_number_sequence}</em>{/if}
  </p>
  <p>
    <label><strong>Purchase Order number</strong><br>
      <input type="text" class="pattern" bind:value={po_number_sequence}
             placeholder="PO-{'{year}'}-{'{counter:04d}'}">
    </label>
    {#if errors.po_number_sequence}<em class="err">{errors.po_number_sequence}</em>{/if}
  </p>
  <p>
    <button type="button"
            onclick={() => save({ job_number_sequence, invoice_number_sequence, po_number_sequence }, 'Numbering')}>Save numbering</button>
  </p>
</fieldset>

<p>
  {#if saveMessage}<em class="ok">{saveMessage}</em>{/if}
  {#if errors._general}<em class="err">{errors._general}</em>{/if}
</p>

<style>
  .block { margin-bottom: 16px; border: 1px solid #d1d5db; padding: 12px; border-radius: 4px; }
  .num { width: 5em; }
  .pattern { width: 100%; max-width: 360px; box-sizing: border-box; font-family: monospace; }
  .err { color: #b91c1c; margin-left: 0.5em; }
  .ok { color: #047857; }
</style>
