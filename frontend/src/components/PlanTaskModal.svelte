<script>
  import { api } from '../lib/api.js';

  let {
    open = false,
    mode = 'create-freeform', // 'create-freeform' | 'create-template' | 'edit'
    task = null,
    worksheetId = null,
    templates = [],
    categories = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let createMode = $state('freeform');
  let name = $state('');
  let description = $state('');
  let accountingCategory = $state('');
  let templateId = $state('');
  let rateSchemeId = $state('');
  let estimatedBillableQty = $state('');
  let activeModifiers = $state([]);
  let schemes = $state([]);
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    if (open) {
      if (mode === 'edit' && task) {
        createMode = 'freeform';
        name = task.name || '';
        description = task.description || '';
        accountingCategory = task.accounting_category ?? '';
        rateSchemeId = task.rate_scheme ?? '';
        activeModifiers = [...(task.active_modifiers || [])];
        estimatedBillableQty = task.est_qty ?? '';
        templateId = '';
      } else if (mode === 'create-template') {
        createMode = 'template';
        resetFields();
      } else {
        createMode = 'freeform';
        resetFields();
      }
      error = '';
      loadSchemes();
    }
  });

  function resetFields() {
    name = ''; description = ''; accountingCategory = '';
    rateSchemeId = ''; estimatedBillableQty = '';
    activeModifiers = []; templateId = '';
  }

  async function loadSchemes() {
    try {
      const data = await api.get('/api/rate-schemes/');
      schemes = data.results ?? data;
    } catch (e) {
      // non-fatal
    }
  }

  const isEdit = $derived(mode === 'edit');
  const title = $derived(isEdit ? 'Edit Task' : 'Add Task');

  const selectedTemplate = $derived(
    templates.find(t => String(t.template_id) === String(templateId)) || null
  );

  const selectedScheme = $derived.by(() => {
    if (rateSchemeId) {
      return schemes.find(s => s.rate_scheme_id === Number(rateSchemeId)) || null;
    }
    return null;
  });

  $effect(() => {
    if (selectedTemplate) {
      activeModifiers = [...(selectedTemplate.default_active_modifiers || [])];
      if (selectedTemplate.default_billable_qty && !estimatedBillableQty) {
        estimatedBillableQty = selectedTemplate.default_billable_qty;
      }
      if (selectedTemplate.rate_scheme && !rateSchemeId) {
        rateSchemeId = selectedTemplate.rate_scheme;
      }
    }
  });

  const chargePreview = $derived.by(() => {
    if (!selectedScheme || !estimatedBillableQty) return null;
    const baseRate = Number(selectedScheme.rate);
    const modPct = (selectedScheme.modifiers || [])
      .filter(m => activeModifiers.includes(m.key))
      .reduce((sum, m) => sum + m.percent, 0);
    return (Number(estimatedBillableQty) * baseRate * (1 + modPct / 100)).toFixed(2);
  });

  function toggleModifier(key) {
    activeModifiers = activeModifiers.includes(key)
      ? activeModifiers.filter(k => k !== key)
      : [...activeModifiers, key];
  }

  async function save() {
    busy = true;
    error = '';
    try {
      const payload = {
        name,
        description,
        accounting_category: accountingCategory || null,
        rate_scheme: rateSchemeId || null,
        active_modifiers: activeModifiers,
        est_qty: estimatedBillableQty || null,
      };
      if (isEdit && task) {
        await api.patch(
          `/api/est-worksheets/${worksheetId}/tasks/${task.plan_task_id}/`,
          payload,
        );
      } else if (createMode === 'template') {
        if (!templateId) { error = 'Please select a template.'; busy = false; return; }
        await api.post(`/api/est-worksheets/${worksheetId}/add-from-template/`, {
          task_template_id: Number(templateId),
          est_qty: estimatedBillableQty || null,
          rate_scheme: rateSchemeId || null,
          active_modifiers: activeModifiers,
        });
      } else {
        await api.post(`/api/est-worksheets/${worksheetId}/tasks/`, payload);
      }
      onSaved();
    } catch (e) {
      if (e.data && typeof e.data === 'object' && !e.data.detail) {
        error = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = e.message || 'Could not save task.';
      }
    } finally {
      busy = false;
    }
  }
</script>

{#if open}
  <div class="overlay">
    <div class="modal">
      <h3>{title}</h3>

      {#if !isEdit}
        <div class="mode-toggle">
          <label><input type="radio" bind:group={createMode} value="freeform"> Freeform</label>
          <label><input type="radio" bind:group={createMode} value="template"> From Template</label>
        </div>
      {/if}

      {#if createMode === 'template' && !isEdit}
        <p>
          <label><strong>Template *</strong><br>
            <select bind:value={templateId}>
              <option value="">-- Select template --</option>
              {#each templates as tmpl}
                <option value={tmpl.template_id}>{tmpl.template_name}</option>
              {/each}
            </select>
          </label>
        </p>
      {:else}
        <p>
          <label><strong>Name *</strong><br>
            <input type="text" bind:value={name} style="width:100%;box-sizing:border-box;">
          </label>
        </p>
        <p>
          <label><strong>Description</strong><br>
            <input type="text" bind:value={description} style="width:100%;box-sizing:border-box;">
          </label>
        </p>
        <p>
          <label><strong>Accounting Category</strong><br>
            <select bind:value={accountingCategory}>
              <option value="">-- None --</option>
              {#each categories as cat}
                <option value={cat.id}>{cat.code} — {cat.name}</option>
              {/each}
            </select>
          </label>
        </p>
      {/if}

      <p>
        <label><strong>Rate scheme</strong><br>
          <select bind:value={rateSchemeId}>
            <option value="">-- None (no billing) --</option>
            {#each schemes as scheme}
              <option value={scheme.rate_scheme_id}>{scheme.name}</option>
            {/each}
          </select>
        </label>
      </p>

      {#if selectedScheme}
        <p><strong>{selectedScheme.name}</strong> — ${selectedScheme.rate}/{selectedScheme.unit_label}</p>
        {#if (selectedScheme.modifiers || []).length > 0}
          <fieldset>
            <legend><strong>Modifiers</strong></legend>
            {#each selectedScheme.modifiers as mod}
              <label>
                <input type="checkbox"
                  checked={activeModifiers.includes(mod.key)}
                  onchange={() => toggleModifier(mod.key)}>
                {mod.label} (+{mod.percent}%)
              </label><br>
            {/each}
          </fieldset>
        {/if}
        <p>
          <label><strong>Estimated billable qty</strong><br>
            <input type="number" step="0.01" bind:value={estimatedBillableQty}>
          </label>
        </p>
        {#if chargePreview !== null}
          <p><strong>Estimated charge:</strong> ${chargePreview}</p>
        {/if}
      {/if}

      <div class="buttons">
        <button type="button" onclick={save} disabled={busy}>Save</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center; z-index: 200;
  }
  .modal { background: white; padding: 16px; max-width: 500px; width: 90%; border: 1px solid #ccc; }
  .mode-toggle { display: flex; gap: 16px; margin-bottom: 12px; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
