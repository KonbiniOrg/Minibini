<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { parseDurationToISO, isoHoursFromDuration, parseDurationToHours } from '../lib/format.js';
  import { triageError } from '../lib/errorTriage.js';
  import { showError } from '../stores/messages.js';
  import FieldError from './FieldError.svelte';
  import FormMessage from './FormMessage.svelte';
  import Modal from './Modal.svelte';
  import UnitsSelect from './UnitsSelect.svelte';

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
    // Money-field write gate (task-owned-money Phase 1). Manual mode: gates
    // rate/unit_label/accounting_category/active_modifiers per MONEY_FIELDS
    // on TaskSerializer. Template mode: add-from-template is
    // IsAuthenticated-only overall, but as of Task 12b it 403s on the mere
    // presence of `active_modifiers` in the payload unless the caller can
    // manage the job's money — same CanManageJobOrPM/can_manage_financials
    // rule, gating that one field. In edit mode, item.can_manage
    // (JobScopedCanManageMixin, already resolved server-side for this task's
    // job) wins when present; this prop is the fallback for create (no item
    // yet) and the override if a caller ever needs one.
    canManage = true,
    categories = [], // AccountingCategory list, for the edit-mode category select/label
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let templateId = $state('');
  let lastFilledTemplateId = $state('');
  let rateSchemeId = $state('');
  let name = $state('');
  let description = $state('');
  let activeModifiers = $state([]); // list of modifier KEYS — the checkbox interaction model
  let estQty = $state('');
  let estWorkerTime = $state(''); // accepts "HH:MM" or "" for null
  let busy = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});
  let saveToCatalog = $state(false); // custom-task create only: also save as a ServiceItem
  let taskCreated = $state(false);   // guards double task-create if catalog save fails + retry

  // Quantity structure (spec §9, task-owned-money Phase 4 Task 4):
  // qty_scales_with_parent renders ONLY on subtask forms — creating a
  // subtask (context 'subtask') or editing one (item.parent_task set).
  // Not a MONEY_FIELD (it shapes the ESTIMATE, like est_qty — see
  // TaskSerializer's docstring), so it's sent unconditionally, never
  // gated on effectiveCanManage. parentInfo is this form's own fetch of
  // the parent task (unit_label/est_qty) — self-contained, same pattern
  // as the onMount scheme fetch above — so no caller needs to
  // thread the parent object through.
  let qtyScalesWithParent = $state(true);
  let parentInfo = $state(null);
  let lastLoadedParentId = $state(null);
  let lastDefaultedParentId = $state(null);

  // Edit-mode money fields: the task's OWN stamped values (task-owned money
  // Phase 1 — rate_scheme is a create-only trigger, never re-forwarded on
  // PATCH, so editing works directly off the task, not a re-pick dropdown).
  let editRate = $state('');
  let editUnitLabel = $state('');
  let editAccountingCategory = $state('');

  // Create-mode AC override (task-owned-money Phase 3, Task 2): the server
  // always stamps rate/unit_label from the chosen preset, but a manager may
  // now override the stamped accounting_category — including clearing it
  // to null ("categorize at invoicing") — so this one field gets its own
  // editable select in create mode too, defaulted from the picked scheme
  // (see lastFilledSchemeId effect below, same fill-once-then-editable
  // pattern as the template-mode field-fill effect).
  let createAccountingCategory = $state('');
  let lastFilledSchemeId = $state('');

  let schemes = $state([]);
  let loading = $state(true);
  // The shop's configured default preset, preselects the CREATE dropdown.
  // Read straight off the `is_default` flag on the already-fetched
  // task-applicable list (RM browser-testing note 3): the old approach hit
  // /api/settings/ for this, which is CanManageConfig-gated and 403s
  // silently for a permissionless worker, so the dropdown never preselected
  // and submit hit the required-scheme error. The list itself is
  // IsAuthenticated-only, so this now works for every user who can open
  // this form at all.
  let defaultSchemeId = $state('');

  onMount(async () => {
    try {
      const resp = await api.get('/api/rate-schemes/?task_applicable=true');
      schemes = resp.results || resp;
      const defaultRow = schemes.find((s) => s.is_default);
      defaultSchemeId = defaultRow ? defaultRow.rate_scheme_id : '';
    } catch (e) {
      formError = e.message || 'Could not load rate schemes.';
    } finally {
      loading = false;
    }
  });

  // Populate when opening or when prefill changes.
  // Modifiers arrive in two shapes depending on source: a ServiceItem's
  // default_active_modifiers is bare keys, a Task's active_modifiers is now
  // {key, label, percent} snapshot dicts (task-owned money Phase 1). The
  // checkbox interaction model stays keys-only either way.
  function loadModifiers(value) {
    if (!Array.isArray(value)) { activeModifiers = []; return; }
    activeModifiers = value.map((v) => (typeof v === 'string' ? v : v?.key)).filter(Boolean);
  }

  $effect(() => {
    if (!open) return;
    if (isEdit && item) {
      name = item.name || '';
      description = item.description || '';
      // rate_scheme is a create-only stamping trigger (write-only on the
      // serializer, never echoed back, never re-forwarded on PATCH) — no
      // re-pick dropdown in edit mode. The task's own money fields below
      // are the price of record.
      rateSchemeId = '';
      loadModifiers(item.active_modifiers);
      editRate = item.rate ?? '';
      editUnitLabel = item.unit_label ?? '';
      editAccountingCategory = item.accounting_category ?? '';
      estQty = item.est_qty ?? '';
      // Seeded from the item snapshot's OWN unit_label, not the live
      // `isHourUnit` derived — that derived reads editUnitLabel, which this
      // same effect writes two lines up. Reading it here would make the
      // effect depend on the field it just set, so editing the Unit
      // dropdown (which changes editUnitLabel, which changes isHourUnit)
      // would re-trigger this whole populate block and stomp the user's
      // pick right back to item.unit_label — the Unit field would look
      // editable but silently snap back on every change.
      estWorkerTime = item.est_worker_time
        ? formatDuration(item.est_worker_time)
        : (item.unit_label === 'hour' ? (item.est_qty ?? '') : '');
      templateId = '';
      // Subtask forms only (item.parent_task set) — read the flag straight
      // off the task, matching the fill-once-then-freely-editable pattern
      // used elsewhere in this form (never re-defaulted from the parent's
      // unit once a real value exists to show).
      qtyScalesWithParent = item.qty_scales_with_parent ?? true;
    } else {
      name = (mode === 'manual' ? (presetName || '') : ''); description = '';
      activeModifiers = [];
      editRate = ''; editUnitLabel = ''; editAccountingCategory = '';
      createAccountingCategory = ''; lastFilledSchemeId = '';
      estQty = ''; estWorkerTime = '';
      // Redefaulted once parentInfo loads (see the effect below) —
      // true here is just the pre-fetch placeholder.
      qtyScalesWithParent = true;
      lastDefaultedParentId = null;
      // Keep numeric so it matches the numeric <option value={tmpl.template_id}>
      // (Svelte 5 selects match option values with strict ===; String() here left
      // the preset unselected in the pulldown).
      templateId = (mode === 'template' && presetTemplateId != null) ? presetTemplateId : '';
      lastFilledTemplateId = '';
      // Read both unconditionally (not via short-circuited &&) so this
      // effect keeps depending on `schemes` even while `defaultSchemeId` is
      // still its initial '' — otherwise the dependency-tracker never
      // subscribes to `schemes`, and the later async update that actually
      // resolves the default preset never triggers a rerun.
      const defaultInList = schemes.some((s) => String(s.rate_scheme_id) === String(defaultSchemeId));
      if (mode === 'manual' && rateScheme) {
        rateSchemeId = rateScheme.rate_scheme_id;
      } else if (mode === 'manual' && defaultSchemeId && defaultInList) {
        // Preselect the shop's configured default preset — but only when
        // it's actually offered here (task_applicable=true already excludes
        // percentage schemes; a default naming a retired one would also
        // fail this check). Otherwise leave the dropdown unselected rather
        // than preselect a value it doesn't render. Number(): Configuration
        // values are always strings, but Svelte 5 selects match <option>
        // values with strict === and s.rate_scheme_id is numeric — same
        // pitfall already noted below for the template pulldown.
        rateSchemeId = Number(defaultSchemeId);
      } else {
        rateSchemeId = '';
      }
    }
    saveToCatalog = false;
    taskCreated = false;
    formError = '';
    fieldErrs = {};
  });

  // Quantity structure (spec §9, Phase 4 Task 4): the parent task id for
  // THIS form instance — creating a subtask (contextId IS the parent) or
  // editing one (item.parent_task). null on every other surface (job-level
  // create/edit, template mode), which is exactly when the flag is inert.
  const parentTaskId = $derived(
    (!isEdit && mode === 'manual' && context === 'subtask') ? contextId
    : (isEdit && item?.parent_task != null) ? item.parent_task
    : null
  );
  const isSubtaskForm = $derived(parentTaskId != null);

  // Self-contained fetch of the parent task (unit_label + est_qty) — same
  // fetch-on-open pattern as onMount's scheme load, just keyed on
  // parentTaskId instead of mount. Refetches only when the parent identity
  // actually changes (not on every keystroke).
  $effect(() => {
    if (!open || parentTaskId == null) {
      parentInfo = null;
      lastLoadedParentId = null;
      return;
    }
    if (String(parentTaskId) === String(lastLoadedParentId)) return;
    lastLoadedParentId = parentTaskId;
    (async () => {
      try {
        parentInfo = await api.get(`/api/tasks/${parentTaskId}/`);
      } catch (e) {
        parentInfo = null;
      }
    })();
  });

  // CREATE only: default the checkbox from the parent's unit_label once
  // parentInfo arrives — unit-keyed ('ea' -> true), mirroring
  // TaskService.create_direct's server-side default exactly (spec §9 rule
  // 2) so what the checkbox shows is what the server would pick if the
  // field were omitted. Fires once per parent identity, then the user is
  // free to override without being redefaulted (same fill-once pattern as
  // the template/scheme-fill effects above). Edit mode never redefaults —
  // it reads the task's own already-persisted value instead (see the
  // populate effect above).
  $effect(() => {
    if (isEdit) return;
    if (!open || !isSubtaskForm || !parentInfo) return;
    if (String(parentTaskId) === String(lastDefaultedParentId)) return;
    lastDefaultedParentId = parentTaskId;
    qtyScalesWithParent = parentInfo.unit_label === 'ea';
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
    rateSchemeId = selectedTemplate.rate_scheme ?? '';
    // If schemes hasn't loaded yet, isHourUnit reads false here and this default
    // could wrongly apply to an hour-unit template — but it's inert: save()
    // recomputes est_qty from live isHourUnit, ignoring this stale estQty.
    if (!isHourUnit) {
      estQty = '1'; // templates no longer carry a default qty; estimator sets the magnitude
    }
  });

  const selectedScheme = $derived(
    (mode === 'manual' && rateScheme && rateScheme.rate_scheme_id === Number(rateSchemeId))
      ? rateScheme
      : (schemes.find(s => s.rate_scheme_id === Number(rateSchemeId)) || null)
  );

  // Manual create mode: default the (now-editable, manager-only)
  // accounting_category field from the picked scheme's own AC each time
  // the scheme selection changes — same fill-once-then-freely-editable
  // pattern as the template-mode field-fill effect above. Harmless to seed
  // even for a non-manager; the field is simply never rendered/sent for one.
  $effect(() => {
    if (mode !== 'manual' || isEdit) return;
    if (rateSchemeId === lastFilledSchemeId) return;
    lastFilledSchemeId = rateSchemeId;
    createAccountingCategory = selectedScheme?.accounting_category ?? '';
  });

  // Task-owned money (Phase 1): whether THIS user may write money fields
  // (rate/unit_label/accounting_category/qty_source/active_modifiers) —
  // MONEY_FIELDS on the Task serializer, CanManageJobOrPM or
  // can_manage_financials. In edit mode item.can_manage (already resolved
  // server-side for this task's job) wins when present; the canManage prop
  // covers create (no item yet) or a caller override. Also drives the
  // template-mode modifier gate (Task 12b: add-from-template's
  // `active_modifiers` key).
  const effectiveCanManage = $derived(
    (isEdit && item && typeof item.can_manage === 'boolean') ? item.can_manage : canManage
  );

  // In edit mode there's no re-pick dropdown (rate_scheme is create-only —
  // see the effect above), so modifier CHECKBOX DEFINITIONS come from the
  // task's original source scheme, looked up in the same task-applicable
  // list the create dropdown uses. Absent (retired/deleted preset, or a
  // legacy task with no source_scheme) means no definitions to build
  // checkboxes from — the existing snapshot stays display-only and untouched
  // on save.
  const modifierScheme = $derived(
    (mode === 'manual' && isEdit)
      ? (item?.source_scheme != null
          ? (schemes.find(s => String(s.rate_scheme_id) === String(item.source_scheme)) || null)
          : null)
      : selectedScheme
  );

  const showMoneyFields = $derived((mode === 'manual' && isEdit) || !!selectedScheme);

  // Keys on unit_label, not algorithm: hour-unit schemes (elapsed, and any
  // entered-qty scheme priced per hour) collapse to a single input whose
  // value drives both est_qty and est_worker_time.
  const isHourUnit = $derived(
    (mode === 'manual' && isEdit) ? editUnitLabel === 'hour' : (selectedScheme?.unit_label === 'hour')
  );

  // Live preview inputs for the ALWAYS-visible inline derived-expectation
  // line (spec §9 rule 3: "the subtask form ALWAYS shows the derived
  // expectation inline"). Mirrors save()'s own estQtyValue resolution
  // (hour-unit schemes drive qty from the parsed worker-time field) so the
  // preview never diverges from what actually gets submitted.
  const childUnitLabelForPreview = $derived(
    isHourUnit ? 'hours'
      : (((mode === 'manual' && isEdit) ? editUnitLabel : selectedScheme?.unit_label) || '')
  );
  const childQtyPreview = $derived.by(() => {
    if (isHourUnit) {
      const h = parseDurationToHours(estWorkerTime);
      return (h === null || h === false) ? null : h;
    }
    const n = parseFloat(estQty);
    return Number.isFinite(n) ? n : null;
  });
  const parentEstQtyPreview = $derived.by(() => {
    if (!parentInfo || parentInfo.est_qty == null || parentInfo.est_qty === '') return null;
    const n = parseFloat(parentInfo.est_qty);
    return Number.isFinite(n) ? n : null;
  });
  // The ONE multiplier this preview uses — mirrors Task._parent_multiplier()
  // (apps/jobs/models.py): flag-false is always ×1; flag-true with no
  // parent est_qty ALSO falls back to ×1, but the template below renders
  // that case as an explicit "not set" state rather than a bare number
  // (carried reviewer note, Task 1 -> Task 4 — never a silent x1).
  //
  // This IS a client-side reimplementation of that backend formula, for an
  // unsaved input a fetch round-trip can't preview — the same established
  // pattern as RateSchemeManager.svelte's `previewTotal`, which has
  // re-implemented Task.effective_rate() the same way since task-owned-
  // money Phase 1. Both carry the same risk: a backend rounding/clamping
  // change (quantization, a future minimum, whatever) can drift silently
  // out from under either preview. Anchored against the backend's own
  // fixture numbers by a Vitest "drift tripwire" below — if you change
  // `_parent_multiplier()`'s math, that test is the one to go re-check.
  const expectedPreview = $derived.by(() => {
    if (childQtyPreview == null) return null;
    if (!qtyScalesWithParent || parentEstQtyPreview == null) return childQtyPreview;
    return childQtyPreview * parentEstQtyPreview;
  });

  function categoryLabel(id) {
    if (id == null || id === '') return '—';
    const cat = categories.find((c) => String(c.id) === String(id));
    return cat ? `${cat.code} — ${cat.name}` : `#${id}`;
  }

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
    if (!isEdit && mode === 'manual' && !rateSchemeId) {
      formError = 'Please pick a rate scheme.';
      return;
    }

    const estWorkerTimeISO = parseDurationToISO(estWorkerTime);
    if (estWorkerTimeISO === false) {
      formError = `Could not parse "${estWorkerTime}" as a duration. Use HH:MM (e.g. 1:30) or decimal hours (e.g. 1.5).`;
      return;
    }
    // Hour-unit schemes have one input (the worker-time field, relabeled
    // "Estimated hours"); est_qty is derived from the already-parsed ISO
    // value above so the two never diverge and we don't reparse the raw string.
    const estQtyValue = isHourUnit
      ? isoHoursFromDuration(estWorkerTimeISO)
      : (estQty || null);

    busy = true;
    try {
      if (isEdit && item) {
        // Money fields (rate/unit_label/accounting_category/active_modifiers)
        // are MONEY_FIELDS on the Task serializer — the raw key's mere
        // presence in the request is what the server gates on, so a
        // non-manager's payload must omit them entirely, not send unchanged
        // values. rate_scheme is never sent here — it's a create-only
        // stamping trigger.
        const editPayload = {
          name,
          description,
          est_qty: estQtyValue,
          est_worker_time: estWorkerTimeISO,
        };
        // Subtask forms only — inert (and omitted) on a top-level task, same
        // as the model field itself (spec §9 rule 2). Not a MONEY_FIELD, so
        // unconditional regardless of effectiveCanManage.
        if (isSubtaskForm) {
          editPayload.qty_scales_with_parent = qtyScalesWithParent;
        }
        if (effectiveCanManage) {
          editPayload.rate = editRate;
          editPayload.unit_label = editUnitLabel;
          // '' is the select's "— none (categorize at invoicing) —" option
          // (task-owned-money Phase 3, Task 2) — map it to a real null so
          // the server clears the AC rather than rejecting an empty pk.
          editPayload.accounting_category = editAccountingCategory || null;
          // Only touch active_modifiers when we actually have the selected
          // preset's modifier definitions to resolve checked keys into
          // {key, label, percent} snapshots (the model field's real shape on
          // PATCH — direct setattr, no stamp_from_scheme resolution like
          // create gets). Without definitions, leave existing modifiers
          // untouched rather than guess.
          if (modifierScheme) {
            editPayload.active_modifiers = (modifierScheme.modifiers || [])
              .filter((m) => activeModifiers.includes(m.key))
              .map((m) => ({ key: m.key, label: m.label, percent: m.percent }));
          }
        }
        const url = `/api/jobs/${contextId}/tasks/${item.task_id}/`;
        await api.patch(url, editPayload);
      } else if (mode === 'template') {
        // add-from-template is IsAuthenticated-only overall, but (Task 12b)
        // 403s on the mere presence of `active_modifiers` unless the caller
        // can manage the job's money — same convention as the money-field
        // gates elsewhere in this form: a non-manager must omit the key
        // entirely (never send `[]`) and let the template's own
        // default_active_modifiers ride the stamp server-side.
        const url = `/api/jobs/${contextId}/add-from-template/`;
        const payload = {
          service_item_id: Number(templateId),
          name,
          description,
          est_qty: estQtyValue,
          est_worker_time: estWorkerTimeISO,
        };
        if (effectiveCanManage) {
          payload.active_modifiers = activeModifiers;
        }
        await api.post(url, payload);
      } else {
        // Manual create: rate_scheme (the preset id) is open to everyone —
        // it's how a worker's "stamp-only" creation happens. active_modifiers
        // and accounting_category are MONEY_FIELDS (their key's mere
        // presence gates on CanManageJobOrPM/financials), so a non-manager
        // must omit them entirely and ride the stamp, never send an
        // unchanged/blank value. rate/unit_label are never sent here — the
        // server always stamps those from the chosen preset regardless of
        // what's submitted, so there's nothing to gain by including them;
        // accounting_category is the one stamped field a manager may
        // override at create time (task-owned-money Phase 3, Task 2),
        // including clearing it to null via the "none" option.
        const payload = {
          name,
          description,
          rate_scheme: rateSchemeId,
          est_qty: estQtyValue,
          est_worker_time: estWorkerTimeISO,
        };
        if (effectiveCanManage) {
          payload.active_modifiers = activeModifiers;
          payload.accounting_category = createAccountingCategory || null;
        }
        let url;
        if (context === 'subtask') {
          url = `/api/tasks/${contextId}/subtasks/`;
          // Not a MONEY_FIELD — est-shaping like est_qty, open to whoever
          // may create the subtask at all (see TaskSerializer's docstring).
          payload.qty_scales_with_parent = qtyScalesWithParent;
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

        {#if mode === 'manual' && isEdit}
          <!-- rate_scheme is a create-only stamping trigger (write-only,
               never re-forwarded on PATCH) — no re-pick dropdown here. This
               names the preset the task was originally stamped from;
               editable money fields are below. -->
          <p><strong>Scheme:</strong> {item?.source_scheme_name || '—'}</p>
        {:else if mode === 'manual'}
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

        {#if mode === 'manual' && isEdit}
          <!-- The task's own stamped money — editable only for a manager
               (item.can_manage / CanManageJobOrPM / financials). Create-time
               never gets this treatment: the server always stamps rate/unit/
               category from the chosen preset regardless of what's
               submitted, so there's nothing for an editable field to do
               before the task exists. -->
          {#if effectiveCanManage}
            <p>
              <label><strong>Rate</strong><br>
                <input type="number" step="0.01" bind:value={editRate}>
              </label>
              <span class="rate-per">per</span>
              <label><strong>Unit</strong><br>
                <UnitsSelect bind:value={editUnitLabel} />
              </label>
              <FieldError errors={fieldErrs} field="rate" />
              <FieldError errors={fieldErrs} field="unit_label" />
            </p>
            <p>
              <label><strong>Accounting Category</strong><br>
                <select bind:value={editAccountingCategory}>
                  <option value="">— none (categorize at invoicing) —</option>
                  {#each categories as cat (cat.id)}
                    <option value={cat.id}>{cat.code} — {cat.name}</option>
                  {/each}
                </select>
              </label>
              <FieldError errors={fieldErrs} field="accounting_category" />
            </p>
          {:else}
            <p><strong>Rate:</strong> ${editRate || '0.00'}/{editUnitLabel || 'none'}</p>
            <p><strong>Accounting Category:</strong> {categoryLabel(editAccountingCategory)}</p>
          {/if}
          {#if modifierScheme && modifierScheme.modifiers && modifierScheme.modifiers.length > 0}
            <fieldset>
              <legend><strong>Modifiers</strong></legend>
              {#each modifierScheme.modifiers as m (m.key)}
                <p>
                  <label>
                    <input
                      type="checkbox"
                      checked={activeModifiers.includes(m.key)}
                      disabled={!effectiveCanManage}
                      onchange={(e) => toggleModifier(m.key, e.target.checked)}
                    />
                    {m.label} (+{m.percent}%)
                  </label>
                </p>
              {/each}
              <FieldError errors={fieldErrs} field="active_modifiers" />
            </fieldset>
          {/if}
        {:else if selectedScheme}
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
          {#if mode === 'manual'}
            <!-- Defaults to the preset's stamped AC (see the fill effect
                 above); a manager may override it here, including clearing
                 it to "none" (task-owned-money Phase 3, Task 2). Non-managers
                 get a read-only preview — the server stamps from the preset
                 regardless of what a worker's payload would say, and workers
                 never send accounting_category at all (MONEY_FIELDS gate). -->
            {#if effectiveCanManage}
              <p>
                <label><strong>Accounting Category</strong><br>
                  <select bind:value={createAccountingCategory}>
                    <option value="">— none (categorize at invoicing) —</option>
                    {#each categories as cat (cat.id)}
                      <option value={cat.id}>{cat.code} — {cat.name}</option>
                    {/each}
                  </select>
                </label>
                <FieldError errors={fieldErrs} field="accounting_category" />
              </p>
            {:else if selectedScheme.accounting_category}
              <p><strong>Accounting Category:</strong> {categoryLabel(selectedScheme.accounting_category)}</p>
            {/if}
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
                      disabled={!effectiveCanManage}
                      onchange={(e) => toggleModifier(m.key, e.target.checked)}
                    />
                    {m.label} (+{m.percent}%)
                  </label>
                </p>
              {/each}
              <FieldError errors={fieldErrs} field="active_modifiers" />
            </fieldset>
          {/if}
        {/if}

        {#if showMoneyFields && !isHourUnit}
          <p>
            <label><strong>Estimated qty</strong><br>
              <input type="number" step="0.01" bind:value={estQty}>
              <small>{(mode === 'manual' && isEdit) ? editUnitLabel : selectedScheme?.unit_label}</small>
            </label>
            <FieldError errors={fieldErrs} field="est_qty" />
          </p>
        {/if}

        <p>
          <label><strong>{isHourUnit ? 'Estimated hours' : 'Estimated worker time'}</strong><br>
            <input type="text" placeholder="e.g. 1:30 or 1.5" bind:value={estWorkerTime}>
            <small>'HH:MM or decimal hours (1.5 = 1h30m)'</small>
          </label>
          <FieldError errors={fieldErrs} field="est_worker_time" />
          {#if isHourUnit}<FieldError errors={fieldErrs} field="est_qty" />{/if}
        </p>

        {#if isSubtaskForm}
          <!-- Quantity structure (spec §9 rule 2): functional and rendered
               ONLY on a subtask form. Default is unit-keyed from the
               parent's own unit_label (see the effect above); freely
               overridable from there — "let users complain" per RM. -->
          <p>
            <label>
              <input type="checkbox" bind:checked={qtyScalesWithParent}>
              Scales with parent quantity (per-unit estimate × parent qty)
            </label>
          </p>
          <!-- ALWAYS visible (spec §9 rule 3) — never hidden behind a toggle,
               and NEVER a silently-computed number when the parent has no
               qty yet (carried reviewer note, Task 1 -> Task 4). -->
          <p class="derived-expectation">
            {#if childQtyPreview == null}
              <em>Enter an estimated quantity to see the expected total.</em>
            {:else if !qtyScalesWithParent}
              {childQtyPreview} {childUnitLabelForPreview} per batch — fixed regardless of parent quantity.
            {:else if parentEstQtyPreview == null}
              <em>Parent quantity not set — treated as ×1.</em>
              Expected: {childQtyPreview} {childUnitLabelForPreview}.
            {:else}
              {childQtyPreview} {childUnitLabelForPreview} × {parentEstQtyPreview} {parentInfo?.unit_label || 'parent unit'}
              = <strong>{expectedPreview} expected</strong>
            {/if}
          </p>
        {/if}

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
