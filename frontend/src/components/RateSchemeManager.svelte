<script>
  import SchemesImportPanel from './qboimport/SchemesImportPanel.svelte';
  import QboPullButton from './qboimport/QboPullButton.svelte';
  import { api, errorMessage } from '../lib/api.js';
  import { triageError } from '../lib/errorTriage.js';
  import { showError } from '../stores/messages.js';
  import FieldError from './FieldError.svelte';
  import FormMessage from './FormMessage.svelte';
  import Modal from './Modal.svelte';

  let pullEpoch = $state(0);

  let schemes = $state([]);
  let categories = $state([]);
  let unitsList = $state([]);
  let loading = $state(true);
  let error = $state('');
  let editingId = $state(null);
  let showInactive = $state(false);
  let form = $state(emptyForm());
  let saving = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});

  // Default preset picker (Configuration key `default_rate_scheme`,
  // read/written via /api/settings/) — the scheme offered by default on new
  // task creation. Loaded alongside the scheme list so it's always fresh.
  let defaultSchemeId = $state('');
  let defaultSaving = $state(false);
  let defaultError = $state('');
  let defaultSuccess = $state('');

  const ALGORITHM_LABELS = {
    elapsed_time: 'Based on time worked',
    entered_qty: 'Worker enters quantity',
    percentage: 'Percentage of other lines',
  };

  function emptyForm() {
    return {
      name: '', algorithm: 'elapsed_time',
      rate: '', unit_label: '',
      modifiers: [], accounting_category: '',
    };
  }

  async function load() {
    loading = true;
    error = '';
    try {
      const url = showInactive
        ? '/api/rate-schemes/?include_inactive=true'
        : '/api/rate-schemes/';
      const [schemeResp, catResp, unitsResp, settingsResp] = await Promise.all([
        api.get(url),
        api.get('/api/accounting-categories/'),
        api.get('/api/settings/units/'),
        api.get('/api/settings/'),
      ]);
      schemes = schemeResp.results || schemeResp;
      categories = catResp.results || catResp;
      unitsList = unitsResp;
      defaultSchemeId = settingsResp.default_rate_scheme || '';
    } catch (e) {
      error = e.message || 'Could not load services.';
    } finally {
      loading = false;
    }
  }

  function categoryLabel(id) {
    const cat = categories.find((c) => c.id === id);
    return cat ? `${cat.code} — ${cat.name}` : '';
  }

  function clearFormMessages() {
    formError = '';
    fieldErrs = {};
  }

  function startCreate() {
    form = emptyForm();
    editingId = 'new';
    clearFormMessages();
  }

  function startEdit(scheme) {
    form = {
      name: scheme.name,
      algorithm: scheme.algorithm,
      rate: scheme.rate,
      unit_label: scheme.unit_label,
      modifiers: [...(scheme.modifiers || [])],
      accounting_category: scheme.accounting_category || '',
    };
    editingId = scheme.rate_scheme_id;
    clearFormMessages();
  }

  function cancelEdit() {
    editingId = null;
    clearFormMessages();
  }

  function addModifier() {
    form.modifiers = [...form.modifiers, { key: '', label: '', percent: '' }];
  }

  function removeModifier(index) {
    form.modifiers = form.modifiers.filter((_, i) => i !== index);
  }

  function slugify(str) {
    return str.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
  }

  async function save() {
    saving = true;
    clearFormMessages();
    try {
      // The backend force-sets this for elapsed_time regardless — this
      // guarantees the payload matches what actually gets persisted, even
      // though the control is locked and never lets the user set it wrong.
      if (form.algorithm === 'elapsed_time') form.unit_label = 'hour';
      const payload = {
        name: form.name,
        algorithm: form.algorithm,
        rate: form.rate,
        unit_label: form.unit_label,
        modifiers: form.modifiers
          // An untouched "add modifier" row (no name, no percent) is a
          // no-op — drop it rather than persist a blank modifier.
          .filter(m => (m.label || m.key || '').trim() || Number(m.percent))
          .map(m => ({
            key: m.key || slugify(m.label),
            label: m.label,
            percent: Number(m.percent),
          })),
        accounting_category: form.accounting_category,
      };

      if (editingId === 'new') {
        await api.post('/api/rate-schemes/', payload);
      } else {
        await api.patch(`/api/rate-schemes/${editingId}/`, payload);
      }
      editingId = null;
      await load();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message;
        fieldErrs = t.fields;
      }
    } finally {
      saving = false;
    }
  }

  async function remove(scheme) {
    if (!confirm(`Delete service "${scheme.name}"?`)) return;
    try {
      await api.delete(`/api/rate-schemes/${scheme.rate_scheme_id}/`);
      await load();
    } catch (e) {
      // Non-form action: the global overlay is the venue.
      showError(errorMessage(e, 'Could not delete.'));
    }
  }

  // Retire/reactivate are reversible toggles (buttons act, no confirm — see
  // UI conventions). Both are non-form actions, so an error goes straight to
  // the global overlay, same as delete above.
  async function retire(scheme) {
    try {
      await api.post(`/api/rate-schemes/${scheme.rate_scheme_id}/retire/`);
      await load();
    } catch (e) {
      showError(errorMessage(e, 'Could not retire.'));
    }
  }

  async function reactivate(scheme) {
    try {
      await api.post(`/api/rate-schemes/${scheme.rate_scheme_id}/reactivate/`);
      await load();
    } catch (e) {
      showError(errorMessage(e, 'Could not reactivate.'));
    }
  }

  async function saveDefaultScheme() {
    defaultSaving = true;
    defaultError = '';
    defaultSuccess = '';
    try {
      await api.patch('/api/settings/', { default_rate_scheme: defaultSchemeId });
      defaultSuccess = 'Default preset saved.';
      setTimeout(() => defaultSuccess = '', 3000);
    } catch (e) {
      const t = triageError(e);
      defaultError = t.fields.default_rate_scheme || t.message || t.overlay || 'Failed to save';
    } finally {
      defaultSaving = false;
    }
  }

  const formOpen = $derived(editingId !== null);
  const formTitle = $derived(editingId === 'new' ? 'New Rate Scheme' : 'Edit Rate Scheme');

  // Only active schemes are ever offered as the default preset — an
  // inactive one must never linger there (server also enforces this).
  const activeSchemes = $derived(schemes.filter((s) => s.is_active));

  // percentage: rate holds the percent (negative = discount); no modifiers, no unit/qty fields.
  const isPercentage = $derived(form.algorithm === 'percentage');

  // Display-only stand-in for the locked unit — NEVER write this back into
  // form.unit_label from a reactive effect: doing so previously clobbered a
  // real unit (e.g. edit an entered_qty scheme with unit 'pc', flip to
  // elapsed_time and back — the effect overwrote unit_label to 'hour' and
  // never restored it, so Save silently persisted the wrong unit). The
  // preview reads this instead of form.unit_label so it renders correctly
  // while elapsed_time is selected, without touching the underlying field;
  // save() is the only place that force-sets form.unit_label, and only
  // right before building the payload.
  const displayUnitLabel = $derived(form.algorithm === 'elapsed_time' ? 'hour' : form.unit_label);

  const previewTotal = $derived.by(() => {
    if (!form.rate) return null;
    const rate = Number(form.rate);
    const modPct = form.modifiers.reduce((sum, m) => sum + (Number(m.percent) || 0), 0);
    const effRate = rate * (1 + modPct / 100);
    const qty = 10;
    return { qty, effRate: effRate.toFixed(2), total: (qty * effRate).toFixed(2) };
  });

  load();
