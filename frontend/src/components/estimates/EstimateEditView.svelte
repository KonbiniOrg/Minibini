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
  import Modal from '../Modal.svelte';
  import LineItemModal from '../LineItemModal.svelte';
  import PriceListPicker from '../PriceListPicker.svelte';
  import WorkItemForm from '../WorkItemForm.svelte';
  import LinkifiedText from '../LinkifiedText.svelte';
  import EstimateAddLineForm from './EstimateAddLineForm.svelte';
  import BackingChip from '../docsurface/BackingChip.svelte';
  import AtomChildRow from '../docsurface/AtomChildRow.svelte';
  import AtomCaptionRow from '../docsurface/AtomCaptionRow.svelte';
  import UncoveredWorkSection from '../docsurface/UncoveredWorkSection.svelte';
  import NewLineFromSelectedRow from '../docsurface/NewLineFromSelectedRow.svelte';
  import BundleModal from '../docsurface/BundleModal.svelte';
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
    // The Make Deliverable button (better-fees §6): EstimatePanel wires
    // this to POST line-items/{id}/make-deliverable/. Suppressed per line
    // once a linked deliverable exists (linked_deliverables from the
    // serializer — the source_line provenance FK).
    onMakeDeliverable = null,
    // Fired when a gesture here changes the JOB's deliverables (the remove
    // dialog's "remove both") — the panel chains it to onJobChange so the
    // context band's Deliverables panel refreshes.
    onDeliverablesChanged = () => {},
    // claims-by-construction (estimating-structure Task 7): whether THIS
    // caller may mint work off an unanswered line or mark it "no work
    // needed" — EstimatePanel computes this the same way it computes
    // canEdit (canManageJobs && a status check), trusted here exactly like
    // canEdit is (no redundant estimate.status re-check for the buttons
    // themselves).
    canMint = false,
    // Mint/decline can be the LAST unanswered line, which auto-releases the
    // job (approved -> in_progress) server-side. onChanged only refreshes
    // this doc + the source pool (silent) — this fires in addition so the
    // panel's onJobChange chain (already wired for status-pill / deliverable
    // refreshes) picks up the job's possibly-changed status live.
    onWorkDecisionChanged = () => {},
    // The job's status (EstimatePanel passes job?.status) — drives the
    // checklist banner's copy only: once the job is already in_progress
    // (e.g. timeslip-start released it out from under an unfinished
    // checklist), the banner must not promise a release that already
    // happened.
    jobStatus = null,
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
  function handleModalSaved(result) {
    modalOpen = false;
    modalItem = null;
    onChanged();
    // The edit dialog updated the linked deliverable — refresh the job so
    // the context band's Deliverables panel shows the new values.
    if (result?.deliverablesUpdated) onDeliverablesChanged();
  }

  // ── Remove (never "delete" in user-facing text) ──────────────────────────
  // Single-phase for ordinary lines (drafts-only, freely re-addable via the
  // uncovered-work pool). A line with a deliverable made from it first asks
  // whether the deliverable goes too (RM 2026-08-12) — deleting a persisted
  // deliverable is the irreversible half, so that choice gets a dialog.
  let removeDialogLine = $state(null);

  function handleRemoveItem(li) {
    if ((li.linked_deliverables || []).length > 0) {
      removeDialogLine = li;
      return;
    }
    removeLine(li, { deleteDeliverables: false });
  }

  async function removeLine(li, { deleteDeliverables }) {
    removeDialogLine = null;
    const suffix = deleteDeliverables ? '?delete_deliverables=true' : '';
    try {
      await api.delete(`${apiBase}/line-items/${li.line_item_id}/${suffix}`);
      onChanged();
      if (deleteDeliverables) onDeliverablesChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not remove line item.'));
    }
  }

  // Qty/units drift between a line and its linked deliverable — passive
  // mismatch caption only, never a sync (spec §6).
  function deliverableMismatch(li) {
    const d = (li.linked_deliverables || [])[0];
    if (!d) return null;
    const drifted = Number(d.qty_ordered) !== Number(li.qty)
      || (d.units || 'none') !== (li.units || 'none');
    return drifted ? d : null;
  }

  // ── Uncovered work pool → selection → line-items-from-atoms (bundle
  // modal) ── "Add selected here" (attach onto an existing line) is
  // retired: composing selected atoms only ever creates a NEW line via the
  // bundle modal below, never an in-table attach onto an existing one.
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

  // Bundle modal (Task 8): the dashed row's action opens BundleModal seeded
  // with the selected atoms' raw pool data (sourcePool.atoms carries the
  // qty/units/rate/amount BundleModal needs — uncoveredRows only has the
  // formatted qty_display used for the picklist). The single-atom case
  // still opens the modal (consistent gesture; the seed is just that
  // atom's values) rather than the old direct-POST-then-edit-modal flow.
  let bundleModalOpen = $state(false);
  let bundleAtoms = $derived(
    (sourcePool?.atoms || []).filter((a) => selected.includes(atomRowId(a)))
  );

  function openBundleModal() {
    bundleModalOpen = true;
  }
  function handleBundleCreated() {
    bundleModalOpen = false;
    selected = [];
    onChanged();
  }
  async function handleBundleConflict(e) {
    bundleModalOpen = false;
    await handleMutationError(e, 'Could not create a line from the selected atoms.');
  }

  async function billDirect(rowId) {
    try {
      // Create the line and stop — no post-create edit modal (RM
      // 2026-08-16): the line is complete as projected; editing is the
      // user's decision via the row's own Edit button.
      await api.post(`${apiBase}/line-items-from-atoms/`, {
        atoms: parseSelected([rowId]),
      });
      await onChanged();
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

  // ── Mint / decline / checklist (claims-by-construction, estimating-
  // structure Task 7) ───────────────────────────────────────────────────
  // needs_work_decision is server-computed (EstimateLineItemSerializer,
  // mirroring EstimateService.unanswered_lines' chain-aware predicate) —
  // consumed directly, never re-derived here. Re-deriving it client-side
  // previously diverged from the backend after an accepted CO moved a
  // line's claims onto a replace line (final-review fix, docs/plans/
  // 2026-08-15-estimating-structure.md).
  let unansweredLines = $derived(lineItems.filter((li) => li.needs_work_decision));
  // Independent of canMint (a permission gate on the ACTION buttons) — the
  // banner is informational for anyone looking at an accepted estimate,
  // same as "needs category" is visible without regard to who can fix it.
  let showChecklistBanner = $derived(
    estimate?.status === 'accepted' && unansweredLines.length > 0
  );
  // Auto-release only fires while the job is still approved — once it's
  // already in_progress (e.g. timeslip-start released it out from under an
  // unfinished checklist), promising an automatic release is simply wrong.
  let checklistBannerText = $derived(
    jobStatus === 'in_progress'
      ? `${unansweredLines.length} line(s) still need a work decision.`
      : `${unansweredLines.length} line(s) need a work decision — the job starts automatically when all are answered.`
  );

  let mintModalOpen = $state(false);
  let mintModalLine = $state(null);

  function openMintModal(li) {
    mintModalLine = li;
    mintModalOpen = true;
  }
  function closeMintModal() {
    mintModalOpen = false;
    mintModalLine = null;
  }
  function handleMintSaved() {
    closeMintModal();
    onChanged();
    onWorkDecisionChanged();
  }

  // No confirm() on either direction — both are reversible (Undo flips it
  // right back), matching the UI convention that only irreversible actions
  // get a confirmation prompt.
  async function declineLine(li) {
    try {
      await api.patch(`${apiBase}/line-items/${li.line_item_id}/`, { work_declined: true });
      onChanged();
      onWorkDecisionChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not mark this line as no work needed.'));
    }
  }

  async function undeclineLine(li) {
    try {
      await api.patch(`${apiBase}/line-items/${li.line_item_id}/`, { work_declined: false });
      onChanged();
      onWorkDecisionChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not undo that.'));
    }
  }
</script>

<h3>Line Items</h3>

{#if canEdit}
  <p>
    <button type="button" onclick={() => { pickerOpen = true; }}>Add line</button>
    <button type="button" onclick={() => { adjustmentModalOpen = true; }}>Add Adjustment</button>
  </p>
{/if}

{#if showChecklistBanner}
  <div class="doc-warning">
    {checklistBannerText}
  </div>
{/if}

<table class="data-table doc-edit-table line-items-table">
  <thead>
    <tr>
      <th>#</th>
      <th>Description</th>
      <th class="text-right">Qty</th>
      <th class="text-right">Price</th>
      <th class="text-right">Amount</th>
      <th>Based on</th>
      {#if canEdit || onMakeDeliverable || canMint}<th>Actions</th>{/if}
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
          {#if deliverableMismatch(li)}
            <br><small class="deliv-mismatch">deliverable: {deliverableMismatch(li).qty_ordered} {deliverableMismatch(li).units}</small>
          {/if}
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
        {#if canEdit || onMakeDeliverable || canMint}
          <td>
            {#if canEdit}
              <button type="button" onclick={() => openEditItem(li)}>Edit</button>
              <button type="button" onclick={() => handleRemoveItem(li)}>Remove</button>
            {/if}
            {#if onMakeDeliverable && (li.linked_deliverables || []).length === 0}
              <button type="button" onclick={() => onMakeDeliverable(li)}>Make Deliverable</button>
            {/if}
            {#if canMint && li.needs_work_decision}
              <button type="button" onclick={() => openMintModal(li)}>Generate work…</button>
              <button type="button" onclick={() => declineLine(li)}>No work needed</button>
            {/if}
            {#if li.work_declined}
              <br><small>no work needed</small>
              {#if canMint}
                <button type="button" onclick={() => undeclineLine(li)}>Undo</button>
              {/if}
            {/if}
          </td>
        {/if}
      </tr>
      <AtomCaptionRow
        sources={li.sources || []}
        colspanBefore={1}
        colspan={5 + ((canEdit || onMakeDeliverable || canMint) ? 1 : 0)}
      />
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
        onCreate={openBundleModal}
        buttonLabel="Bundle into line…"
      />
    {/if}
  </tbody>
</table>

{#if canEdit}
  {#if uncoveredRows.length === 0}
    <!-- Empty pool: the whole section gives way to a plan-first pointer
         (RM 2026-08-16) — a heading over an empty table taught nothing. -->
    <p class="pool-empty-hint">
      To build an estimate based on tasks and materials, add them in the
      Tasks pane and they'll be listed below for line item reference.
    </p>
  {:else}
    <UncoveredWorkSection
      title="Unquoted work"
      subtitle="Tasks and materials from this job not yet on this estimate."
      rows={uncoveredRows}
      bind:selected
      directLabel="Add as its own line"
      onDirect={billDirect}
      emptyText="No unquoted tasks or materials."
    />
  {/if}
{/if}

<PriceListPicker open={pickerOpen} onChoose={handleChoose} onclose={() => { pickerOpen = false; }} />

<EstimateAddLineForm
  open={addChoice != null}
  choice={addChoice}
  estimateId={estimate.estimate_id}
  {categories}
  onSaved={handleLineAdded}
  onClose={() => { addChoice = null; }}
/>

<LineItemModal
  open={modalOpen}
  mode="edit"
  apiBase={apiBase}
  item={modalItem}
  {categories}
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

<!-- "Generate work…" (Task 7): mirror-seeded manual task create, bound to
     the estimate line via claimEstimateLine so the mint (MintService,
     accepted-only) claims it atomically with task creation. -->
<WorkItemForm
  open={mintModalOpen}
  mode="manual"
  context="job"
  contextId={estimate.job}
  presetName={mintModalLine?.description || ''}
  presetQty={mintModalLine?.qty ?? null}
  claimEstimateLine={mintModalLine?.line_item_id ?? null}
  {categories}
  onSaved={handleMintSaved}
  onClose={closeMintModal}
/>

<BundleModal
  open={bundleModalOpen}
  atoms={bundleAtoms}
  {apiBase}
  onCreated={handleBundleCreated}
  onConflict={handleBundleConflict}
  onClose={() => { bundleModalOpen = false; }}
/>

<Modal open={removeDialogLine != null} onCancel={() => { removeDialogLine = null; }} label="Remove line">
  {#if removeDialogLine}
    <h3>Remove line</h3>
    <p>
      A deliverable was made from this line
      ("{(removeDialogLine.linked_deliverables[0] || {}).description}").
      Remove the deliverable as well?
    </p>
    <div class="remove-dialog-buttons">
      <button type="button" onclick={() => removeLine(removeDialogLine, { deleteDeliverables: true })}>
        Remove line and deliverable
      </button>
      <button type="button" onclick={() => removeLine(removeDialogLine, { deleteDeliverables: false })}>
        Remove line, keep deliverable
      </button>
      <button type="button" onclick={() => { removeDialogLine = null; }}>Cancel</button>
    </div>
  {/if}
</Modal>

<style>
  table { border-collapse: collapse; }
  th, td { padding: 6px 10px; }
  .pool-empty-hint { margin-top: 16px; color: #6b7280; font-size: 14px; }
  /* Matches the old LineItemTable's needs-category marker (send is blocked
     without an accounting_category — the estimator must see this before the
     send-time error). */
  .needs-category { background-color: #fff8e1; color: #b45309; font-style: italic; }
  /* Passive qty/units drift note between a line and its linked deliverable. */
  .deliv-mismatch { color: #b45309; }
  .remove-dialog-buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  /* Muted amber notice banner — informational, not the red error overlay.
     Matches InvoiceEditView's .doc-warning (same family, same styling). */
  .doc-warning {
    border: 1px solid #f0c36d; background: #fff8e1; color: #92620a;
    border-radius: 6px; padding: 8px 12px; margin: 10px 0; font-size: 13px;
  }
</style>
