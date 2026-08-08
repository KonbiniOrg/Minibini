<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { parseDurationToISO, isoHoursFromDuration } from '../lib/format.js';
  import { triageError } from '../lib/errorTriage.js';
  import { showError } from '../stores/messages.js';
  import FieldError from './FieldError.svelte';
  import FormMessage from './FormMessage.svelte';
  import Modal from './Modal.svelte';
  import UnitsSelect from './UnitsSelect.svelte';

  let {
    open = false,
    mode = 'manual', // 'manual' | 'template'
    context = 'job', // 'job' (subtasks removed 2026-08, better-fees spec §3)
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
    // rule, gating that one field. In edit mode, item.can_write_money (RM
    // browser-testing note 6 — a SerializerMethodField reusing the server's
    // own TaskSerializer._can_write_money() gate, NOT item.can_manage,
    // which is the can_manage_jobs-atom-or-PM test only and misses
    // financials-only callers) wins when present; this prop is the
    // fallback for create (no item yet) and the override if a caller ever
    // needs one.
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

  // Edit-mode money fields: the task's OWN stamped values (task-owned money
  // Phase 1 — rate_scheme is a create-only trigger, never re-forwarded on
  // PATCH). RM browser-testing note 5 added a SEPARATE re-pick mechanism,
  // source_scheme, for edit mode only: picking a different scheme in the
  // dropdown below client-side RESTAMPS these three fields (plus
  // activeModifiers) from the new scheme's list data — see the restamp
  // $effect below. Editing continues to work directly off these fields
  // either way; the dropdown is just a fast way to reseed them.
  let editRate = $state('');
  let editUnitLabel = $state('');
  let editAccountingCategory = $state('');
  // Edit mode: the Rate Scheme dropdown's current selection — starts as the
  // task's original source_scheme (preselected, see the populate effect
  // below) and moves to whatever the user picks next.
  let editSourceSchemeId = $state('');
  // Guards the restamp effect below: only actually restamp when
  // editSourceSchemeId is a DIFFERENT value than what was last restamped
  // from — mirrors lastFilledSchemeId's fill-once guard pattern, but (unlike
  // that one-time default) fires again on every distinct value, since a
  // restamp is a deliberate re-pick each time, not a one-shot default.
  let lastRestampedSchemeId = $state('');

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
      // Preselect the Rate Scheme dropdown to the task's CURRENT provenance
      // (RM browser-testing note 5). lastRestampedSchemeId is synced to the
      // same value in this same synchronous block so the restamp $effect
      // below sees them already equal on its first run and does NOT fire —
      // the money fields above are already seeded from the task's own
      // persisted values, not from re-deriving the current scheme's
      // (possibly since-edited) list data. Recomputed from `item.source_scheme`
      // independently rather than as `= editSourceSchemeId` — reading the
      // state var back here would make THIS effect depend on
      // editSourceSchemeId itself, so a later user pick (which writes that
      // same state var) would re-trigger this populate effect and snap the
      // selection right back to the task's original scheme. Same bug class
      // as the RM note 4 estWorkerTime/isHourUnit fix above — see that
      // comment for the general shape of the trap.
      editSourceSchemeId = item.source_scheme ?? '';
      lastRestampedSchemeId = item.source_scheme ?? '';
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
    } else {
      name = (mode === 'manual' ? (presetName || '') : ''); description = '';
      activeModifiers = [];
      editRate = ''; editUnitLabel = ''; editAccountingCategory = '';
      editSourceSchemeId = ''; lastRestampedSchemeId = '';
      estQty = ''; estWorkerTime = '';
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

  // Edit mode: the scheme currently selected in the Rate Scheme dropdown
  // (RM browser-testing note 5) — starts pointing at the task's original
  // source_scheme (see the populate effect above) and moves to whatever the
  // user picks next. Looked up in the same task-applicable `schemes` list
  // the create dropdown uses, so it resolves to null for either placeholder
  // state (a retired current scheme, or a null current scheme) — those
  // aren't selectable targets, so this derived never needs to represent
  // them as anything but "nothing to restamp from".
  const editSelectedScheme = $derived(
    (mode === 'manual' && isEdit)
      ? (schemes.find(s => String(s.rate_scheme_id) === String(editSourceSchemeId)) || null)
      : null
  );

  // Client-side restamp (RM browser-testing note 5): fires only on a
  // genuine CHANGE of the edit-mode Rate Scheme dropdown — re-selecting the
  // CURRENT scheme is naturally a no-op (editSourceSchemeId doesn't change
  // value, so this effect's dependency doesn't dirty and it never reruns;
  // no same-value reset path to build, deliberately, per RM). Prefills
  // rate/unit_label/accounting_category from the new scheme's list data and
  // replaces the modifier checkboxes WHOLESALE with the new scheme's
  // definitions, none checked — the user re-ticks before saving. Everything
  // stays editable and nothing persists until Save (explicit-save
  // doctrine).
  //
  // The blessed "reset" path is A -> B -> A: each hop is a real value
  // change and restamps, so landing back on A restamps to A's OWN current
  // list values — which may differ from what the task was originally
  // stamped with, if A's preset has been edited since. That's correct: a
  // fresh pick of A means exactly A's current data, not a memory of the
  // task's pre-edit state.
  $effect(() => {
    if (mode !== 'manual' || !isEdit) return;
    if (editSourceSchemeId === lastRestampedSchemeId) return;
    lastRestampedSchemeId = editSourceSchemeId;
    if (!editSelectedScheme) return; // disabled placeholder options can't actually be picked; defensive only
    editRate = editSelectedScheme.rate;
    editUnitLabel = editSelectedScheme.unit_label;
    editAccountingCategory = editSelectedScheme.accounting_category ?? '';
    activeModifiers = [];
  });

  // Task-owned money (Phase 1): whether THIS user may write money fields
  // (rate/unit_label/accounting_category/qty_source/active_modifiers) —
  // MONEY_FIELDS on the Task serializer, CanManageJobOrPM or
  // can_manage_financials. RM browser-testing note 6: this must read
  // item.can_write_money, NOT item.can_manage — can_manage
  // (JobScopedCanManageMixin) is the can_manage_jobs-atom-or-PM test only
  // and EXCLUDES can_manage_financials, so a financials-only caller would
  // see money fields disabled/greyed here even though the server's own
  // write-gate (TaskSerializer._can_write_money) would accept the write.
  // can_write_money is a SerializerMethodField that reuses that exact gate
  // server-side, so this is the SAME test driving both the server's accept/
  // reject and the SPA's enable/grey signal — never two independently-
  // maintained tests that can drift apart. In edit mode item.can_write_money
  // (already resolved server-side for this task's job) wins when present;
  // the canManage prop covers create (no item yet, no such field to read —
  // create's own equivalent test lives server-side in the same place, see
  // TaskSerializer.validate) or a caller override. Also drives the
  // template-mode modifier gate (Task 12b: add-from-template's
  // `active_modifiers` key).
  const effectiveCanWriteMoney = $derived(
    (isEdit && item && typeof item.can_write_money === 'boolean') ? item.can_write_money : canManage
  );

  // Modifier CHECKBOX DEFINITIONS: in edit mode these track the CURRENTLY
  // SELECTED scheme in the Rate Scheme dropdown (editSelectedScheme —
  // RM browser-testing note 5), which starts at the task's original
  // source_scheme and moves with the user's pick (see the restamp effect
  // above); in create mode, the picked preset as before. Null (retired/null
  // current scheme never re-picked, or nothing picked yet in create) means
  // no definitions to build checkboxes from — the existing snapshot stays
  // display-only and untouched on save.
  const modifierScheme = $derived(
    (mode === 'manual' && isEdit) ? editSelectedScheme : selectedScheme
  );

  const showMoneyFields = $derived((mode === 'manual' && isEdit) || !!selectedScheme);

  // Keys on unit_label, not algorithm: hour-unit schemes (elapsed, and any
  // entered-qty scheme priced per hour) collapse to a single input whose
  // value drives both est_qty and est_worker_time.
  const isHourUnit = $derived(
    (mode === 'manual' && isEdit) ? editUnitLabel === 'hour' : (selectedScheme?.unit_label === 'hour')
  );

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
        if (effectiveCanWriteMoney) {
          editPayload.rate = editRate;
          editPayload.unit_label = editUnitLabel;
          editPayload.accounting_category = editAccountingCategory;
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
          // source_scheme (RM browser-testing note 5): only sent when it
          // actually changed from the task's original provenance — its
          // mere presence is what TaskSerializer.MONEY_FIELDS gates on, and
          // an unchanged re-select never fires the restamp effect in the
          // first place (see above), so there's nothing new to report. The
          // rate/unit_label/accounting_category/active_modifiers above ARE
          // the restamp; the server just records this pointer alongside them.
          if (String(editSourceSchemeId) !== String(item.source_scheme ?? '')) {
            editPayload.source_scheme = editSourceSchemeId;
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
        if (effectiveCanWriteMoney) {
          payload.active_modifiers = activeModifiers;
        }
        await api.post(url, payload);
      } else {
        // Manual create: rate_scheme (the preset id) is open to everyone —
        // it's how a worker's "stamp-only" creation happens. active_modifiers
        // is a MONEY_FIELD (its key's mere presence gates on
        // CanManageJobOrPM/financials), so a non-manager must omit the key
        // entirely and ride the stamp (zero modifiers), never send `[]`.
        // rate/unit_label/accounting_category are never sent here — the
        // server always stamps those from the chosen preset regardless of
        // what's submitted, so there's nothing to gain by including them.
        const payload = {
          name,
          description,
          rate_scheme: rateSchemeId,
          est_qty: estQtyValue,
          est_worker_time: estWorkerTimeISO,
        };
        if (effectiveCanWriteMoney) {
          payload.active_modifiers = activeModifiers;
        }
        const url = `/api/jobs/${contextId}/tasks/`;
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
          <!-- rate_scheme (the write-only CREATE trigger prop) stays
               create-only — never re-forwarded on PATCH. RM browser-testing
               note 5 adds a SEPARATE edit-only re-pick: source_scheme,
               preselected to the task's current preset. A currently-retired
               scheme (not present in the task-applicable `schemes` list,
               since that fetch is is_active=True/non-percentage only) or a
               null source_scheme each render as a disabled placeholder
               option — informational only, never a selectable TARGET; real
               options are only active, non-percentage, task-applicable
               schemes, same list the create dropdown uses. Picking a
               genuinely different scheme fires the restamp $effect above.
               Non-managers get the same read-only name they always did —
               no dropdown, no restamp. -->
          {#if effectiveCanWriteMoney}
            <p>
              <label><strong>Rate Scheme</strong><br>
                <select bind:value={editSourceSchemeId}>
                  {#if item?.source_scheme != null && !schemes.some((s) => String(s.rate_scheme_id) === String(item.source_scheme))}
                    <option value={item.source_scheme} disabled>{item.source_scheme_name || 'Unknown'} (retired)</option>
                  {:else if item?.source_scheme == null}
                    <option value="" disabled>—</option>
                  {/if}
                  {#each schemes as s (s.rate_scheme_id)}
                    <option value={s.rate_scheme_id}>{s.name}</option>
                  {/each}
                </select>
              </label>
              <FieldError errors={fieldErrs} field="source_scheme" />
            </p>
          {:else}
            <p><strong>Scheme:</strong> {item?.source_scheme_name || '—'}</p>
          {/if}
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
          {#if effectiveCanWriteMoney}
            <p>
              <span class="rate-unit-row">
                <label><strong>Rate</strong><br>
                  <input type="number" step="0.01" bind:value={editRate} style="width:80px;">
                </label>
                <span class="rate-per">per</span>
                <label><strong>Unit</strong><br>
                  <UnitsSelect bind:value={editUnitLabel} />
                </label>
              </span>
              <FieldError errors={fieldErrs} field="rate" />
              <FieldError errors={fieldErrs} field="unit_label" />
            </p>
            <p>
              <label><strong>Accounting Category</strong><br>
                <select bind:value={editAccountingCategory}>
                  <option value="">-- select --</option>
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
                      disabled={!effectiveCanWriteMoney}
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
          {#if mode === 'manual' && selectedScheme.accounting_category}
            <!-- Create-time preview only — informational, not editable: the
                 server always stamps this from the chosen preset. -->
            <p><strong>Accounting Category:</strong> {categoryLabel(selectedScheme.accounting_category)}</p>
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
                      disabled={!effectiveCanWriteMoney}
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
  /* "Rate [input] per [unit]" on one line, controls bottom-aligned —
     matches RateSchemeManager's .rate-row. Rate input is fixed-width
     (matches the price-input convention used elsewhere, e.g.
     PurchaseOrderDetail/ReconciliationSection) so the row actually fits
     the modal instead of line-wrapping between "Rate" and "per". */
  .rate-unit-row { display: inline-flex; align-items: flex-end; gap: 8px; flex-wrap: nowrap; }
  .rate-unit-row .rate-per { padding-bottom: 3px; }
</style>
