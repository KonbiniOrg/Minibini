<script>
  // Dual-source picker for the line-add flow.
  // Shows service items and catalog inventory items together, driven by backend
  // search (no initial list — results appear after typing). Emits a single
  // onChoose callback; carries zero surface-specific logic.
  import SearchPicker from './SearchPicker.svelte';
  import Modal from './Modal.svelte';
  import { api } from '../lib/api.js';
  import { PICKER_PAGE_SIZE } from '../lib/pagination.js';

  // taskSurface: the task-list footer offers three explicit atom buttons
  // (Task / Material / Fee). Default (estimate) footer is the material checkbox
  // + "Add Line" (there, tasks come only from a ServiceItem pick).
  let { open = false, onChoose = null, onclose = null, taskSurface = false } = $props();
  let pickerQuery = $state('');
  let isMaterial = $state(false); // freeform: unchecked → Fee, checked → Material

  // Start fresh on every open: a cancelled add (or any other close) must not
  // leave stale typing or a stale material toggle behind when reopened.
  $effect(() => {
    if (open) { pickerQuery = ''; isMaterial = false; }
  });

  const search = async (q) => {
    const enc = encodeURIComponent(q);
    const [svc, inv] = await Promise.all([
      api.get(`/api/service-items/?search=${enc}&page_size=${PICKER_PAGE_SIZE}`),
      api.get(`/api/inventory/?is_active=true&is_catalog=true&search=${enc}&page_size=${PICKER_PAGE_SIZE}`),
    ]);
    const svcRows = svc.results || svc;
    const invRows = inv.results || inv;
    const rows = [
      ...svcRows.map((s) => ({ kind: 'service', id: s.template_id, label: s.template_name,
        sub: s.description || '', price: s.rate_scheme_detail?.rate, unit: s.rate_scheme_detail?.unit_label, item: s })),
      ...invRows.map((m) => ({ kind: 'inventory', id: m.inventory_item_id, label: m.code,
        sub: m.description || '', price: m.selling_price, unit: m.units, item: m })),
    ];
    return { rows, total: (svc.count ?? svcRows.length) + (inv.count ?? invRows.length) };
  };

  const rowLabel = (r) => r.label;
  const resolveLabel = () => Promise.resolve(null);

  function emitRow(r) {
    if (r.kind === 'service') onChoose?.({ type: 'service', serviceItem: r.item });
    else onChoose?.({ type: 'inventory', inventoryItem: r.item });
  }
  function emitFreeform() {
    // Estimate footer: the "is material?" checkbox decides material vs fee.
    onChoose?.({ type: 'freeform', typed: pickerQuery, isMaterial });
  }
  // Task-list footer: explicit per-atom emits.
  function emitFreeformMaterial() {
    onChoose?.({ type: 'freeform', typed: pickerQuery, isMaterial: true });
  }
  function emitFreeformFee() {
    onChoose?.({ type: 'freeform', typed: pickerQuery, isMaterial: false });
  }
  function emitFreeformTask() {
    // A manual/freeform Task — rate scheme picked in the follow-up WorkItemForm.
    // Estimates never offer this (tasks come from a ServiceItem pick there).
    onChoose?.({ type: 'freeform-task', typed: pickerQuery });
  }
</script>

<Modal {open} onCancel={onclose} label="Add line">
  <div class="plp-header">
    <strong>Add line</strong>
    <button type="button" onclick={onclose}>Close</button>
  </div>

  <div class="plp-body">
        <SearchPicker
          bind:query={pickerQuery}
          {search} {resolveLabel} {rowLabel}
          onPick={emitRow}
          placeholder="Search services or materials…"
        >
          {#snippet row(r)}
            <span class="plp-row">
              <span class="plp-row-label">{r.label}</span>
              <span class="plp-row-sub">{r.sub}</span>
              {#if r.price != null}<span class="plp-row-price">${Number(r.price).toFixed(2)}</span>{/if}
              {#if r.unit}<span class="plp-row-unit">/ {r.unit}</span>{/if}
            </span>
          {/snippet}
        </SearchPicker>
      </div>

  <div class="plp-freeform">
    {#if taskSurface}
      <button type="button" onclick={emitFreeformTask}>Add Task</button>
      <button type="button" onclick={emitFreeformMaterial}>Add Material</button>
      <button type="button" onclick={emitFreeformFee}>Add Fee</button>
    {:else}
      <label><input type="checkbox" bind:checked={isMaterial}> Is this a material?</label>
      <button type="button" onclick={emitFreeform}>Add Line</button>
    {/if}
  </div>
</Modal>

<style>
  /* Lives on the shared <Modal> shell (position/size/drag come from there);
     the header/footer dividers bleed to the box edges past the shell's 16px
     padding. The results list is an absolutely-positioned dropdown (.plp-body
     is relative), so it never shifts the modal as results load. */
  .plp-header {
    display: flex; align-items: center; justify-content: space-between;
    margin: 0 -16px; padding: 0 16px 10px; border-bottom: 1px solid #eee;
  }
  /* padding-bottom leaves room for a one-row dropdown ("No matches…") so the
     freeform footer below stays visible while it's showing. */
  .plp-body { padding: 12px 0 56px; position: relative; }
  /* Widen the search box to ~2x a default text input. Scoped under .plp-body so
     other SearchPicker instances elsewhere are unaffected. */
  .plp-body :global(input[type="text"]) { width: 40ch; max-width: 100%; }
  .plp-freeform { margin: 0 -16px -16px; padding: 10px 16px 16px; border-top: 1px solid #eee; }

  /* Row layout inside SearchPicker's dropdown button (which is display:block,
     so the row needs its own flex container for the columns to align) */
  .plp-row { display: flex; gap: 12px; align-items: baseline; width: 100%; }
  .plp-row-label { flex: 0 0 12rem; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .plp-row-sub {
    flex: 1 1 auto; min-width: 0; color: #666; font-size: 12px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .plp-row-price { margin-left: auto; font-size: 12px; color: #444; white-space: nowrap; }
  .plp-row-unit { font-size: 12px; color: #777; white-space: nowrap; }
</style>
