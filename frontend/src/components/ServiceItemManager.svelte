<script>
  import { api, errorMessage } from '../lib/api.js';
  import { triageError } from '../lib/errorTriage.js';
  import { showError } from '../stores/messages.js';
  import FieldError from './FieldError.svelte';
  import FormMessage from './FormMessage.svelte';

  let { canEdit = true } = $props();

  let templates = $state([]);
  let schemes = $state([]);
  let allSchemes = $state([]);
  let loading = $state(true);
  let error = $state('');
  let editingId = $state(null);
  let form = $state(emptyForm());
  let saving = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});

  function clearFormMessages() {
    formError = '';
    fieldErrs = {};
  }

  function emptyForm() {
    return {
      template_name: '', description: '', rate_scheme: '',
      default_active_modifiers: [],
      is_active: true,
    };
  }

  async function load() {
    loading = true;
    error = '';
    try {
      const [tmplResp, schemeResp, allSchemeResp] = await Promise.all([
        api.get('/api/service-items/'),
        api.get('/api/rate-schemes/'),
        api.get('/api/rate-schemes/?include_inactive=true'),
      ]);
      templates = tmplResp.results || tmplResp;
      schemes = schemeResp.results || schemeResp;
      allSchemes = allSchemeResp.results || allSchemeResp;
    } catch (e) {
      error = e.message || 'Could not load.';
    } finally {
      loading = false;
    }
  }

  const selectedScheme = $derived(
    schemes.find(s => s.rate_scheme_id === Number(form.rate_scheme)) || null
  );
  // flat_fee schemes: the item's config is one {amount} entry, not a list of
  // pre-checked modifier keys — the scheme owns that interpretation
  // (RateScheme.validate_item_config). The UI shows a single Amount field
  // and the word "modifier" never renders on this path (RM 2026-08-16).
  const isFlatFeeScheme = $derived(selectedScheme?.algorithm === 'flat_fee');
  let flatFeeAmount = $state('');

  function schemeFor(id) {
    return allSchemes.find(s => s.rate_scheme_id === id);
  }

  // "Rush (+50%), Fragile (-10%)" for the item's default-active modifiers.
  function activeModifierNote(template, scheme) {
    const active = template.default_active_modifiers || [];
    if (!scheme || active.length === 0) return '';
    return (scheme.modifiers || [])
      .filter(m => active.includes(m.key))
      .map(m => `${m.label || m.key} (${m.percent >= 0 ? '+' : ''}${m.percent}%)`)
      .join(', ');
  }

  function isInactiveScheme(template) {
    const s = schemeFor(template.rate_scheme);
    return !!(s && !s.is_active);
  }

  async function refreshSchemes() {
    // The schemes list is loaded once on mount, but a RateScheme can be
    // edited/retired elsewhere on the settings page while this component
    // sits open — re-fetch on form open so the picker is never stale.
    try {
      const [schemeResp, allSchemeResp] = await Promise.all([
        api.get('/api/rate-schemes/'),
        api.get('/api/rate-schemes/?include_inactive=true'),
      ]);
      schemes = schemeResp.results || schemeResp;
      allSchemes = allSchemeResp.results || allSchemeResp;
    } catch {
      // Keep the previously-loaded lists; save still validates server-side.
    }
  }

  function startCreate() {
    form = emptyForm();
    flatFeeAmount = '';
    editingId = 'new';
    clearFormMessages();
    refreshSchemes();
  }

  function startEdit(tmpl) {
    // Config shape is scheme-owned: a list of modifier KEYS for percent-style
    // schemes, one {amount} entry for flat_fee ones. Prefill both local
    // shapes; save() emits whichever the picked scheme calls for.
    const dm = tmpl.default_active_modifiers;
    const amountEntry = Array.isArray(dm)
      ? dm.find((m) => m && typeof m === 'object' && 'amount' in m)
      : null;
    flatFeeAmount = amountEntry ? String(amountEntry.amount) : '';
    form = {
      template_name: tmpl.template_name,
      description: tmpl.description || '',
      rate_scheme: tmpl.rate_scheme || '',
      default_active_modifiers:
        Array.isArray(dm) && !amountEntry ? [...dm] : [],
      is_active: tmpl.is_active,
    };
    editingId = tmpl.template_id;
    clearFormMessages();
    refreshSchemes();
  }

  function cancelEdit() { editingId = null; clearFormMessages(); }

  function toggleModifier(key) {
    if (form.default_active_modifiers.includes(key)) {
      form.default_active_modifiers = form.default_active_modifiers.filter(k => k !== key);
    } else {
      form.default_active_modifiers = [...form.default_active_modifiers, key];
    }
  }

  async function save() {
    saving = true;
    clearFormMessages();
    try {
      const payload = {
        template_name: form.template_name,
        description: form.description,
        rate_scheme: form.rate_scheme || null,
        default_active_modifiers: isFlatFeeScheme
          // Number-input binding yields a number; emit the backend's string
          // convention at 2 decimals (matches Decimal(str(amount)) parsing).
          ? (flatFeeAmount !== '' && flatFeeAmount != null
              ? [{ amount: Number(flatFeeAmount).toFixed(2) }] : [])
          : form.default_active_modifiers,
        is_active: form.is_active,
      };
      if (editingId === 'new') {
        await api.post('/api/service-items/', payload);
      } else {
        await api.patch(`/api/service-items/${editingId}/`, payload);
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

  async function remove(tmpl) {
    if (!confirm(`Delete template "${tmpl.template_name}"?`)) return;
    try {
      await api.delete(`/api/service-items/${tmpl.template_id}/`);
      await load();
    } catch (e) {
      // Non-form action: the global overlay is the venue.
      showError(errorMessage(e, 'Could not delete.'));
    }
  }

  load();
</script>

<h3>Service Items</h3>

{#if error}<p><em>{error}</em></p>{/if}
{#if loading}<p>Loading...</p>{/if}

{#if !loading && editingId === null}
  <table class="data-table">
    <thead>
      <tr><th>Name</th><th>Rate Scheme</th><th>Active</th><th></th></tr>
    </thead>
    <tbody>
      {#each templates as t (t.template_id)}
        {@const scheme = schemeFor(t.rate_scheme)}
        <tr>
          <td>{t.template_name}</td>
          <td>
            {scheme ? scheme.name : '—'}
            {#if activeModifierNote(t, scheme)}
              <br><small>{activeModifierNote(t, scheme)}</small>
            {/if}
            {#if isInactiveScheme(t)}
              <br><strong style="color:#a8071a">WARNING: Rate Scheme is inactive — update before next use</strong>
            {/if}
          </td>
          <td>{t.is_active ? 'Yes' : 'No'}</td>
          <td>
            {#if canEdit}
              <button type="button" onclick={() => startEdit(t)}>Edit</button>
              <button type="button" onclick={() => remove(t)}>Delete</button>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if canEdit}
    <p><button type="button" onclick={startCreate}>Add Service Item</button></p>
  {/if}
{/if}

{#if editingId !== null}
  <fieldset>
    <legend><strong>{editingId === 'new' ? 'New Service Item' : 'Edit Service Item'}</strong></legend>
    <p><label><strong>Name *</strong><br>
      <input type="text" bind:value={form.template_name} style="width:100%;box-sizing:border-box;">
    </label>
    <FieldError errors={fieldErrs} field="template_name" /></p>
    <p><label><strong>Description</strong><br>
      <textarea bind:value={form.description} style="width:100%;box-sizing:border-box;"></textarea>
    </label>
    <FieldError errors={fieldErrs} field="description" /></p>
    <p><label><strong>Rate Scheme</strong><br>
      <select bind:value={form.rate_scheme}>
        <option value="">-- None --</option>
        {#each schemes as s (s.rate_scheme_id)}
          <option value={s.rate_scheme_id}>{s.name} ({s.algorithm})</option>
        {/each}
      </select>
    </label>
    <FieldError errors={fieldErrs} field="rate_scheme" /></p>

    {#if selectedScheme}
      {#if isFlatFeeScheme}
        <p><label><strong>Amount *</strong><br>
          <input type="number" step="0.01" min="0.01" bind:value={flatFeeAmount}>
        </label>
        <small>per {selectedScheme.unit_label}</small>
        <FieldError errors={fieldErrs} field="default_active_modifiers" /></p>
      {:else}
        <p><strong>Rate:</strong> ${selectedScheme.rate}/{selectedScheme.unit_label} <small>(from rate scheme)</small></p>
        {#if selectedScheme.modifiers && selectedScheme.modifiers.length > 0}
          <fieldset>
            <legend><strong>Default Modifiers</strong></legend>
            {#each selectedScheme.modifiers as mod}
              <label>
                <input type="checkbox"
                  checked={form.default_active_modifiers.includes(mod.key)}
                  onchange={() => toggleModifier(mod.key)}>
                {mod.label} (+{mod.percent}%)
              </label><br>
            {/each}
          </fieldset>
          <FieldError errors={fieldErrs} field="default_active_modifiers" />
        {/if}
      {/if}
    {/if}

    <p><label>
      <input type="checkbox" bind:checked={form.is_active}> Active
    </label>
    <FieldError errors={fieldErrs} field="is_active" /></p>

    <p>
      <button type="button" onclick={save} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </button>
      <button type="button" onclick={cancelEdit} disabled={saving}>Cancel</button>
    </p>
    <FormMessage error={formError} />
  </fieldset>
{/if}
