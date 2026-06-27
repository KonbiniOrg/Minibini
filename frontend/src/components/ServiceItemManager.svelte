<script>
  import { api } from '../lib/api.js';

  let templates = $state([]);
  let schemes = $state([]);
  let allSchemes = $state([]);
  let loading = $state(true);
  let error = $state('');
  let editingId = $state(null);
  let form = $state(emptyForm());
  let saving = $state(false);
  let saveError = $state('');

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
        api.get('/api/rate-schemes/?include_superseded=true'),
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

  function schemeFor(id) {
    return allSchemes.find(s => s.rate_scheme_id === id);
  }

  function isSuperseded(template) {
    const s = schemeFor(template.rate_scheme);
    return !!(s && s.superseded);
  }

  function startCreate() {
    form = emptyForm();
    editingId = 'new';
    saveError = '';
  }

  function startEdit(tmpl) {
    // active_modifiers is always a list of modifier keys.
    const dm = tmpl.default_active_modifiers;
    form = {
      template_name: tmpl.template_name,
      description: tmpl.description || '',
      rate_scheme: tmpl.rate_scheme || '',
      default_active_modifiers: Array.isArray(dm) ? [...dm] : [],
      is_active: tmpl.is_active,
    };
    editingId = tmpl.template_id;
    saveError = '';
  }

  function cancelEdit() { editingId = null; saveError = ''; }

  function toggleModifier(key) {
    if (form.default_active_modifiers.includes(key)) {
      form.default_active_modifiers = form.default_active_modifiers.filter(k => k !== key);
    } else {
      form.default_active_modifiers = [...form.default_active_modifiers, key];
    }
  }

  async function save() {
    saving = true;
    saveError = '';
    try {
      const payload = {
        template_name: form.template_name,
        description: form.description,
        rate_scheme: form.rate_scheme || null,
        default_active_modifiers: form.default_active_modifiers,
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
      if (e.data && typeof e.data === 'object') {
        saveError = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        saveError = e.message || 'Could not save.';
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
      error = e.message || 'Could not delete.';
    }
  }

  load();
</script>

<h3>Task Templates</h3>

{#if error}<p><em>{error}</em></p>{/if}
{#if loading}<p>Loading...</p>{/if}

{#if !loading && editingId === null}
  <table class="data-table">
    <thead>
      <tr><th>Name</th><th>Service</th><th>Active</th><th></th></tr>
    </thead>
    <tbody>
      {#each templates as t (t.template_id)}
        {@const scheme = schemeFor(t.rate_scheme)}
        <tr>
          <td>{t.template_name}</td>
          <td>
            {scheme ? scheme.name : '—'}
            {#if isSuperseded(t)}
              <br><strong style="color:#a8071a">WARNING: Service is superseded — update before next use</strong>
            {/if}
          </td>
          <td>{t.is_active ? 'Yes' : 'No'}</td>
          <td>
            <button type="button" onclick={() => startEdit(t)}>Edit</button>
            <button type="button" onclick={() => remove(t)}>Delete</button>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  <p><button type="button" onclick={startCreate}>Add Template</button></p>
{/if}

{#if editingId !== null}
  <fieldset>
    <legend><strong>{editingId === 'new' ? 'New Task Template' : 'Edit Task Template'}</strong></legend>
    <p><label><strong>Name *</strong><br>
      <input type="text" bind:value={form.template_name} style="width:100%;box-sizing:border-box;">
    </label></p>
    <p><label><strong>Description</strong><br>
      <textarea bind:value={form.description} style="width:100%;box-sizing:border-box;"></textarea>
    </label></p>
    <p><label><strong>Service</strong><br>
      <select bind:value={form.rate_scheme}>
        <option value="">-- None --</option>
        {#each schemes as s (s.rate_scheme_id)}
          <option value={s.rate_scheme_id}>{s.name} ({s.algorithm})</option>
        {/each}
      </select>
    </label></p>

    {#if selectedScheme}
      <p><strong>Rate:</strong> ${selectedScheme.rate}/{selectedScheme.unit_label} <small>(from service)</small></p>
      {#if selectedScheme.algorithm !== 'flat_fee' && selectedScheme.modifiers && selectedScheme.modifiers.length > 0}
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
      {/if}
    {/if}

    <p><label>
      <input type="checkbox" bind:checked={form.is_active}> Active
    </label></p>

    <p>
      <button type="button" onclick={save} disabled={saving}>
        {saving ? 'Saving...' : 'Save'}
      </button>
      <button type="button" onclick={cancelEdit} disabled={saving}>Cancel</button>
    </p>
    {#if saveError}<p><em style="color:#a8071a">{saveError}</em></p>{/if}
  </fieldset>
{/if}
