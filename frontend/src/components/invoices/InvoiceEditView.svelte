<script>
  // The invoice document's "Edit" mode — merges the old lines table and the
  // reconcile wizard into one surface: a `.data-table` of the invoice's line
  // items (each with its atom nest, BackingChip, est-reference, and backing
  // controls) alongside an "uncovered work" pool of not-yet-billed job atoms
  // and a dedicated deposit-credits picker. Presentation + gestures only —
  // InvoicePanel owns data loading (invoice, sourcePool) and refreshes both
  // after `onChanged()`.
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import { formatQtyUnits } from '../../lib/format.js';
  import { fmtMoney } from '../../lib/taskTotals.js';
  import AdjustmentModal from '../AdjustmentModal.svelte';
  import LineItemModal from '../LineItemModal.svelte';
  import PriceListPicker from '../PriceListPicker.svelte';
  import LinkifiedText from '../LinkifiedText.svelte';
  import InvoiceAddLineForm from './InvoiceAddLineForm.svelte';
  import AgreementAdjustmentsPanel from './AgreementAdjustmentsPanel.svelte';
  import BackingChip from '../docsurface/BackingChip.svelte';
  import AtomChildRow from '../docsurface/AtomChildRow.svelte';
  import UncoveredWorkSection from '../docsurface/UncoveredWorkSection.svelte';
  import NewLineFromSelectedRow from '../docsurface/NewLineFromSelectedRow.svelte';

  // Atom rows carry # (colspanBefore=1) + description/qty/rate/amount (4) +
  // this many blank cells before the onRemove cell — one for the Backing
  // column that always sits between Amount and Actions in the main table,
  // so Remove lands under Actions, not Backing.
  const ATOM_ROW_COLSPAN_AFTER = 1;

  let {
    invoice,
    canEdit,
    onChanged = () => {},
    sourcePool = null,
    lineItems = [],
    categories = [],
  } = $props();

  const apiBase = $derived(`/api/invoices/${invoice.invoice_id}`);

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

  // ── Seed buttons — offered only while the draft has zero lines. Most new
  // invoices already arrive pre-seeded (InvoiceWizardService.open_for_job
  // seeds by default), so this mainly matters for a deposit invoice (which
  // opts out of seeding) before anything else has been added. ─────────────
  async function applyEverything() {
    try {
      await api.post(`${apiBase}/apply-everything/`, {});
      onChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not apply everything.'));
    }
  }
  async function copyFromEstimate() {
    try {
      await api.post(`${apiBase}/copy-from-estimate/`, {});
      onChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not copy from the estimate.'));
    }
  }

  // ── Edit modal (field-edit mode), reused for both "Edit…" and the
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

  // ── Remove from invoice (never "delete" in user-facing text) ─────────────
  // Single-phase: the invoice line-item DELETE has no two-phase confirm gate
  // (draft-only, and an agreement-backed line is freely re-addable via
  // Restore below). The server-side delete already releases the agreement
  // reference and mirrored claims (InvoiceService.remove_line) — the struck
  // row here is purely a client-side memory of what used to be on this
  // line, for the current edit-view session, so Restore has something to
  // show and re-add.
  let removedRefs = $state([]);

  async function handleRemoveItem(li) {
    try {
      await api.delete(`${apiBase}/line-items/${li.line_item_id}/`);
      if (li.agreement_ref) {
        removedRefs = [...removedRefs, {
          kind: li.agreement_ref.kind,
          line_id: li.agreement_ref.line_id,
          description: li.description,
          qty_display: formatQtyUnits(li.qty, li.units),
          price: li.price,
          amount: lineAmount(li),
        }];
      }
      onChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not remove this line from the invoice.'));
    }
  }

  async function handleRestore(entry) {
    try {
      const payload = entry.kind === 'estimate'
        ? { estimate_line_id: entry.line_id }
        : { co_line_id: entry.line_id };
      await api.post(`${apiBase}/restore-line/`, payload);
      removedRefs = removedRefs.filter((r) => r !== entry);
      onChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not restore this line.'));
    }
  }

  // ── Backing controls ──────────────────────────────────────────────────────
  function showUseEstimate(li) {
    return li.agreement_ref != null && li.backing !== 'estimate';
  }
  function showUseActuals(li) {
    return (li.backing === 'estimate' || li.backing === 'edited') && li.actuals_total != null;
  }
  function isSynced(li) {
    return li.backing === 'actuals' && li.agreement_ref != null
      && li.actuals_total === li.agreement_ref.est_amount;
  }

  async function useEstimate(li) {
    try {
      await api.patch(`${apiBase}/line-items/${li.line_item_id}/`, {
        qty: li.agreement_ref.est_qty,
        price: li.agreement_ref.est_price,
      });
      onChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not reset this line to the estimate.'));
    }
  }

  async function useActuals(li) {
    const qty = Number(li.qty);
    if (!qty) return;
    const newPrice = (Math.round((Number(li.actuals_total) / qty) * 100) / 100).toFixed(2);
    try {
      await api.patch(`${apiBase}/line-items/${li.line_item_id}/`, { price: newPrice });
      onChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not set this line to actuals.'));
    }
  }

  // "est was $X · +$Δ" — Δ compares the estimate's stored amount against
  // what the line is actually backed by right now: actuals (when claimed
  // work exists) else the line's own current amount. The "· +$Δ" clause
  // is suppressed entirely when Δ is exactly zero: fmtMoney(0) renders as
  // '-' (its "no amount" sentinel, used everywhere else in this app), so
  // showing the clause at Δ=0 would render the nonsense "· +-" instead of
  // just quietly having nothing to report.
  function estReferenceText(li) {
    const ref = li.agreement_ref;
    if (!ref) return '';
    const estAmount = Number(ref.est_amount);
    const current = li.actuals_total != null ? Number(li.actuals_total) : lineAmount(li);
    const delta = current - estAmount;
    let text = `est was ${fmtMoney(estAmount)}`;
    if (delta !== 0) {
      const sign = delta > 0 ? '+' : '';
      text += ` · ${sign}${fmtMoney(delta)}`;
    }
    return text;
  }

  // ── Uncovered work pool → selection → add-atoms / line-items-from-atoms ──
  // The invoice pool is nested (tasks[].atoms[]), unlike the estimate's flat
  // pool — flatten it here, excluding the atoms already claimed by THIS
  // invoice (they're already shown as nested AtomChildRows under their
  // line) and the "Deposit credits" group (that has its own dedicated
  // section below — pulling a credit creates a deduction, not a billed
  // line, so it doesn't belong in the generic pick list).
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

  function unselectableNote(atom) {
    if (atom.state === 'claimed_by_other') {
      return `Invoiced on ${atom.claiming_invoice_number || ''}`.trim();
    }
    if (atom.state === 'not_billable') {
      return atom.not_billable_reason === 'task_incomplete'
        ? 'Task not complete yet' : 'Material not yet consumed';
    }
    return undefined;
  }

  // INVOICED-elsewhere wins when both apply (a cancelled task claimed by
  // another invoice is uninteresting to bill here at all) — otherwise a
  // cancelled task still carries its own prompt: the work is real and
  // billable, but the biller must consciously choose to bill it rather
  // than have it disappear into an undifferentiated row (same doctrine
  // as the source pool's own `struck_from_agreement` badge). The
  // "descoped by CO-N" chip (Task 9's `chip` prop) arrives with the CO
  // plan and slots in here the same way, unused for now.
  function atomChip(atom) {
    if (atom.state === 'claimed_by_other') {
      return { label: `invoiced — ${atom.claiming_invoice_number || ''}`.trim(), cls: 'invoiced-elsewhere' };
    }
    if (atom.task_cancelled) {
      return { label: 'cancelled — work done', cls: 'edited' };
    }
    if (atom.struck_from_agreement) {
      return { label: 'struck from agreement', cls: 'edited' };
    }
    return undefined;
  }

  let uncoveredRows = $derived(
    (sourcePool?.tasks || [])
      .filter((t) => t.name !== 'Deposit credits')
      .flatMap((t) => t.atoms || [])
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
        chip: atomChip(a),
      }))
  );

  // A claim conflict (another line/invoice grabbed an atom between the pool
  // load and this POST) can't be resolved by retrying blind — refresh so the
  // pool/lines reflect reality, and say so, instead of the generic overlay.
  async function handleMutationError(e, fallback) {
    if (e?.status === 409) {
      selected = [];
      await onChanged();
      showError(errorMessage(e, 'Some of those atoms were claimed by another invoice in the meantime — refreshed.'));
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
  // reliable now that InvoicePanel's refresh no longer unmounts this view.
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

  // ── Deposit credits — dedicated to one-click deduction. Pulling a credit is
  // a distinct gesture from billing an atom (it creates a deduction line
  // against money already collected, not a claim on job work) so it gets
  // its own section and a direct one-click action rather than the
  // select-then-merge flow above. ──────────────────────────────────────────
  let depositCreditAtoms = $derived(
    (sourcePool?.tasks || [])
      .filter((t) => t.name === 'Deposit credits')
      .flatMap((t) => t.atoms || [])
      .filter((a) => a.state === 'available')
  );

  let applyingDepositId = $state(null);

  async function applyDepositCredit(atom) {
    applyingDepositId = atom.id;
    try {
      await api.post(`${apiBase}/line-items-from-atoms/`, {
        atoms: [{ type: 'deposit', id: atom.id }],
      });
      onChanged();
    } catch (e) {
      await handleMutationError(e, 'Could not apply this deposit credit.');
    } finally {
      applyingDepositId = null;
    }
  }

  function lineAmount(li) {
    return Number(li.qty || 0) * Number(li.price || 0);
  }

  let total = $derived(lineItems.reduce((sum, li) => sum + lineAmount(li), 0));

  // Next number offered by "New line from selected" — the highest existing
  // line_number + 1, not the array length (lines can carry gaps in theory,
  // and this is only ever a hint text, never sent to the server).
  let nextLineNumber = $derived(
    lineItems.length > 0
      ? Math.max(...lineItems.map((li) => li.line_number || 0)) + 1
      : 1
  );

  // Small provenance caption under the description for an adjustment line —
  // hand/sourced lines already carry their nested AtomChildRows or the
  // Backing chip's est-reference for that.
  function provenanceText(li) {
    if (!li.adjustment_service_detail) return '';
    const pct = Number(li.adjustment_service_detail.rate);
    const sign = pct >= 0 ? '+' : '';
    return `${sign}${pct}% ${li.adjustment_service_detail.name}`;
  }
</script>

<h3>Line Items</h3>

{#if canEdit && lineItems.length === 0}
  <p class="seed-buttons">
    <button type="button" onclick={applyEverything}>Apply everything</button>
    <button
      type="button"
      onclick={copyFromEstimate}
      disabled={invoice.job_has_other_invoices}
      title={invoice.job_has_other_invoices ? 'Not available once another invoice exists for this job' : undefined}
    >Copy from estimate</button>
  </p>
{/if}

{#if canEdit}
  <p>
    <button type="button" onclick={() => { pickerOpen = true; }}>Add Line Item</button>
    <button type="button" onclick={() => { adjustmentModalOpen = true; }}>Add Adjustment</button>
  </p>
{/if}

<table class="data-table line-items-table">
  <thead>
    <tr>
      <th>#</th>
      <th>Description</th>
      <th class="text-right">Qty</th>
      <th class="text-right">Price</th>
      <th class="text-right">Amount</th>
      <th>Backing</th>
      {#if canEdit}<th>Actions</th>{/if}
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
        <td class="text-right">{formatQtyUnits(li.qty, li.units)}</td>
        <td class="text-right">{fmtMoney(li.price)}</td>
        <td class="text-right">{fmtMoney(lineAmount(li))}</td>
        <td>
          <BackingChip backing={li.backing} syncedWithEstimate={isSynced(li)} />
          {#if estReferenceText(li)}<br><small>{estReferenceText(li)}</small>{/if}
        </td>
        {#if canEdit}
          <td>
            {#if showUseEstimate(li)}
              <button type="button" onclick={() => useEstimate(li)}>Use estimate</button>
            {/if}
            {#if showUseActuals(li)}
              <button type="button" onclick={() => useActuals(li)}>Use actuals</button>
            {/if}
            <button type="button" onclick={() => openEditItem(li)}>Edit&hellip;</button>
            <button type="button" onclick={() => handleRemoveItem(li)}>Remove from invoice</button>
            {#if selected.length > 0}
              <button type="button" onclick={() => addSelectedToLine(li)}>Add selected here</button>
            {/if}
          </td>
        {/if}
      </tr>
      {#each li.sources || [] as source (source.source_id)}
        <AtomChildRow
          atom={{
            kind: source.source_type === 'task' ? 'task' : 'material',
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
        nextNumber={String(nextLineNumber)}
        onCreate={createLineFromSelected}
      />
      {#each removedRefs as entry (entry.kind + ':' + entry.line_id)}
        <tr class="doc-offdoc">
          <td></td>
          <td class="preserve-breaks">{entry.description}</td>
          <td class="text-right">{entry.qty_display}</td>
          <td class="text-right">{fmtMoney(entry.price)}</td>
          <td class="text-right">{fmtMoney(entry.amount)}</td>
          <td></td>
          <td><button type="button" onclick={() => handleRestore(entry)}>Restore</button></td>
        </tr>
      {/each}
    {/if}
  </tbody>
  <tfoot>
    <tr class="grand">
      <td colspan="4"><strong>Total</strong></td>
      <td class="text-right"><strong>{fmtMoney(total)}</strong></td>
      <td colspan={canEdit ? 2 : 1}></td>
    </tr>
  </tfoot>
</table>

{#if canEdit}
  <UncoveredWorkSection
    title="Uncovered work"
    subtitle="Tasks, materials, expenses, and fees from this job not yet on this invoice."
    rows={uncoveredRows}
    bind:selected
    directLabel="Bill as its own line"
    onDirect={billDirect}
    emptyText="No uncovered billable items."
  />

  {#if depositCreditAtoms.length > 0}
    <section class="deposit-credits-section">
      <h3>Deposit credits</h3>
      <p>Unapplied deposits on this job that can be pulled in as a deduction.</p>
      <table class="data-table">
        <tbody>
          {#each depositCreditAtoms as atom (atom.id)}
            <tr>
              <td>
                {atom.description}
                {#if atom.sub_info}<br><small>{atom.sub_info}</small>{/if}
              </td>
              <td class="text-right">{fmtMoney(atom.amount)}</td>
              <td>
                <button
                  type="button"
                  onclick={() => applyDepositCredit(atom)}
                  disabled={applyingDepositId === atom.id}
                >{applyingDepositId === atom.id ? 'Applying…' : 'Apply to this invoice'}</button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </section>
  {/if}

  <AgreementAdjustmentsPanel
    invoiceId={invoice.invoice_id}
    refreshKey={lineItems.map((li) => li.line_item_id).join(',')}
    onLineItemAdded={onChanged}
  />
{/if}

<PriceListPicker open={pickerOpen} onChoose={handleChoose} onclose={() => { pickerOpen = false; }} />

<InvoiceAddLineForm
  open={addChoice != null}
  choice={addChoice}
  invoiceId={invoice.invoice_id}
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

<style>
  table { border-collapse: collapse; }
  th, td { padding: 6px 10px; }
  /* Matches LineItemTable's old needs-category marker (send is blocked
     without an accounting_category — the biller must see this before the
     send-time error). */
  .needs-category { background-color: #fff8e1; color: #b45309; font-style: italic; }
  .deposit-credits-section { margin-top: 20px; }
</style>
