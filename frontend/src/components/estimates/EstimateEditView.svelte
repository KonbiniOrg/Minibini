<script>
  // The estimate document's "Edit" mode — merges the old lines table and the
  // reconcile wizard into one surface: a `.data-table` of the estimate's
  // line items (each with its atom nest and BackingChip) alongside an
  // "uncovered work" pool of not-yet-billed job atoms. Presentation +
  // gestures only — EstimatePanel owns data loading (estimate, sourcePool)
  // and refreshes both after `onChanged()`.
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import { formatQtyUnits } from '../../lib/format.js';
  import { fmtMoney } from '../../lib/taskTotals.js';
  import AdjustmentModal from '../AdjustmentModal.svelte';
  import LineItemModal from '../LineItemModal.svelte';
  import PriceListPicker from '../PriceListPicker.svelte';
  import LinkifiedText from '../LinkifiedText.svelte';
  import EstimateAddLineForm from './EstimateAddLineForm.svelte';
  import BackingChip from '../docsurface/BackingChip.svelte';
  import AtomChildRow from '../docsurface/AtomChildRow.svelte';
  import UncoveredWorkSection from '../docsurface/UncoveredWorkSection.svelte';
  import NewLineFromSelectedRow from '../docsurface/NewLineFromSelectedRow.svelte';
  import QtyUnits from '../docsurface/QtyUnits.svelte';

  // Atom rows carry # (colspanBefore=1) + description/qty/rate/amount (4) +
  // this many blank cells before the onRemove cell — one for the Backing
  // column that always sits between Amount and Actions in the main table,
  // so Remove lands under Actions, not Backing.
  const ATOM_ROW_COLSPAN_AFTER = 1;

  let {
    estimate,
    canEdit,
    onChanged = () => {},
    sourcePool = null,
    lineItems = [],
    categories = [],
    defaultMaterialCategoryId = null,
    // Dark until the §6 "make deliverable" endpoint lands — a caller wires
    // this to render the per-line "→ Deliverable" action; EstimatePanel
    // doesn't wire it yet, so the button stays unrendered.
    onMakeDeliverable = null,
  } = $props();

  const apiBase = $derived(`/api/estimates/${estimate.estimate_id}`);

  // ── Add line / Add adjustment (unchanged flows) ──────────────────────────
  let pickerOpen = $state(false);
  let addChoice = $state(null);
  let adjustmentModalOpen = $state(false);

  function handleChoose(choice) {
    pickerOpen = false;
    addChoice = choice;
  }
  function handleLineAdded() {
    addChoice = null;
    onChanged();
  }

  // ── Edit modal (field-edit mode), reused for both "Edit" and the
  // post-create landing after a new line is built from selected atoms. ────
  let modalOpen = $state(false);
  let modalItem = $state(null);

  function openEditItem(li) {
    modalItem = li;
    modalOpen = true;
  }
  function handleModalSaved() {
    modalOpen = false;
    modalItem = null;
    onChanged();
  }

  // ── Remove (never "delete" in user-facing text) ──────────────────────────
  // Single-phase: the estimate line-item DELETE has no two-phase confirm
  // gate (drafts-only, freely re-addable via the uncovered-work pool).
  async function handleRemoveItem(li) {
    try {
      await api.delete(`${apiBase}/line-items/${li.line_item_id}/`);
      onChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not remove line item.'));
    }
  }

  // ── Uncovered work pool → selection → add-atoms / line-items-from-atoms ──
  let selected = $state([]); // array of "type:id" row ids

  function atomRowId(atom) {
    return `${atom.type}:${atom.id}`;
  }
  function parseSelected(ids) {
    return ids.map((id) => {
      const sep = id.indexOf(':');
      return { type: id.slice(0, sep), id: Number(id.slice(sep + 1)) };
    });
  }

  // A claimed_by_other atom is claimed on one of two lenses (Task 7): a CO
  // add line (claiming_change_order_number set) or another estimate
  // (claiming_estimate_number set) — never both. CO wins the branch since
  // it's the more specific claim; falls back to the estimate note.
  function unselectableNote(atom) {
    if (atom.state !== 'claimed_by_other') return undefined;
    if (atom.claiming_change_order_number) {
      return `Claimed by change order ${atom.claiming_change_order_number}`;
    }
    return `Claimed by estimate ${atom.claiming_estimate_number || ''}`.trim();
  }

  let uncoveredRows = $derived(
    (sourcePool?.atoms || [])
      .filter((a) => a.state !== 'claimed_by_current')
      .map((a) => ({
        id: atomRowId(a),
        kind: a.type,
        description: a.description,
        qty_display: formatQtyUnits(a.qty, a.units),
        rate: a.rate,
        amount: a.amount,
        selectable: a.state === 'available',
        unselectableNote: unselectableNote(a),
      }))
  );

  // A claim conflict (another line/estimate grabbed an atom between the pool
  // load and this POST) can't be resolved by retrying blind — refresh so the
  // pool/lines reflect reality, and say so, instead of the generic overlay.
  async function handleMutationError(e, fallback) {
    if (e?.status === 409) {
      selected = [];
      await onChanged();
      showError(errorMessage(e, 'Some of those atoms were claimed elsewhere in the meantime — refreshed.'));
    } else {
      showError(errorMessage(e, fallback));
    }
  }

  async function addSelectedToLine(li) {
    try {
      await api.post(`${apiBase}/line-items/${li.line_item_id}/add-atoms/`, {
        atoms: parseSelected(selected),
      });
      selected = [];
      onChanged();
    } catch (e) {
      await handleMutationError(e, 'Could not add the selected atoms to this line.');
    }
  }

  // Waits for the parent's (silent) refresh so `lineItems` reflects the
  // server's authoritative copy of the just-created line, then opens the
  // edit modal against THAT object — falling back to the raw POST response
  // if the refreshed list doesn't contain it for some reason. Opening the
  // modal only after the refresh resolves (never before) is what keeps this
  // reliable now that EstimatePanel's refresh no longer unmounts this view.
  async function openModalForCreatedLine(newLine) {
    await onChanged();
    modalItem = lineItems.find((li) => li.line_item_id === newLine.line_item_id) || newLine;
    modalOpen = true;
  }

  async function createLineFromSelected() {
    try {
      const newLine = await api.post(`${apiBase}/line-items-from-atoms/`, {
        atoms: parseSelected(selected),
      });
      selected = [];
      await openModalForCreatedLine(newLine);
    } catch (e) {
      await handleMutationError(e, 'Could not create a line from the selected atoms.');
    }
  }

  async function billDirect(rowId) {
    try {
      const newLine = await api.post(`${apiBase}/line-items-from-atoms/`, {
        atoms: parseSelected([rowId]),
      });
      await openModalForCreatedLine(newLine);
    } catch (e) {
      await handleMutationError(e, 'Could not create a line from this atom.');
    }
  }

  async function removeAtomFromLine(li, source) {
    try {
      await api.post(`${apiBase}/line-items/${li.line_item_id}/remove-atoms/`, {
        source_ids: [source.source_id],
      });
      onChanged();
    } catch (e) {
      await handleMutationError(e, 'Could not remove this atom from the line.');
    }
  }

  function lineAmount(li) {
    return Number(li.qty || 0) * Number(li.price || 0);
  }

  // Small provenance caption under the description — where a catalog or
  // adjustment line's price actually comes from. Sourced (planned_work /
  // planned_materials / edited) lines already carry their nested
  // AtomChildRows for that; hand lines have nothing to add. A bare
  // inventory_item ref with no nested detail has nothing displayable (just
  // a raw PK) — say nothing rather than show that.
  function provenanceText(li) {
    if (li.adjustment_service != null) {
      const detail = li.adjustment_service_detail;
      if (!detail) return '';
      const pct = Number(detail.rate);
      const sign = pct >= 0 ? '+' : '';
      return `${sign}${pct}% ${detail.name}`;
    }
    if (li.service_item_detail) return `Catalog: ${li.service_item_detail.name}`;
    return '';
  }
