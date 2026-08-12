<script>
  // The change order's "amended agreement" edit surface (CO amend-in-place,
  // Task 8): one table showing the agreement as it will read if this CO is
  // accepted — server-composed by compose_amended_agreement (Tasks 5-7) so
  // the view, footer totals, and future seeding can never disagree.
  // Presentation + gestures only — ChangeOrderPanel owns loading (co,
  // amended, sourcePool) and refreshes both after `onChanged()`, same
  // silent-refresh contract as EstimateEditView.
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import { formatQtyUnits } from '../../lib/format.js';
  import { fmtMoney } from '../../lib/taskTotals.js';
  import COLineItemModal from './COLineItemModal.svelte';
  import COAddLineForm from './COAddLineForm.svelte';
  import PriceListPicker from '../PriceListPicker.svelte';
  import LinkifiedText from '../LinkifiedText.svelte';
  import BackingChip from '../docsurface/BackingChip.svelte';
  import AtomChildRow from '../docsurface/AtomChildRow.svelte';
  import UncoveredWorkSection from '../docsurface/UncoveredWorkSection.svelte';
  import NewLineFromSelectedRow from '../docsurface/NewLineFromSelectedRow.svelte';
  import QtyUnits from '../docsurface/QtyUnits.svelte';

  // Atom rows carry description/qty/price/amount (4, no leading # column in
  // this table — amended-agreement rows carry no stable line_number) + this
  // many blank cells before the onRemove cell, so Remove lands under
  // Actions, not Backing (which always sits between Amount and Actions).
  const ATOM_ROW_COLSPAN_AFTER = 1;

  let {
    co,
    canEdit,
    onChanged = () => {},
    amended = null,
    sourcePool = null,
    categories = [],
  } = $props();

  const apiBase = $derived(`/api/change-orders/${co.change_order_id}`);
  let rows = $derived(amended?.rows || []);

  function rowKey(row, i) {
    if (row.kind === 'agreement') return `a-${row.line.estimate_line_id ?? `i${i}`}`;
    if (row.kind === 'removed') return `r-${row.co_line_id}`;
    if (row.kind === 'replaced') return `p-${row.co_line_id}`;
    return `d-${row.co_line_id}`; // 'added'
  }

  function fmtTotal(n) { return `$${Number(n ?? 0).toFixed(2)}`; }
  function fmtDelta(n) {
    const v = Number(n ?? 0);
    if (v === 0) return fmtTotal(0);
    return (v > 0 ? '+' : '-') + `$${Math.abs(v).toFixed(2)}`;
  }

  // ── Add line (unchanged flow: PriceListPicker → COAddLineForm) ───────────
  let pickerOpen = $state(false);
  let addChoice = $state(null);

  function handleLineAdded() {
    addChoice = null;
    onChanged();
  }

  // ── COLineItemModal orchestration — gestures preset everything ──────────
  let modalOpen = $state(false);
  let modalVariant = $state('edit-fields');
  let modalLineItemId = $state(null);
  let modalTargetLineItem = $state(null);
  let modalNeedsAC = $state(false);
  let modalInitialDescription = $state('');
  let modalInitialQty = $state('');
  let modalInitialUnits = $state('none');
  let modalInitialPrice = $state('');
  let modalInitialPercent = $state('');
  let modalInitialAC = $state('');

  function handleModalSaved() {
    modalOpen = false;
    onChanged();
  }

  /** 'agreement' row → [Replace…]: adjustment lines open the percent variant,
      everything else opens replace-prefill seeded from the current line. */
  function openReplace(row) {
    const line = row.line;
    modalLineItemId = null;
    modalTargetLineItem = line.estimate_line_id;
    modalInitialDescription = line.description || '';
    modalNeedsAC = false;
    if (line.is_adjustment) {
      modalVariant = 'adjustment';
      modalInitialPercent = line.percent ?? '';
    } else {
      modalVariant = 'replace-prefill';
      modalInitialQty = line.qty ?? '';
      modalInitialUnits = line.units || 'none';
      modalInitialPrice = line.price ?? '';
    }
    modalOpen = true;
  }

  /** 'replaced' row → [Edit]: PATCH the existing CO replace line. */
  function openEditReplaced(row) {
    const line = row.line;
    modalLineItemId = row.co_line_id;
    modalTargetLineItem = null;
    modalInitialDescription = line.description || '';
    modalNeedsAC = false;
    if (line.is_adjustment) {
      modalVariant = 'adjustment';
      modalInitialPercent = line.percent ?? '';
    } else {
      modalVariant = 'edit-fields';
      modalInitialQty = line.qty ?? '';
      modalInitialUnits = line.units || 'none';
      modalInitialPrice = line.price ?? '';
    }
    modalOpen = true;
  }

  /** 'added' row → [Edit]: PATCH the existing CO add line (needs an AC). */
  function openEditAdded(row) {
    const line = row.line;
    modalLineItemId = row.co_line_id;
    modalTargetLineItem = null;
    modalVariant = 'edit-fields';
    modalInitialDescription = line.description || '';
    modalInitialQty = line.qty ?? '';
    modalInitialUnits = line.units || 'none';
    modalInitialPrice = line.price ?? '';
    modalInitialAC = line.accounting_category_id ?? '';
    modalNeedsAC = true;
    modalOpen = true;
  }

  // ── Remove via CO / Undo / Remove (never "delete" in user-facing text) ──
  // Single-phase, no confirm() — every gesture here is undoable (re-add via
  // Undo, or re-select the atoms again).
  async function removeViaCO(row) {
    try {
      await api.post(`${apiBase}/line-items/`, {
        action: 'remove', target_line_item: row.line.estimate_line_id,
      });
      onChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not remove line via change order.'));
    }
  }

  async function deleteCOLine(coLineId, fallback) {
    try {
      await api.delete(`${apiBase}/line-items/${coLineId}/`);
      onChanged();
    } catch (e) {
      showError(errorMessage(e, fallback));
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

  // A claimed_by_other atom is claimed on one of two lenses (Task 7): another
  // CO's add line or an estimate — CO wins the branch since it's the more
  // specific claim (mirrors EstimateEditView's unselectableNote).
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
      // Atoms claimed by this CO's own agreement display nested under their
      // agreement line above (RM 2026-08-10) — not as disabled pool noise.
      // Claims by a different estimate or another CO stay visible: those are
      // real conflicts the user can't see anywhere else on this page.
      .filter((a) => !(a.state === 'claimed_by_other'
                       && a.claiming_estimate_id === co.estimate))
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

  // A claim conflict (another line/estimate/CO grabbed an atom between the
  // pool load and this POST) can't be resolved by retrying blind — refresh
  // so the pool/rows reflect reality, and say so, instead of the generic
  // overlay (mirrors EstimateEditView's handleMutationError).
  async function handleMutationError(e, fallback) {
    if (e?.status === 409) {
      selected = [];
      await onChanged();
      showError(errorMessage(e, 'Some of those atoms were claimed elsewhere in the meantime — refreshed.'));
    } else {
      showError(errorMessage(e, fallback));
    }
  }

  async function addSelectedToLine(row) {
    try {
      await api.post(`${apiBase}/line-items/${row.co_line_id}/add-atoms/`, {
        atoms: parseSelected(selected),
      });
      selected = [];
      onChanged();
    } catch (e) {
      await handleMutationError(e, 'Could not add the selected atoms to this line.');
    }
  }

  // Waits for the parent's (silent) refresh so `co.line_items` reflects the
  // server's authoritative copy of the just-created line, then opens the
  // edit modal against it — falling back to the raw POST response if the
  // refreshed list doesn't contain it for some reason (mirrors
  // EstimateEditView's openModalForCreatedLine).
  async function openModalForCreatedLine(newLine) {
    await onChanged();
    const li = (co.line_items || []).find((x) => x.line_item_id === newLine.line_item_id) || newLine;
    modalLineItemId = li.line_item_id;
    modalTargetLineItem = null;
    modalVariant = 'edit-fields';
    modalInitialDescription = li.description || '';
    modalInitialQty = li.qty ?? '';
    modalInitialUnits = li.units || 'none';
    modalInitialPrice = li.price ?? '';
    modalInitialAC = li.accounting_category ?? '';
    modalNeedsAC = true;
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

  async function removeAtomFromLine(coLineId, source) {
    try {
      await api.post(`${apiBase}/line-items/${coLineId}/remove-atoms/`, {
        source_ids: [source.source_id],
      });
      onChanged();
    } catch (e) {
      await handleMutationError(e, 'Could not remove this atom from the line.');
    }
  }

  function atomFromSource(source) {
    return {
      kind: source.source_type,
      description: source.description ?? '(removed)',
      qty_display: formatQtyUnits(source.qty, source.units),
      rate: source.rate,
      amount: source.computed_amount,
    };
  }

</script>

<h3>Line items</h3>

{#if canEdit}
  <p>
    <button type="button" onclick={() => { pickerOpen = true; }}>Add line</button>
  </p>
{/if}

<table class="data-table doc-edit-table co-edit-table">
  <thead>
    <tr>
      <th>Description</th>
      <th class="text-right">Qty</th>
      <th class="text-right">Price</th>
      <th class="text-right">Amount</th>
      <th>Backing</th>
      {#if canEdit}<th>Actions</th>{/if}
    </tr>
  </thead>
  <tbody>
    {#each rows as row, i (rowKey(row, i))}
      {#if row.kind === 'agreement'}
        <tr>
          <td class="preserve-breaks">
            <LinkifiedText text={row.line.description || 'No description'} />
          </td>
          <td class="text-right"><QtyUnits qty={row.line.qty} units={row.line.units} /></td>
          <td class="text-right">{fmtMoney(row.line.price)}</td>
          <td class="text-right">{fmtMoney(row.line.amount)}</td>
          <td>
            <BackingChip backing={row.backing} />
            {#if row.backing === 'edited' && row.backing_total != null}
              <br><small>work totals {fmtMoney(row.backing_total)}</small>
            {/if}
          </td>
          {#if canEdit}
            <td>
              {#if row.line.estimate_line_id != null}
                <button type="button" disabled={!!row.billed_on}
                  title={row.billed_on ? `Billed on ${row.billed_on}` : undefined}
                  onclick={() => removeViaCO(row)}>Remove via CO</button>
                <button type="button" disabled={!!row.billed_on}
                  title={row.billed_on ? `Billed on ${row.billed_on}` : undefined}
                  onclick={() => openReplace(row)}>Replace&hellip;</button>
                {#if row.billed_on}<br><small>billed on {row.billed_on}</small>{/if}
                {#if row.adjustment_expected_amount != null}
                  <br><small class="muted">recomputes to {fmtMoney(row.adjustment_expected_amount)} if replaced</small>
                {/if}
              {/if}
            </td>
          {/if}
        </tr>
        {#each row.sources || [] as source (source.source_id)}
          <AtomChildRow
            atom={atomFromSource(source)}
            colspanBefore={0}
            colspanAfter={ATOM_ROW_COLSPAN_AFTER}
            onRemove={null}
          />
        {/each}
      {:else if row.kind === 'removed'}
        <tr class="co-struck-original">
          <td class="preserve-breaks struck">{row.original.description}</td>
          <td class="text-right struck"><QtyUnits qty={row.original.qty} units={row.original.units} /></td>
          <td class="text-right struck">{fmtMoney(row.original.price)}</td>
          <td class="text-right struck">({fmtMoney(row.original.amount)})</td>
          <td></td>
          {#if canEdit}
            <td><button type="button" onclick={() => deleteCOLine(row.co_line_id, 'Could not undo removal.')}>Undo</button></td>
          {/if}
        </tr>
      {:else if row.kind === 'replaced'}
        <tr class="co-authored">
          <td class="preserve-breaks">
            <span class="co-badge">CO {row.co_index}</span>
            <span class="co-desc"><LinkifiedText text={row.line.description || 'No description'} /></span>
          </td>
          <td class="text-right"><QtyUnits qty={row.line.qty} units={row.line.units} /></td>
          <td class="text-right">{fmtMoney(row.line.price)}</td>
          <td class="text-right">{fmtMoney(row.line.amount)}</td>
          <td>
            <BackingChip backing={row.backing} />
            {#if row.backing === 'edited' && row.backing_total != null}
              <br><small>work totals {fmtMoney(row.backing_total)}</small>
            {/if}
          </td>
          {#if canEdit}
            <td>
              <button type="button" onclick={() => openEditReplaced(row)}>Edit</button>
              <button type="button" onclick={() => deleteCOLine(row.co_line_id, 'Could not undo this change.')}>Undo</button>
            </td>
          {/if}
        </tr>
        <tr class="co-struck-original">
          <td class="preserve-breaks struck">{row.original.description}</td>
          <td class="text-right struck"><QtyUnits qty={row.original.qty} units={row.original.units} /></td>
          <td class="text-right struck">{fmtMoney(row.original.price)}</td>
          <td class="text-right struck">({fmtMoney(row.original.amount)})</td>
          <td></td>
          {#if canEdit}<td></td>{/if}
        </tr>
        {#each row.sources || [] as source (source.source_id)}
          <AtomChildRow
            atom={atomFromSource(source)}
            colspanBefore={0}
            colspanAfter={ATOM_ROW_COLSPAN_AFTER}
            note={`inherited from line ${source.inherited_from_line}`}
            onRemove={null}
          />
        {/each}
      {:else}
        <!-- 'added' -->
        <tr class="co-authored">
          <td class="preserve-breaks">
            <span class="co-badge">CO {row.co_index}</span>
            <span class="co-desc"><LinkifiedText text={row.line.description || 'No description'} /></span>
          </td>
          <td class="text-right"><QtyUnits qty={row.line.qty} units={row.line.units} /></td>
          <td class="text-right">{fmtMoney(row.line.price)}</td>
          <td class="text-right">{fmtMoney(row.line.amount)}</td>
          <td>
            <BackingChip backing={row.backing} />
            {#if row.backing === 'edited' && row.backing_total != null}
              <br><small>work totals {fmtMoney(row.backing_total)}</small>
            {/if}
          </td>
          {#if canEdit}
            <td>
              <button type="button" onclick={() => openEditAdded(row)}>Edit</button>
              <button type="button" onclick={() => deleteCOLine(row.co_line_id, 'Could not remove line item.')}>Remove</button>
              {#if selected.length > 0}
                <button type="button" onclick={() => addSelectedToLine(row)}>Add selected here</button>
              {/if}
            </td>
          {/if}
        </tr>
        {#each row.sources || [] as source (source.source_id)}
          <AtomChildRow
            atom={atomFromSource(source)}
            colspanBefore={0}
            colspanAfter={ATOM_ROW_COLSPAN_AFTER}
            onRemove={canEdit ? () => removeAtomFromLine(row.co_line_id, source) : null}
          />
        {/each}
      {/if}
    {/each}
    {#if canEdit}
      <NewLineFromSelectedRow
        visible={selected.length > 0}
        onCreate={createLineFromSelected}
      />
    {/if}
  </tbody>
  <tfoot>
    <tr>
      <td colspan="3" class="text-right">Original</td>
      <td class="text-right">{fmtTotal(amended?.original_total)}</td>
      <td colspan={canEdit ? 2 : 1}></td>
    </tr>
    <tr>
      <td colspan="3" class="text-right">This change order</td>
      <td class="text-right">{fmtDelta(amended?.co_delta)}</td>
      <td colspan={canEdit ? 2 : 1}></td>
    </tr>
    <tr>
      <td colspan="3" class="text-right"><strong>Revised total</strong></td>
      <td class="text-right"><strong>{fmtTotal(amended?.revised_total)}</strong></td>
      <td colspan={canEdit ? 2 : 1}></td>
    </tr>
  </tfoot>
</table>

{#if canEdit}
  <UncoveredWorkSection
    title="Uncovered work"
    subtitle="Tasks and materials from this job not covered by the agreement."
    rows={uncoveredRows}
    bind:selected
    directLabel="Add as its own line"
    onDirect={billDirect}
    emptyText="No uncovered tasks or materials."
  />
{/if}

<PriceListPicker open={pickerOpen} onChoose={(c) => { pickerOpen = false; addChoice = c; }} onclose={() => { pickerOpen = false; }} />

<COAddLineForm
  open={addChoice != null}
  choice={addChoice}
  coId={co.change_order_id}
  {categories}
  onSaved={handleLineAdded}
  onClose={() => { addChoice = null; }}
/>

<COLineItemModal
  open={modalOpen}
  variant={modalVariant}
  coId={co.change_order_id}
  lineItemId={modalLineItemId}
  targetLineItem={modalTargetLineItem}
  needsAccountingCategory={modalNeedsAC}
  initialDescription={modalInitialDescription}
  initialQty={modalInitialQty}
  initialUnits={modalInitialUnits}
  initialPrice={modalInitialPrice}
  initialPercent={modalInitialPercent}
  initialAccountingCategory={modalInitialAC}
  {categories}
  onSaved={handleModalSaved}
  onClose={() => { modalOpen = false; }}
/>

<style>
  table { border-collapse: collapse; }
  th, td { padding: 6px 10px; }

  /* CO-authored (replace/add) rows get a light teal tint consistent with the
     app's teal accent (data-table header band, backing chips). */
  tr.co-authored { background: #f0fdfa; }
  .co-badge {
    display: inline-block; font-size: 11px; font-weight: 600; color: #0f766e;
    background: #ccfbf1; border-radius: 3px; padding: 1px 5px; margin-right: 6px;
  }

  /* Struck original/removed rows — excluded from totals, shown for context. */
  tr.co-struck-original td.struck { color: #9ca3af; text-decoration: line-through; }

  .muted { color: #6b7280; }

  tfoot td { padding: 8px 10px; border-top: 2px solid #e5e7eb; }
</style>
