<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { parseDurationToISO } from '../lib/format.js';
  import { triageError } from '../lib/errorTriage.js';
  import { showError } from '../stores/messages.js';
  import FieldError from './FieldError.svelte';
  import FormMessage from './FormMessage.svelte';
  import Modal from './Modal.svelte';

  let {
    open = false,
    mode = 'manual', // 'manual' | 'template'
    context = 'job', // 'job' | 'subtask'
    contextId = null, // job pk, worksheet pk, or parent task pk
    item = null,     // for edit mode; null for create
    isEdit = false,
    templates = [],
    rateScheme = null, // optional pre-selected RateScheme (manual mode only)
    presetTemplateId = null, // optional pre-selected ServiceItem id (template mode only)
    presetServiceItem = null, // full pre-picked ServiceItem object (template mode only):
                              // the Add-Work search is live, so it can return items the
                              // caller's cached `templates` list doesn't have yet (created
                              // in another window) — the pick carries the object so this
                              // form never re-resolves it from a stale list
    presetName = '', // optional pre-fill for the name (manual / custom-task create only)
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let templateId = $state('');
  let lastFilledTemplateId = $state('');
  let rateSchemeId = $state('');
  let name = $state('');
  let description = $state('');
  let activeModifiers = $state([]);
  let estQty = $state('');
  let estWorkerTime = $state(''); // accepts "HH:MM" or "" for null
  let busy = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});
  let saveToCatalog = $state(false); // custom-task create only: also save as a ServiceItem
  let taskCreated = $state(false);   // guards double task-create if catalog save fails + retry

  let schemes = $state([]);
  let loading = $state(true);

  onMount(async () => {
    try {
      const resp = await api.get('/api/rate-schemes/');
      schemes = resp.results || resp;
    } catch (e) {
      formError = e.message || 'Could not load rate schemes.';
    } finally {
      loading = false;
    }
  });

  // Populate when opening or when prefill changes
  // active_modifiers is always a list of modifier keys.
  function loadModifiers(value) {
    activeModifiers = Array.isArray(value) ? [...value] : [];
  }

  $effect(() => {
    if (!open) return;
    if (isEdit && item) {
      name = item.name || '';
      description = item.description || '';
      rateSchemeId = item.rate_scheme ?? '';
      loadModifiers(item.active_modifiers);
      estQty = item.est_qty ?? '';
      estWorkerTime = formatDuration(item.est_worker_time);
      templateId = '';
    } else {
      name = (mode === 'manual' ? (presetName || '') : ''); description = '';
      activeModifiers = [];
      estQty = ''; estWorkerTime = '';
      // Keep numeric so it matches the numeric <option value={tmpl.template_id}>
      // (Svelte 5 selects match option values with strict ===; String() here left
      // the preset unselected in the pulldown).
      templateId = (mode === 'template' && presetTemplateId != null) ? presetTemplateId : '';
      lastFilledTemplateId = '';
      if (mode === 'manual' && rateScheme) {
        rateSchemeId = rateScheme.rate_scheme_id;
      } else {
        rateSchemeId = '';
      }
    }
    saveToCatalog = false;
    taskCreated = false;
    formError = '';
    fieldErrs = {};
  });

  // In template mode, when the user picks a template, defaults flow downward.
  // presetServiceItem is the fallback for ids the cached list doesn't know.
  const selectedTemplate = $derived(
    templates.find(t => String(t.template_id) === String(templateId))
    || (presetServiceItem
        && String(presetServiceItem.template_id) === String(templateId)
        ? presetServiceItem : null)
  );
  // The pulldown needs an <option> for the preset even when the cached list
  // lacks it, or the select renders unselected with no matching entry.
  const presetMissingFromList = $derived(
    presetServiceItem
    && !templates.some(t => String(t.template_id) === String(presetServiceItem.template_id))
  );
  $effect(() => {
    if (mode !== 'template') return;
    if (!selectedTemplate) return;
    if (templateId === lastFilledTemplateId) return;
    lastFilledTemplateId = templateId;
    // User just picked (or switched) the template — overwrite fields with its defaults.
    // The user is free to delete or edit any field afterward; we won't refill.
    name = selectedTemplate.template_name || '';
    description = selectedTemplate.description || '';
    loadModifiers(selectedTemplate.default_active_modifiers);
    estQty = '1'; // templates no longer carry a default qty; estimator sets the magnitude
    rateSchemeId = selectedTemplate.rate_scheme ?? '';
  });

  const selectedScheme = $derived(
    (mode === 'manual' && rateScheme && rateScheme.rate_scheme_id === Number(rateSchemeId))
      ? rateScheme
      : (schemes.find(s => s.rate_scheme_id === Number(rateSchemeId)) || null)
  );

  function formatDuration(value) {
    // Server returns ISO 8601 like "PT1H30M" or HH:MM:SS — accept either, render HH:MM
    if (!value) return '';
    if (typeof value === 'string') {
      const isoMatch = value.match(/PT(?:(\d+)H)?(?:(\d+)M)?/);
      if (isoMatch) {
        const h = parseInt(isoMatch[1] || '0', 10);
        const m = parseInt(isoMatch[2] || '0', 10);
        return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
      }
      const hmsMatch = value.match(/(\d+):(\d+)/);
      if (hmsMatch) return `${hmsMatch[1].padStart(2, '0')}:${hmsMatch[2]}`;
    }
    return '';
  }

  function toggleModifier(key, checked) {
    if (checked) {
      if (!activeModifiers.includes(key)) {
        activeModifiers = [...activeModifiers, key];
      }
    } else {
      activeModifiers = activeModifiers.filter(k => k !== key);
    }
  }

  async function save() {
    formError = '';
    fieldErrs = {};
    if (!name || !name.trim()) {
      formError = 'Name is required.';
      return;
    }
    if (!isEdit && mode === 'template' && !templateId) {
      formError = 'Please pick a template.';
      return;
    }
    if (mode === 'manual' && !rateSchemeId) {
      formError = 'Please pick a rate scheme.';
      return;
    }

    const estWorkerTimeISO = parseDurationToISO(estWorkerTime);
    if (estWorkerTimeISO === false) {
      formError = `Could not parse "${estWorkerTime}" as a duration. Use HH:MM (e.g. 1:30) or decimal hours (e.g. 1.5).`;
      return;
    }

    busy = true;
    try {
      const payload = {
        name,
        description,
        rate_scheme: rateSchemeId,
        active_modifiers: activeModifiers,
        est_qty: estQty || null,
        est_worker_time: estWorkerTimeISO,
      };

      if (isEdit && item) {
        const url = `/api/jobs/${contextId}/tasks/${item.task_id}/`;
        await api.patch(url, payload);
      } else if (mode === 'template') {
        const url = `/api/jobs/${contextId}/add-from-template/`;
        await api.post(url, {
          service_item_id: Number(templateId),
          name,
          description,
          est_qty: estQty || null,
          active_modifiers: activeModifiers,
          est_worker_time: estWorkerTimeISO,
        });
      } else {
        let url;
        if (context === 'subtask') {
          url = `/api/tasks/${contextId}/subtasks/`;
        } else {
          url = `/api/jobs/${contextId}/tasks/`;
        }
        // taskCreated guards a double create if the optional catalog save fails + retry.
        if (!taskCreated) {
          await api.post(url, payload);
          taskCreated = true;
        }
        if (saveToCatalog) {
          await api.post('/api/service-items/', {
            template_name: name,
            description,
            rate_scheme: rateSchemeId,
            default_active_modifiers: activeModifiers,
          });
        }
      }
      onSaved();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message;
        fieldErrs = t.fields;
      }
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open} onCancel={onClose}>
<form onsubmit={(e) => { e.preventDefault(); if (!busy) save(); }}>
      <h3>{isEdit ? 'Edit Task' : (mode === 'template' ? 'Add Task From Template' : 'Add Manual Task')}</h3>

      {#if loading}
        <p>Loading rate schemes…</p>
      {:else}
        {#if !isEdit && mode === 'template'}
          <p>
            <label><strong>Template *</strong><br>
              <select bind:value={templateId}>
                <option value="">-- Select template --</option>
                {#if presetMissingFromList}
                  <option value={presetServiceItem.template_id}>{presetServiceItem.template_name}</option>
                {/if}
                {#each templates as tmpl (tmpl.template_id)}
                  <option value={tmpl.template_id}>{tmpl.template_name}</option>
                {/each}
              </select>
            </label>
            <FieldError errors={fieldErrs} field="service_item_id" />
          </p>
        {/if}

        {#if mode === 'manual'}
          {#if rateScheme}
            <p><strong>Rate Scheme:</strong> {rateScheme.name}</p>
          {:else}
            <p>
              <label><strong>Rate Scheme *</strong><br>
                <select bind:value={rateSchemeId}>
                  <option value="">-- select --</option>
                  {#each schemes as s (s.rate_scheme_id)}
                    <option value={s.rate_scheme_id}>{s.name}</option>
                  {/each}
                </select>
              </label>
              <FieldError errors={fieldErrs} field="rate_scheme" />
            </p>
          {/if}
        {/if}

        <p>
          <label><strong>Name *</strong><br>
            <input type="text" bind:value={name} style="width:100%;box-sizing:border-box;">
          </label>
          <FieldError errors={fieldErrs} field="name" />
        </p>
        <p>
          <!-- Textarea, matching Job Description in JobEditModal: a task
               description carries the per-job work specifics, which need
               line breaks. TaskDetailPage renders it with preserve-breaks. -->
          <label><strong>Description</strong><br>
            <textarea rows="4" bind:value={description} style="width:100%;box-sizing:border-box;"></textarea>
          </label>
          <FieldError errors={fieldErrs} field="description" />
        </p>

        {#if selectedScheme}
          {#if mode === 'template'}
            <p>
              <strong>Rate Scheme:</strong> {selectedScheme.name} —
              ${selectedScheme.rate}/{selectedScheme.unit_label}
              <small>(from template)</small>
            </p>
          {:else}
            <p>
              <strong>Rate:</strong> ${selectedScheme.rate}/{selectedScheme.unit_label}
              <small>(from rate scheme)</small>
            </p>
          {/if}
          {#if selectedScheme.modifiers && selectedScheme.modifiers.length > 0}
            <fieldset>
              <legend><strong>Modifiers</strong></legend>
              {#each selectedScheme.modifiers as m (m.key)}
                <p>
                  <label>
                    <input
                      type="checkbox"
                      checked={activeModifiers.includes(m.key)}
                      onchange={(e) => toggleModifier(m.key, e.target.checked)}
                    />
                    {m.label} (+{m.percent}%)
                  </label>
                </p>
              {/each}
              <FieldError errors={fieldErrs} field="active_modifiers" />
            </fieldset>
          {/if}

          <p>
            <label><strong>Estimated qty</strong><br>
              <input type="number" step="0.01" bind:value={estQty}>
              <small>{selectedScheme.unit_label}</small>
            </label>
            <FieldError errors={fieldErrs} field="est_qty" />
          </p>
        {/if}

        <p>
          <label><strong>Estimated worker time</strong><br>
            <input type="text" placeholder="e.g. 1:30 or 1.5" bind:value={estWorkerTime}>
            <small>HH:MM or decimal hours (1.5 = 1h30m)</small>
          </label>
          <FieldError errors={fieldErrs} field="est_worker_time" />
        </p>

        {#if mode === 'manual' && !isEdit}
          <p>
            <label>
              <input type="checkbox" bind:checked={saveToCatalog}>
              Save to catalog (reuse this as a service item)
            </label>
          </p>
        {/if}

        <div class="buttons">
          <button type="submit" disabled={busy}>Save</button>
          <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
        </div>
        <FormMessage error={formError} />
      {/if}
</form>
</Modal>


<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
</style>