</script>

<h3>Rate Schemes</h3>
<QboPullButton area="schemes" onPulled={() => pullEpoch++} />
{#key pullEpoch}
  <SchemesImportPanel onCommitted={load} {unitsList} />
{/key}

{#if error}<p><em>{error}</em></p>{/if}
{#if loading}<p>Loading...</p>{/if}

{#if !loading}
  <p>
    <label>
      <input type="checkbox" bind:checked={showInactive} onchange={load} />
      Show inactive rate schemes
    </label>
  </p>
  <p>
    <label for="default-rate-scheme"><strong>Default preset</strong></label><br>
    <select id="default-rate-scheme" bind:value={defaultSchemeId}>
      <option value="">-- None --</option>
      {#each activeSchemes as s (s.rate_scheme_id)}
        <option value={String(s.rate_scheme_id)}>{s.name}</option>
      {/each}
    </select>
    {#if defaultError}<strong>Error:</strong> {defaultError}{/if}
    {#if defaultSuccess}<em>{defaultSuccess}</em>{/if}
  </p>
  <p><small>The rate scheme offered by default when creating a new task.</small></p>
  <p>
    <!-- Distinct label from the add/edit modal's "Save" button, which can be
         open at the same time this control is on screen. -->
    <button type="button" onclick={saveDefaultScheme} disabled={defaultSaving}>
      {defaultSaving ? 'Saving...' : 'Save default preset'}
    </button>
  </p>
  <table class="data-table">
    <thead>
      <tr>
        <th>Name</th><th>Type</th><th>Rate</th><th>Unit</th>
        <th>Category</th><th>Modifiers</th><th>Active</th><th></th>
      </tr>
    </thead>
    <tbody>
      {#each schemes as s (s.rate_scheme_id)}
        <tr>
          <td>{s.name}</td>
          <td>{ALGORITHM_LABELS[s.algorithm] || s.algorithm}</td>
          <td>${s.rate}/{s.unit_label}</td>
          <td>{s.unit_label}</td>
          <td>{categoryLabel(s.accounting_category)}</td>
          <td>{(s.modifiers || []).length}</td>
          <td>{s.is_active ? 'Yes' : 'No'}</td>
          <td>
            <button type="button" onclick={() => startEdit(s)}>Edit</button>
            <button type="button" onclick={() => remove(s)}>Delete</button>
            {#if s.is_active}
              <button type="button" onclick={() => retire(s)}>Retire</button>
            {:else}
              <button type="button" onclick={() => reactivate(s)}>Reactivate</button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if editingId === null}
    <p><button type="button" onclick={startCreate}>Add Rate Scheme</button></p>
  {/if}
{/if}

<!-- Button-driven content (no native <form>), so the shell takes onSave and
     owns Enter; `busy` suppresses a double-Enter mid-save. -->
<Modal open={formOpen} onSave={save} onCancel={cancelEdit} busy={saving}
       maxWidth="700px" label={formTitle}>
    <h3 class="rs-modal-title">{formTitle}</h3>
    <p><label><strong>Name *</strong><br>
      <input type="text" bind:value={form.name} style="width:100%;box-sizing:border-box;">
    </label>
    <FieldError errors={fieldErrs} field="name" />
    </p>
    <p><label><strong>Algorithm *</strong><br>
      <select bind:value={form.algorithm}>
        <option value="elapsed_time">Based on time worked</option>
        <option value="entered_qty">Worker enters quantity</option>
        <option value="percentage">Percentage of other lines</option>
      </select>
    </label>
    <FieldError errors={fieldErrs} field="algorithm" /></p>
    <p>
    {#if isPercentage}
      <label><strong>Rate (%) *</strong><br>
        <input type="number" step="0.01" bind:value={form.rate}>
      </label>
      <FieldError errors={fieldErrs} field="rate" />
    {:else}
      <span class="rate-row">
        <label><strong>Rate *</strong><br>
          <input type="number" step="0.01" bind:value={form.rate}>
        </label>
        <span class="rate-per">per</span>
        {#if form.algorithm === 'elapsed_time'}
          <input type="text" value="hour" disabled aria-label="Unit">
        {:else}
          <select bind:value={form.unit_label} required aria-label="Unit">
            <option value="">-- select --</option>
            {#each unitsList as u}
              <option value={u}>{u}</option>
            {/each}
          </select>
        {/if}
      </span>
      {#if form.algorithm === 'elapsed_time'}
        <br><small>Time-based schemes are billed in hours.</small>
      {/if}
      <FieldError errors={fieldErrs} field="rate" />
      <FieldError errors={fieldErrs} field="unit_label" />
    {/if}
    </p>
    <p><label><strong>Accounting Category *</strong><br>
      <select bind:value={form.accounting_category} required>
        <option value="">-- select --</option>
        {#each categories as cat (cat.id)}
          <option value={cat.id}>{cat.code} — {cat.name}</option>
        {/each}
      </select>
    </label>
    <FieldError errors={fieldErrs} field="accounting_category" /></p>

    {#if !isPercentage}
      <fieldset>
        <legend><strong>Modifiers</strong></legend>
        {#each form.modifiers as mod, i}
          <p>
            <input type="text" bind:value={mod.label} placeholder="Label">
            <input type="number" step="0.1" bind:value={mod.percent} placeholder="%" style="width:60px;">%
            <button type="button" onclick={() => removeModifier(i)}>Remove</button>
          </p>
        {/each}
        <p><button type="button" onclick={addModifier}>Add modifier</button></p>
        <FieldError errors={fieldErrs} field="modifiers" />
      </fieldset>
    {/if}

    {#if previewTotal && !isPercentage}
      <p><strong>Preview:</strong>
        {previewTotal.qty} {displayUnitLabel} @ ${previewTotal.effRate}/{displayUnitLabel} = ${previewTotal.total}
      </p>
    {/if}

    <p>
      <button type="button" onclick={save} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </button>
      <button type="button" onclick={cancelEdit} disabled={saving}>Cancel</button>
    </p>
    <FormMessage error={formError} />
</Modal>

<style>
  /* Matches JobEditModal's title treatment. */
  .rs-modal-title { margin-top: 0; }
  /* "Rate [input] per [unit]" on one line, controls bottom-aligned. */
  .rate-row { display: inline-flex; align-items: flex-end; gap: 8px; }
  .rate-row .rate-per { padding-bottom: 3px; }
</style>
