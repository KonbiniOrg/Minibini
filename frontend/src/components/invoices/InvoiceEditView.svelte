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
  import { coShortLabel, estReferenceText } from '../../lib/agreementReference.js';
  import AdjustmentModal from '../AdjustmentModal.svelte';
  import LineItemModal from '../LineItemModal.svelte';
  import PriceListPicker from '../PriceListPicker.svelte';
  import Modal from '../Modal.svelte';
  import LinkifiedText from '../LinkifiedText.svelte';
  import InvoiceAddLineForm from './InvoiceAddLineForm.svelte';
  import AgreementAdjustmentsPanel from './AgreementAdjustmentsPanel.svelte';
  import BackingChip from '../docsurface/BackingChip.svelte';
  import AtomChildRow from '../docsurface/AtomChildRow.svelte';
  import AtomCaptionRow from '../docsurface/AtomCaptionRow.svelte';
  import UncoveredWorkSection from '../docsurface/UncoveredWorkSection.svelte';
  import NewLineFromSelectedRow from '../docsurface/NewLineFromSelectedRow.svelte';
  import QtyUnits from '../docsurface/QtyUnits.svelte';

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

  // ── Add from agreement… — the restore picker (spec §7.2's "arriving
  // referenced but unclaimed" fallback needs a way back onto the invoice
  // beyond the session-only struck-row Restore below, which is lost on a
  // mode flip or reload). Loaded once canEdit is known (only a financials
  // manager may hit the endpoint) and refreshed after any gesture that adds
  // or removes an agreement-line reference. ────────────────────────────────
  let remainingLines = $state([]);
  let agreementPickerOpen = $state(false);
  let addingLineKey = $state(null);

  async function loadRemaining() {
    if (!canEdit) { remainingLines = []; return; }
    try {
      const resp = await api.get(`${apiBase}/remaining-agreement-lines/`);
      remainingLines = resp.lines || [];
    } catch (_) {
      remainingLines = [];
    }
  }

  $effect(() => {
    if (invoice?.invoice_id && canEdit) loadRemaining();
  });

  function agreementLineKey(line) {
    return line.estimate_line_id != null
      ? `e:${line.estimate_line_id}` : `c:${line.co_line_id}`;
  }

  async function addFromAgreement(line) {
    addingLineKey = agreementLineKey(line);
    try {
      const payload = line.estimate_line_id != null
        ? { estimate_line_id: line.estimate_line_id }
        : { co_line_id: line.co_line_id };
      await api.post(`${apiBase}/restore-line/`, payload);
      await loadRemaining();
      onChanged();
    } catch (e) {
      await handleMutationError(e, 'Could not add this agreement line to the invoice.');
    } finally {
      addingLineKey = null;
    }
  }

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
      // Not awaited: the remaining-agreement-lines refresh is a local
      // freshness nicety for the picker button, not something onChanged's
      // caller (InvoicePanel's own refresh) should wait on.
      loadRemaining();
      onChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not apply everything.'));
    }
  }
  async function copyFromEstimate() {
    try {
      await api.post(`${apiBase}/copy-from-estimate/`, {});
      loadRemaining();
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
  // (draft-only, and an agreement-backed line is freely re-addable). The
  // server-side delete releases the agreement reference and mirrored claims
  // (InvoiceService.remove_line), so the line simply reappears in the
  // "Add from agreement" section below — that section is the single restore
  // path (RM 2026-08-12: the old in-table struck rows duplicated it and
  // confused an emptied invoice).
  async function handleRemoveItem(li) {
    try {
      await api.delete(`${apiBase}/line-items/${li.line_item_id}/`);
      loadRemaining();
      onChanged();
    } catch (e) {
      showError(errorMessage(e, 'Could not remove this line from the invoice.'));
    }
  }

  // ── Backing controls ──────────────────────────────────────────────────────
  function showUseEstimate(li) {
    return li.agreement_ref != null && li.backing !== 'estimate';
  }
  function showUseActuals(li) {
    // qty === 0 is excluded: useActuals() divides by qty to derive a
    // per-unit price, so a zero-qty line has nothing to solve for and the
    // button would silently no-op when clicked.
    return (li.backing === 'estimate' || li.backing === 'edited')
      && li.actuals_total != null && Number(li.qty) !== 0;
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
  // "descoped by CO-N" chip reads `descoped_by_co_number` (the CO whose
  // remove line struck this atom off the accepted agreement — Task 3);
  // `struck_from_agreement` is the server-computed display gate, already
  // suppressed on a cancelled task (one amber badge is a prompt, two is
  // noise) — this branch never re-derives that suppression client-side.
  function atomChip(atom) {
    if (atom.state === 'claimed_by_other') {
      return { label: `invoiced — ${atom.claiming_invoice_number || ''}`.trim(), cls: 'invoiced-elsewhere' };
    }
    if (atom.task_cancelled) {
      return { label: 'cancelled — work done', cls: 'edited' };
    }
    if (atom.struck_from_agreement) {
      return { label: `descoped by ${coShortLabel(atom.descoped_by_co_number)}`, cls: 'edited' };
    }
    return undefined;
  }

  // A deposit/progress invoice — every line is a deposit line (and there is
  // at least one). Derived from content, never stored (spec §7.4
  // no-invoice-mode). Advance money bills against the job as a whole, so the
  // agreement machinery (uncovered work, Add from agreement) is withheld on
  // it — RM 2026-08-09. A mixed invoice keeps both offerings.
  let isDepositInvoice = $derived(
    lineItems.length > 0 && lineItems.every((li) => li.is_deposit)
  );

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

  // No post-create edit modal on either creation gesture (RM 2026-08-16,
  // matching the estimate/CO surfaces): the line is complete as created;
  // editing is the user's decision via the row's own Edit button.
  async function createLineFromSelected() {
    try {
      await api.post(`${apiBase}/line-items-from-atoms/`, {
        atoms: parseSelected(selected),
      });
      selected = [];
      await onChanged();
    } catch (e) {
      await handleMutationError(e, 'Could not create a line from the selected atoms.');
    }
  }

  async function billDirect(rowId) {
    try {
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

  // "The estimate said $X for the work billed here" — Σ est_amount over
  // on-doc lines seeded from the agreement (estimate/actuals/edited backing
  // all keep their ref; hand and deposit lines have none). Rendered small in
  // the Total row's Backing cell so it sits under the chips, beside the
  // invoice's actual total. Null (cell stays empty) when no line has a ref.
  let estimateTotal = $derived.by(() => {
    const referenced = lineItems.filter((li) => li.agreement_ref != null);
    if (referenced.length === 0) return null;
    return referenced.reduce((sum, li) => sum + Number(li.agreement_ref.est_amount || 0), 0);
  });

  // Small provenance caption under the description for an adjustment line —
  // hand/sourced lines already carry their nested AtomChildRows or the
  // Backing chip's est-reference for that.
  function provenanceText(li) {
    if (!li.adjustment_service_detail) return '';
    const pct = Number(li.adjustment_service_detail.rate);
    const sign = pct >= 0 ? '+' : '';
    return `${sign}${pct}% ${li.adjustment_service_detail.name}`;
  }

  // ── Uncategorized-line chip + targeted-adjustment warning (Phase 3 Task 6)
  // used_fallback_ac (serializer-computed) flags a line whose accounting
  // category is the configured fallback — the categories list this panel
  // loads is unfiltered, so the fallback row (name/taxability) is looked up
  // client-side by the line's own AC id. A stale/missing categories list
  // (client hasn't refreshed since the fallback was reconfigured) degrades
  // to a bare "uncategorized" rather than guessing.
  function fallbackCategoryFor(li) {
    return categories.find((c) => c.id === li.accounting_category) || null;
  }
  function uncategorizedChipText(li) {
    const cat = fallbackCategoryFor(li);
    if (!cat) return 'uncategorized';
    return `uncategorized → ${cat.name} · ${cat.taxable ? 'taxable' : 'non-taxable'}`;
  }

  // A targeted percentage adjustment (a target list means "only these
  // categories", never "all") silently skips any line still sitting on the
  // fallback category — the warning below surfaces that before it bites at
  // send/QBO-push time.
  let hasUncategorizedLine = $derived(lineItems.some((li) => li.used_fallback_ac === true));
  let hasTargetedAdjustment = $derived(
    lineItems.some((li) =>
      li.adjustment_service != null && (li.adjustment_target_categories || []).length > 0)
  );
  let showUncategorizedWarning = $derived(hasUncategorizedLine && hasTargetedAdjustment);
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
    {#if remainingLines.length > 0 && !isDepositInvoice}
      <button type="button" onclick={() => { agreementPickerOpen = true; }}>Add from agreement&hellip;</button>
    {/if}
  </p>
{/if}

{#if showUncategorizedWarning}
  <div class="doc-warning">
    This invoice has uncategorized lines. Targeted adjustments never apply to
    them — categorize the lines or check the adjustment's targets.
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
        <td class="text-right"><QtyUnits qty={li.qty} units={li.units} /></td>
        <td class="text-right">{fmtMoney(li.price)}</td>
        <td class="text-right">{fmtMoney(lineAmount(li))}</td>
        <td>
          <BackingChip backing={li.backing} syncedWithEstimate={isSynced(li)} />
          {#if li.used_fallback_ac}
            <span class="uncategorized-chip">{uncategorizedChipText(li)}</span>
          {/if}
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
      <AtomCaptionRow
        sources={li.sources || []}
        colspanBefore={1}
        colspan={5 + (canEdit ? 1 : 0)}
      />
      {#each li.sources || [] as source (source.source_id)}
        <AtomChildRow
          atom={{
            // Pass the real source_type through — deposit/expense rows have
            // their own tags in ATOM_KIND_TAGS; atomKindTag falls back to
            // 'mat' for anything unknown, preserving the old binary behavior.
            kind: source.source_type,
            description: source.description ?? '(removed)',
            qty_display: formatQtyUnits(source.qty, source.units),
            rate: source.rate,
            amount: source.computed_amount,
          }}
          colspanBefore={1}
          colspanAfter={ATOM_ROW_COLSPAN_AFTER + (canEdit ? 1 : 0)}
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
  <tfoot>
    <tr class="grand">
      <td colspan="4"><strong>Total</strong></td>
      <td class="text-right"><strong>{fmtMoney(total)}</strong></td>
      <td colspan={canEdit ? 2 : 1}>
        {#if estimateTotal != null}
          <small>estimate {fmtMoney(estimateTotal)}</small>
        {/if}
      </td>
    </tr>
  </tfoot>
</table>

{#if canEdit}
  {#if !isDepositInvoice}
    <UncoveredWorkSection
      title="Unbilled work"
      subtitle="Tasks, materials, and expenses from this job not yet on this invoice."
      rows={uncoveredRows}
      bind:selected
      directLabel="Bill as its own line"
      onDirect={billDirect}
      emptyText="No unbilled items."
    />
  {/if}

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

<Modal open={agreementPickerOpen} onCancel={() => { agreementPickerOpen = false; }} label="Add from agreement">
  <div class="aap-header">
    <strong>Add from agreement</strong>
    <button type="button" onclick={() => { agreementPickerOpen = false; }}>Close</button>
  </div>
  <table class="data-table">
    <thead>
      <tr>
        <th>Description</th>
        <th class="text-right">Qty</th>
        <th class="text-right">Price</th>
        <th class="text-right">Amount</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {#each remainingLines as line (agreementLineKey(line))}
        <tr>
          <td>{line.description}</td>
          <td class="text-right"><QtyUnits qty={line.qty} units={line.units} /></td>
          <td class="text-right">{fmtMoney(line.price)}</td>
          <td class="text-right">{fmtMoney(Number(line.qty) * Number(line.price))}</td>
          <td>
            <button
              type="button"
              onclick={() => addFromAgreement(line)}
              disabled={addingLineKey === agreementLineKey(line)}
            >{addingLineKey === agreementLineKey(line) ? 'Adding…' : 'Add to this invoice'}</button>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</Modal>

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
  /* Uncategorized-line chip (Phase 3 Task 6) — same shape as .backing-chip,
     amber like .needs-category (the two mark related but distinct states:
     no category at all vs. parked on the fallback category). */
  .uncategorized-chip { display:inline-block; font-size:11px; font-weight:600;
    padding:1px 8px; border-radius:999px; white-space:nowrap;
    background:#fff8e1; color:#b45309; margin-left: 4px; }
  /* Muted amber notice banner — informational, not the red error overlay. */
  .doc-warning {
    border: 1px solid #f0c36d; background: #fff8e1; color: #92620a;
    border-radius: 6px; padding: 8px 12px; margin: 10px 0; font-size: 13px;
  }
  .deposit-credits-section { margin-top: 20px; }
  /* Add-from-agreement picker modal header — same shell vocabulary as
     PriceListPicker's .plp-header (bleed to the box edges, divider below). */
  .aap-header {
    display: flex; align-items: center; justify-content: space-between;
    margin: 0 -16px; padding: 0 16px 10px; border-bottom: 1px solid #eee;
  }
</style>
