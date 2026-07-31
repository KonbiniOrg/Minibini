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
  let supersedingId = $state(null);
  let showSuperseded = $state(false);
  let form = $state(emptyForm());
  let saving = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});
  // Set when a save bounced off the referenced-scheme 409 — the footer
  // message then offers "Create new version" (the conflict's next step).
  let conflictSchemeId = $state(null);

  const ALGORITHM_LABELS = {
    elapsed_time: 'Based on time worked',
    entered_qty: 'Worker enters quantity',
    percentage: 'Percentage of other lines',
  };

  function emptyForm() {
    return {
      name: '', description: '', algorithm: 'elapsed_time',
      rate: '', unit_label: '',
      modifiers: [], accounting_category: '',
    };
  }

  async function load() {
    loading = true;
    error = '';
    try {
      const url = showSuperseded
        ? '/api/rate-schemes/?include_superseded=true'
        : '/api/rate-schemes/';
      const [schemeResp, catResp, unitsResp] = await Promise.all([
        api.get(url),
        api.get('/api/accounting-categories/'),
        api.get('/api/settings/units/'),
      ]);
      schemes = schemeResp.results || schemeResp;
      categories = catResp.results || catResp;
      unitsList = unitsResp;
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

  function isReferenced(s) {
    const c = s.reference_counts || {};
    return ((c.task_count || 0) + (c.service_item_count || 0)) > 0;
  }

  function clearFormMessages() {
    formError = '';
    fieldErrs = {};
    conflictSchemeId = null;
  }

  function startCreate() {
    form = emptyForm();
    editingId = 'new';
    supersedingId = null;
    clearFormMessages();
  }

  function startEdit(scheme) {
    form = {
      name: scheme.name,
      description: scheme.description || '',
      algorithm: scheme.algorithm,
      rate: scheme.rate,
      unit_label: scheme.unit_label,
      modifiers: [...(scheme.modifiers || [])],
      accounting_category: scheme.accounting_category || '',
    };
    editingId = scheme.rate_scheme_id;
    supersedingId = null;
    clearFormMessages();
  }

  function startSupersede(scheme) {
    form = {
      name: scheme.name,
      description: scheme.description || '',
      algorithm: scheme.algorithm,
      rate: scheme.rate,
      unit_label: scheme.unit_label,
      modifiers: [...(scheme.modifiers || [])],
      accounting_category: scheme.accounting_category || '',
    };
    supersedingId = scheme.rate_scheme_id;
    editingId = null;
    clearFormMessages();
  }

  function cancelEdit() {
    editingId = null;
    supersedingId = null;
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
      const payload = {
        name: form.name,
        description: form.description,
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

      if (supersedingId) {
        await api.post(`/api/rate-schemes/${supersedingId}/supersede/`, payload);
      } else if (editingId === 'new') {
        await api.post('/api/rate-schemes/', payload);
      } else {
        await api.patch(`/api/rate-schemes/${editingId}/`, payload);
      }
      editingId = null;
      supersedingId = null;
      await load();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message;
        fieldErrs = t.fields;
        if (e.data?.code === 'referenced' && editingId && editingId !== 'new') {
          conflictSchemeId = editingId;
        }
      }
    } finally {
      saving = false;
    }
  }

  function supersedeFromConflict() {
    const scheme = schemes.find((s) => s.rate_scheme_id === conflictSchemeId);
    if (scheme) startSupersede(scheme);
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

  // The add/edit/supersede form is one Modal in three modes — the
  // conflict path (supersedeFromConflict) switches mode in place, so the
  // shell stays open across it.
  const formOpen = $derived(editingId !== null || supersedingId !== null);
  const formTitle = $derived(
    supersedingId ? 'New Version of Rate Scheme'
      : editingId === 'new' ? 'New Rate Scheme' : 'Edit Rate Scheme');

  // percentage: rate holds the percent (negative = discount); no modifiers, no unit/qty fields.
  const isPercentage = $derived(form.algorithm === 'percentage');

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
      <input type="checkbox" bind:checked={showSuperseded} onchange={load} />
      Show superseded rates
    </label>
  </p>
  <table class="data-table">
    <thead>
      <tr>
        <th>Name</th><th>Type</th><th>Rate</th><th>Unit</th>
        <th>Category</th><th>Modifiers</th><th></th>
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
          <td>
            {#if s.superseded}
              <small>
                Replaced by: scheme {s.replaced_by}
                {#if s.replaced_at}| Replaced at: {new Date(s.replaced_at).toLocaleString()}{/if}
                | References: {s.reference_counts?.task_count || 0} tasks,
                {s.reference_counts?.service_item_count || 0} templates
              </small>
            {:else if isReferenced(s)}
              <button type="button" onclick={() => startSupersede(s)}>Create new version</button>
            {:else}
              <button type="button" onclick={() => startEdit(s)}>Edit</button>
              <button type="button" onclick={() => remove(s)}>Delete</button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if !showSuperseded && editingId === null && supersedingId === null}
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
    {#if supersedingId}
      <small>
        You can keep this name. The retired version will be renamed
        automatically (e.g. "(v1)").
      </small>
    {/if}
    </p>
    <p><label><strong>Description</strong><br>
      <textarea bind:value={form.description} style="width:100%;box-sizing:border-box;"></textarea>
    </label>
    <FieldError errors={fieldErrs} field="description" /></p>
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
      <label><strong>Rate *</strong><br>
        <input type="number" step="0.01" bind:value={form.rate}>
      </label>
      <FieldError errors={fieldErrs} field="rate" />
      <label><strong>Unit label *</strong><br>
        <select bind:value={form.unit_label} required>
          <option value="">-- select --</option>
          {#each unitsList as u}
            <option value={u}>{u}</option>
          {/each}
        </select>
      </label>
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
        {previewTotal.qty} {form.unit_label}s @ ${previewTotal.effRate}/{form.unit_label} = ${previewTotal.total}
      </p>
    {/if}

    <p>
      <button type="button" onclick={save} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </button>
      <button type="button" onclick={cancelEdit} disabled={saving}>Cancel</button>
    </p>
    <FormMessage error={formError}>
      {#if conflictSchemeId}
        <button type="button" onclick={supersedeFromConflict}>Create new version</button>
      {/if}
    </FormMessage>
</Modal>

<style>
  /* Matches JobEditModal's title treatment. */
  .rs-modal-title { margin-top: 0; }
</style>
