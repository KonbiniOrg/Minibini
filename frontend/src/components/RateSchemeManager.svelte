<script>
  import { api } from '../lib/api.js';

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
  let saveError = $state('');

  const ALGORITHM_LABELS = {
    elapsed_time: 'Based on time worked',
    entered_qty: 'Worker enters quantity',
    flat_fee: 'Fixed charge',
  };

  function emptyForm() {
    return {
      name: '', description: '', algorithm: 'elapsed_time',
      rate: '', unit_label: '', minimum_charge: '',
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
      error = e.message || 'Could not load rate schemes.';
    } finally {
      loading = false;
    }
  }

  function isReferenced(s) {
    const c = s.reference_counts || {};
    return ((c.plan_task_count || 0) + (c.task_charge_count || 0) + (c.task_template_count || 0)) > 0;
  }

  function startCreate() {
    form = emptyForm();
    editingId = 'new';
    supersedingId = null;
    saveError = '';
  }

  function startEdit(scheme) {
    form = {
      name: scheme.name,
      description: scheme.description || '',
      algorithm: scheme.algorithm,
      rate: scheme.rate,
      unit_label: scheme.unit_label,
      minimum_charge: scheme.minimum_charge || '',
      modifiers: [...(scheme.modifiers || [])],
      accounting_category: scheme.accounting_category || '',
    };
    editingId = scheme.rate_scheme_id;
    supersedingId = null;
    saveError = '';
  }

  function startSupersede(scheme) {
    form = {
      name: scheme.name,
      description: scheme.description || '',
      algorithm: scheme.algorithm,
      rate: scheme.rate,
      unit_label: scheme.unit_label,
      minimum_charge: scheme.minimum_charge || '',
      modifiers: [...(scheme.modifiers || [])],
      accounting_category: scheme.accounting_category || '',
    };
    supersedingId = scheme.rate_scheme_id;
    editingId = null;
    saveError = '';
  }

  function cancelEdit() {
    editingId = null;
    supersedingId = null;
    saveError = '';
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
    saveError = '';
    try {
      const payload = {
        name: form.name,
        description: form.description,
        algorithm: form.algorithm,
        rate: form.rate,
        unit_label: form.unit_label,
        minimum_charge: form.minimum_charge || null,
        modifiers: form.modifiers.map(m => ({
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

  async function remove(scheme) {
    if (!confirm(`Delete rate scheme "${scheme.name}"?`)) return;
    try {
      await api.delete(`/api/rate-schemes/${scheme.rate_scheme_id}/`);
      await load();
    } catch (e) {
      error = e.message || 'Could not delete.';
    }
  }

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

{#if error}<p><em>{error}</em></p>{/if}
{#if loading}<p>Loading...</p>{/if}

{#if !loading && editingId === null && supersedingId === null}
  <p>
    <label>
      <input type="checkbox" bind:checked={showSuperseded} onchange={load} />
      Show superseded schemes
    </label>
  </p>
  <table border="1">
    <thead>
      <tr>
        <th>Name</th><th>Type</th><th>Rate</th><th>Unit</th>
        <th>Modifiers</th><th></th>
      </tr>
    </thead>
    <tbody>
      {#each schemes as s (s.rate_scheme_id)}
        <tr>
          <td>{s.name}</td>
          <td>{ALGORITHM_LABELS[s.algorithm] || s.algorithm}</td>
          <td>${s.rate}/{s.unit_label}</td>
          <td>{s.unit_label}</td>
          <td>{(s.modifiers || []).length}</td>
          <td>
            {#if s.superseded}
              <small>
                Replaced by: scheme {s.replaced_by}
                {#if s.replaced_at}| Replaced at: {new Date(s.replaced_at).toLocaleString()}{/if}
                | References: {s.reference_counts?.plan_task_count || 0} plan tasks,
                {s.reference_counts?.task_charge_count || 0} task charges,
                {s.reference_counts?.task_template_count || 0} templates
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
  {#if !showSuperseded}
    <p><button type="button" onclick={startCreate}>Add Rate Scheme</button></p>
  {/if}
{/if}

{#if editingId !== null || supersedingId !== null}
  <fieldset>
    <legend><strong>{supersedingId ? 'New Version of Rate Scheme' : (editingId === 'new' ? 'New Rate Scheme' : 'Edit Rate Scheme')}</strong></legend>
    <p><label><strong>Name *</strong><br>
      <input type="text" bind:value={form.name} style="width:100%;box-sizing:border-box;">
    </label>
    {#if supersedingId}
      <small>
        You can keep this name. The retired version will be renamed
        automatically (e.g. "(v1)").
      </small>
    {/if}
    </p>
    <p><label><strong>Description</strong><br>
      <textarea bind:value={form.description} style="width:100%;box-sizing:border-box;"></textarea>
    </label></p>
    <p><label><strong>Algorithm *</strong><br>
      <select bind:value={form.algorithm}>
        <option value="elapsed_time">Based on time worked</option>
        <option value="entered_qty">Worker enters quantity</option>
        <option value="flat_fee">Fixed charge</option>
      </select>
    </label></p>
    <p><label><strong>Rate *</strong><br>
      <input type="number" step="0.01" bind:value={form.rate}>
    </label>
    <label><strong>Unit label *</strong><br>
      <select bind:value={form.unit_label} required>
        <option value="">-- select --</option>
        {#each unitsList as u}
          <option value={u}>{u}</option>
        {/each}
      </select>
    </label></p>
    <p><label><strong>Minimum charge</strong><br>
      <input type="number" step="0.01" bind:value={form.minimum_charge}>
    </label></p>
    <p><label><strong>Accounting Category *</strong><br>
      <select bind:value={form.accounting_category} required>
        <option value="">-- select --</option>
        {#each categories as cat (cat.id)}
          <option value={cat.id}>{cat.code} — {cat.name}</option>
        {/each}
      </select>
    </label></p>

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
    </fieldset>

    {#if previewTotal}
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
    {#if saveError}<p><em style="color:#a8071a">{saveError}</em></p>{/if}
  </fieldset>
{/if}