</script>

<h3>Line Items</h3>

{#if canEdit}
  <p>
    <button type="button" onclick={() => { pickerOpen = true; }}>Add line</button>
    <button type="button" onclick={() => { adjustmentModalOpen = true; }}>Add Adjustment</button>
  </p>
{/if}

<table class="data-table doc-edit-table line-items-table">
  <thead>
    <tr>
      <th>#</th>
      <th>Description</th>
      <th class="text-right">Qty</th>
      <th class="text-right">Price</th>
      <th class="text-right">Amount</th>
      <th>Backing</th>
      {#if canEdit || onMakeDeliverable}<th>Actions</th>{/if}
    </tr>
  </thead>
  <tbody>
    {#each lineItems as li (li.line_item_id)}
      <tr>
        <td>{li.line_number}</td>
        <td class="preserve-breaks">
          <LinkifiedText text={li.description || 'No description'} />
          {#if canEdit && li.accounting_category == null}
            <br><small class="needs-category">needs category</small>
          {/if}
          {#if provenanceText(li)}<br><small>{provenanceText(li)}</small>{/if}
        </td>
        <td class="text-right"><QtyUnits qty={li.qty} units={li.units} /></td>
        <td class="text-right">{fmtMoney(li.price)}</td>
        <td class="text-right">{fmtMoney(lineAmount(li))}</td>
        <td>
          <BackingChip backing={li.backing} />
          {#if li.backing === 'edited' && li.backing_total != null}
            <br><small>work totals {fmtMoney(li.backing_total)}</small>
          {/if}
        </td>
        {#if canEdit || onMakeDeliverable}
          <td>
            {#if canEdit}
              <button type="button" onclick={() => openEditItem(li)}>Edit</button>
              <button type="button" onclick={() => handleRemoveItem(li)}>Remove</button>
              {#if selected.length > 0}
                <button type="button" onclick={() => addSelectedToLine(li)}>Add selected here</button>
              {/if}
            {/if}
            {#if onMakeDeliverable}
              <button type="button" onclick={() => onMakeDeliverable(li)}>&rarr; Deliverable</button>
            {/if}
          </td>
        {/if}
      </tr>
      {#each li.sources || [] as source (source.source_id)}
        <AtomChildRow
          atom={{
            kind: source.source_type,
            description: source.description ?? '(removed)',
            qty_display: formatQtyUnits(source.qty, source.units),
            rate: source.rate,
            amount: source.computed_amount,
          }}
          colspanBefore={1}
          colspanAfter={ATOM_ROW_COLSPAN_AFTER}
          onRemove={canEdit ? () => removeAtomFromLine(li, source) : null}
        />
      {/each}
    {/each}
    {#if canEdit}
      <NewLineFromSelectedRow
        visible={selected.length > 0}
        onCreate={createLineFromSelected}
      />
    {/if}
  </tbody>
</table>

{#if canEdit}
  <UncoveredWorkSection
    title="Uncovered work"
    subtitle="Tasks and materials from this job not yet on this estimate."
    rows={uncoveredRows}
    bind:selected
    directLabel="Add as its own line"
    onDirect={billDirect}
    emptyText="No uncovered tasks or materials."
  />
{/if}

<PriceListPicker open={pickerOpen} onChoose={handleChoose} onclose={() => { pickerOpen = false; }} />

<EstimateAddLineForm
  open={addChoice != null}
  choice={addChoice}
  estimateId={estimate.estimate_id}
  {categories}
  {defaultMaterialCategoryId}
  onSaved={handleLineAdded}
  onClose={() => { addChoice = null; }}
/>

<LineItemModal
  open={modalOpen}
  mode="edit"
  apiBase={apiBase}
  item={modalItem}
  {categories}
  showMaterialMarker={true}
  {defaultMaterialCategoryId}
  onSaved={handleModalSaved}
  onClose={() => { modalOpen = false; }}
/>

<AdjustmentModal
  open={adjustmentModalOpen}
  apiBase={apiBase}
  {categories}
  onSaved={() => { adjustmentModalOpen = false; onChanged(); }}
  onClose={() => { adjustmentModalOpen = false; }}
/>

<style>
  table { border-collapse: collapse; }
  th, td { padding: 6px 10px; }
  /* Matches the old LineItemTable's needs-category marker (send is blocked
     without an accounting_category — the estimator must see this before the
     send-time error). */
  .needs-category { background-color: #fff8e1; color: #b45309; font-style: italic; }
</style>
