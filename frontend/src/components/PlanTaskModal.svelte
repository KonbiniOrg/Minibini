<script>
  import { api } from '../lib/api.js';
  import RateSchemeFieldset from './RateSchemeFieldset.svelte';

  let {
    open = false,
    mode = 'create-freeform', // 'create-freeform' | 'create-template' | 'edit'
    task = null,
    worksheetId = null,
    templates = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let createMode = $state('freeform');
  let name = $state('');
  let description = $state('');
  let templateId = $state('');
  let rateSchemeId = $state(task?.rate_scheme ?? '');
  let activeModifiers = $state(task?.active_modifiers ?? []);
  let estQty = $state(task?.est_qty ?? '');
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    if (open) {
      if (mode === 'edit' && task) {
        createMode = 'freeform';
        name = task.name || '';
        description = task.description || '';
        rateSchemeId = task.rate_scheme ?? '';
        activeModifiers = [...(task.active_modifiers || [])];
        estQty = task.est_qty ?? '';
        templateId = '';
      } else if (mode === 'create-template') {
        createMode = 'template';
        resetFields();
      } else {
        createMode = 'freeform';
        resetFields();
      }
      error = '';
    }
  });

  function resetFields() {
    name = ''; description = '';
    rateSchemeId = ''; estQty = '';
    activeModifiers = []; templateId = '';
  }

  const isEdit = $derived(mode === 'edit');
  const title = $derived(isEdit ? 'Edit Task' : 'Add Task');

  const selectedTemplate = $derived(
    templates.find(t => String(t.template_id) === String(templateId)) || null
  );

  $effect(() => {
    if (selectedTemplate) {
      activeModifiers = [...(selectedTemplate.default_active_modifiers || [])];
      if (selectedTemplate.default_billable_qty && !estQty) {
        estQty = selectedTemplate.default_billable_qty;
      }
      if (selectedTemplate.rate_scheme && !rateSchemeId) {
        rateSchemeId = selectedTemplate.rate_scheme;
      }
    }
  });

  async function save() {
    busy = true;
    error = '';
    try {
      const payload = {
        name,
        description,
        rate_scheme: rateSchemeId,
        active_modifiers: activeModifiers,
        est_qty: estQty,
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
          est_qty: estQty,
          rate_scheme: rateSchemeId,
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
      {/if}

      <RateSchemeFieldset
        bind:rateSchemeId
        bind:activeModifiers
        bind:estQty
      />

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
