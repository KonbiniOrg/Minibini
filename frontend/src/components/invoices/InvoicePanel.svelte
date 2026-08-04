<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import { canManageFinancials } from '../../stores/permissions.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { unappliedDepositCredits } from '../../lib/depositCredits.js';
  import LineItemTable from '../LineItemTable.svelte';
  import LineItemModal from '../LineItemModal.svelte';
  import AdjustmentModal from '../AdjustmentModal.svelte';
  import PriceListPicker from '../PriceListPicker.svelte';
  import InvoiceAddLineForm from './InvoiceAddLineForm.svelte';
  import DepositInvoiceModal from './DepositInvoiceModal.svelte';
  import DocSubnav from '../jobs/DocSubnav.svelte';
  import ReconcileMode from '../wizards/ReconcileMode.svelte';
  import { getJobWs, rememberMode } from '../../stores/jobWorkspace.js';
  import { formatMoney } from '../../lib/format.js';

  let { job, invoiceId, onJobChange = () => {} } = $props();

  let invoice = $state(null);
  let invoices = $state([]); // this job's invoices (raw /api/invoices/?job= results)
  let listLoaded = $state(false);
  let categories = $state([]);
  let docLoading = $state(true);
  let error = $state('');
  let success = $state(null);

  let canEditLineItems = $derived($canManageFinancials && invoice?.status === 'draft');
  // "Show Billables" when the job has anything billable to pull from — tasks,
  // materials, OR fees. (JobSerializer exposes all three.) The pool may still be
  // empty of logged actuals — that's fine, we still offer the wizard view.
  let hasBillables = $derived(
    (job?.tasks?.length ?? 0) > 0 ||
    (job?.materials?.length ?? 0) > 0 ||
    (job?.fees?.length ?? 0) > 0
  );
  // Revise placeholder: visible on sent invoices, not yet functional.
  let canSeeRevise = $derived(
    $canManageFinancials && (invoice?.status === 'open' || invoice?.status === 'partly-paid')
  );

  let modalOpen = $state(false);
  let modalMode = $state('edit');
  let modalItem = $state(null);
  let adjustmentModalOpen = $state(false);
  let pickerOpen = $state(false);
  let addChoice = $state(null);
  let depositModalOpen = $state(false);

  // Reconcile (wizard) is a mode of this panel, not a separate route. Initial
  // mode comes from the per-doc workspace memory, but is validated against the
  // live doc: reconcile is only restorable while the invoice is still an
  // editable draft (someone may have sent it since the mode was remembered).
  let mode = $state('lines');
  let modeInitializedFor = $state(null);
  $effect(() => {
    if (invoice && String(invoice.invoice_id) === String(invoiceId)
        && modeInitializedFor !== String(invoiceId)) {
      const remembered = getJobWs(job?.job_id).modes[`inv:${invoiceId}`] ?? 'lines';
      mode = (remembered === 'reconcile' && canEditLineItems) ? 'reconcile' : 'lines';
      modeInitializedFor = String(invoiceId);
    }
  });

  function setMode(next) {
    mode = next;
    rememberMode(job?.job_id, `inv:${invoiceId}`, next);
    // Returning to lines must show fresh data — reconcile mode may have
    // mutated the invoice's line items. It can also claim/release a deposit
    // credit (an "Add Here" pull creates the deduction line's source row),
    // which changes the job-scoped `invoices` list the unapplied-deposit-
    // credit notice is derived from — refresh that too, not just the single
    // invoice.
    if (next === 'lines') {
      loadInvoice();
      loadInvoices();
    }
  }

  let lineItems = $derived(
    (invoice?.line_items || []).slice().sort((a, b) => a.line_number - b.line_number)
  );

  let allLinesHaveCategory = $derived(
    lineItems.every(li => li.accounting_category != null)
  );

  // task-owned-money Phase 3, Task 4 — display-level warning only (no
  // computation change): a targeted percentage adjustment (non-empty
  // adjustment_target_categories) can never have applied to a fallback-
  // stamped line, because the fallback AC is excluded from AC pickers and
  // so can never appear in a target set. Surfacing this tells the biller
  // to check whether a flagged (used_fallback_ac) line's amount should
  // actually have been included in that adjustment's base.
  let hasTargetedAdjustment = $derived(
    lineItems.some((li) => li.adjustment_service && (li.adjustment_target_categories?.length ?? 0) > 0)
  );
  let hasFallbackFlaggedLine = $derived(lineItems.some((li) => li.used_fallback_ac));
  let showFallbackAdjustmentWarning = $derived(hasTargetedAdjustment && hasFallbackFlaggedLine);

  async function applyEverything() {
    try {
      await api.post(`/api/invoices/${invoice.invoice_id}/apply-everything/`, {});
      await loadInvoice();
    } catch (e) {
      // api.js surfaces error overlay automatically; nothing to do here
    }
  }

  async function copyFromEstimate() {
    try {
      await api.post(`/api/invoices/${invoice.invoice_id}/copy-from-estimate/`, {});
      await loadInvoice();
    } catch (e) {
      // api.js surfaces error overlay automatically; nothing to do here
    }
  }

  function openAddItem() { pickerOpen = true; }
  function openEditItem(li) { modalItem = li; modalMode = 'edit'; modalOpen = true; }
  function handleSaved() { modalOpen = false; modalItem = null; loadInvoice(); }

  function handleChoose(choice) {
    pickerOpen = false;
    addChoice = choice;
  }
  function handleLineAdded() {
    addChoice = null;
    loadInvoice();
  }

  // Gates the deposit modal's enabled state: only offer it once an active
  // deposit accounting category exists (server stamps it; no AC select shown
  // in the deposit form), same rule as the settings deposit-category picker.
  let hasDepositCategory = $derived(
    categories.some((c) => c.is_active !== false && c.is_deposit)
  );

  // Task 22 — unapplied deposit credit notice (draft-panel only). Derived
  // from the same job-scoped `invoices` array used for the Add Deposit
  // Invoice gate above; see lib/depositCredits.js for the exact-parity
  // derivation. The notice text itself is shown to any viewer of the
  // draft (informational); only the Apply action is gated on
  // canEditLineItems, same as any other line-item mutation.
  let unappliedCredits = $derived(unappliedDepositCredits(invoices));
  let applyingCreditId = $state(null);

  async function applyDepositCredit(credit) {
    applyingCreditId = credit.lineItem.line_item_id;
    try {
      await api.post(`/api/invoices/${invoice.invoice_id}/line-items-from-atoms/`, {
        atoms: [{ type: 'deposit', id: credit.lineItem.line_item_id }],
      });
      await loadInvoice();
      await loadInvoices();
    } catch (e) {
      // No form here (this is a plain action button) — everything routes
      // to the overlay, same venue as handleDeleteItem/handleReorder above.
      // Covers the 409 atoms_already_claimed case (a field-less {detail,
      // code, atom_ids} body) same as any other operation error.
      const t = triageError(e);
      showError(t.overlay || t.message || 'Could not apply deposit credit.');
      // The credit may have just been claimed by someone else (the 409
      // case) — refresh so the notice reflects current reality.
      await loadInvoices();
    } finally {
      applyingCreditId = null;
    }
  }

  function creditAmount(li) {
    return Number(li.qty) * Number(li.price);
  }

  async function handleDeleteItem(li) {
    // No confirm: draft-only line edit, re-addable by hand.
    try {
      await api.delete(`/api/invoices/${invoice.invoice_id}/line-items/${li.line_item_id}/`);
      await loadInvoice();
    } catch (e) {
      showError(errorMessage(e, 'Could not delete line item.'));
    }
  }

  async function handleReorder(itemIds) {
    try {
      await api.post(`/api/invoices/${invoice.invoice_id}/line-items/reorder/`, { item_ids: itemIds });
      await loadInvoice();
    } catch (e) {
      showError(errorMessage(e, 'Could not reorder line items.'));
    }
  }

  function moveUp(index) {
    if (index === 0) return;
    const ids = lineItems.map(li => li.line_item_id);
    [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]];
    handleReorder(ids);
  }

  function moveDown(index) {
    if (index >= lineItems.length - 1) return;
    const ids = lineItems.map(li => li.line_item_id);
    [ids[index], ids[index + 1]] = [ids[index + 1], ids[index]];
    handleReorder(ids);
  }

  async function loadInvoice() {
    docLoading = true;
    error = '';
    try {
      invoice = await api.get(`/api/invoices/${invoiceId}/`);
    } catch (e) {
      error = e.message || 'Could not load invoice.';
    } finally {
      docLoading = false;
    }
  }

  // Value-keyed: the glue (JobInvoicePage) assigns a new `job` object on
  // every loadJob() run, even when the job itself hasn't changed. Deriving
  // jobId memoizes on the value, so the effect below only reruns when the
  // job actually changes. The load functions read this derived (not
  // job.job_id directly) so they don't reintroduce a dependency on the raw
  // job object.
  const jobId = $derived(job?.job_id);

  async function loadInvoices() {
    try {
      const resp = await api.get(`/api/invoices/?job=${jobId}`);
      invoices = resp?.results || resp || [];
    } catch (_) {
      invoices = [];
    } finally {
      listLoaded = true;
    }
  }

  async function loadCategories() {
    try {
      const resp = await api.get('/api/accounting-categories/?page_size=100');
      categories = resp.results || resp;
    } catch (_) {
      categories = [];
    }
  }

  // Display-only category list (task-owned-money Phase 3, Task 4 follow-up):
  // `categories` (above) deliberately EXCLUDES the Configuration-designated
  // fallback category — it feeds the LineItemModal/AdjustmentModal pickers,
  // which must never offer the fallback as something a human manually
  // assigns. But LineItemTable's categoryName()/categoryTaxable()/
  // fallbackBadgeText() are read-only lookups, not pickers — using the
  // excluded list there made a fallback-stamped line's own badge unable to
  // name its own category ("Uncategorized → —" instead of "Uncategorized →
  // <name>"), and would do the same to any other line/RateScheme that
  // happens to reference whatever category is currently the fallback.
  // include_fallback=true keeps the lookup complete without touching the
  // picker lists.
  let displayCategories = $state([]);
  async function loadDisplayCategories() {
    try {
      const resp = await api.get('/api/accounting-categories/?page_size=100&include_fallback=true');
      displayCategories = resp.results || resp;
    } catch (_) {
      displayCategories = [];
    }
  }

  $effect(() => {
    if (invoiceId) {
      loadInvoice();
    }
  });

  // Categories are needed for the deposit-category gate (hasDepositCategory)
  // even in the empty state (no invoiceId yet, e.g. the "Add Deposit
  // Invoice" button before any invoice exists) — load off jobId, not
  // invoiceId.
  $effect(() => {
    if (jobId) {
      loadInvoices();
      loadCategories();
      loadDisplayCategories();
    }
  });

  function fmtDate(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleString();
  }

  // Invoice subnav: this job's invoices, oldest first.
  let sortedInvoices = $derived(
    [...(invoices || [])].sort((a, b) => new Date(a.created_date) - new Date(b.created_date))
  );

  let subnavItems = $derived(
    sortedInvoices.map((inv) => ({
      id: `inv-${inv.invoice_id}`,
      label: inv.display_number,
      status: inv.status,
      href: `#/jobs/${job.job_id}/invoice/${inv.invoice_id}`,
      current: String(inv.invoice_id) === String(invoiceId),
    }))
  );

  // A job can carry several invoices (progress billing), but only ONE draft at
  // a time (unique_draft_invoice_per_job) and only while billable. So "+ New
  // invoice" is offered only when the job is billable, no draft is open, and the
  // user can manage financials — mirrors InvoiceWizardService.open_for_job.
  const BILLABLE_JOB_STATUSES = ['approved', 'in_progress', 'work_complete', 'completed', 'cancelled'];
  let hasOpenDraft = $derived((invoices || []).some((i) => i.status === 'draft'));
  let canCreateInvoice = $derived(
    $canManageFinancials && BILLABLE_JOB_STATUSES.includes(job?.status) && !hasOpenDraft
  );
  // The empty-state Start Invoice button shares the billable gate: on a
  // pre-approval job the click could only ever return the backend's refusal,
  // so it is hidden with a hint instead (like the estimate panel's Create
  // Change Order gate).
  let jobBillable = $derived(BILLABLE_JOB_STATUSES.includes(job?.status));

  // Add Deposit Invoice — three states, derived from the job's own
  // `invoices` list (loaded above via loadInvoices, keyed off jobId).
  // InvoicePanel's GET /api/invoices/?job= call carries no ?summary= param,
  // so each entry there is the full InvoiceSerializer — nested line_items
  // included, same shape as the single-invoice GET — so no separate fetch
  // is needed to know whether the job's draft (if any) already has lines.
  //   1. no draft on the job      → "Add Deposit Invoice" (create + line)
  //   2. draft exists, zero lines → "Make this a deposit invoice" (adds the
  //      line to that draft — open_for_job's idempotent lookup resolves to
  //      it, so the same modal flow works unchanged)
  //   3. draft exists, ≥1 lines   → suppressed entirely (both placements)
  let draftInvoice = $derived((invoices || []).find((i) => i.status === 'draft'));
  let draftHasLines = $derived((draftInvoice?.line_items?.length ?? 0) > 0);
  let showDepositButton = $derived(jobBillable && job?.can_manage && !draftHasLines);
  let depositButtonLabel = $derived(
    draftInvoice ? 'Make this a deposit invoice' : 'Add Deposit Invoice'
  );

  let startingInvoice = $state(false);
  async function startInvoice() {
    startingInvoice = true;
    try {
      const inv = await api.post('/api/invoices/', { job: job.job_id });
      window.location.hash = `/jobs/${job.job_id}/invoice/${inv.invoice_id}`;
    } catch (e) {
      showError(errorMessage(e, 'Failed to start invoice.'));
    } finally {
      startingInvoice = false;
    }
  }

  // DepositInvoiceModal does its own two-step create (invoice, then deposit
  // line) and hands back the resulting invoice_id.
  //   - If the user is already viewing the draft that just received the
  //     line (state 2 — Make this a deposit invoice, on its own doc),
  //     reload it in place so the new line appears — the panel's
  //     established convention (same as handleLineAdded's loadInvoice()
  //     call after a normal add-line save), not a full page refresh.
  //   - Otherwise (state 1 — a brand new draft, or state 2 triggered while
  //     viewing a different doc) navigate to the draft, same as Start
  //     Invoice's navigation.
  // Either way, `invoices` is refreshed so the three-state gate above is
  // correct once the affected draft's line count has changed.
  function handleDepositCreated(newInvoiceId) {
    depositModalOpen = false;
    const viewingCreatedDraft = invoiceId != null && String(invoiceId) === String(newInvoiceId);
    if (viewingCreatedDraft) {
      loadInvoice();
    } else {
      window.location.hash = `/jobs/${job.job_id}/invoice/${newInvoiceId}`;
    }
    loadInvoices();
  }
</script>

{#snippet newInvoiceAction()}
  <button type="button" class="new-invoice-btn" onclick={startInvoice} disabled={startingInvoice}>
    {startingInvoice ? 'Starting…' : '+ New invoice'}
  </button>
{/snippet}

{#snippet addDepositInvoiceAction()}
  <button type="button" class="new-invoice-btn" onclick={() => { depositModalOpen = true; }}
    disabled={!hasDepositCategory}
    title={hasDepositCategory ? '' : 'Set a deposit category in Settings first'}>
    {depositButtonLabel}
  </button>
{/snippet}

{#snippet subnavTrailing()}
  {#if canCreateInvoice}{@render newInvoiceAction()}{/if}
  {#if showDepositButton}{@render addDepositInvoiceAction()}{/if}
{/snippet}

{#if subnavItems.length > 0}
  <DocSubnav
    items={subnavItems}
    section="invoice"
    trailing={(canCreateInvoice || showDepositButton) ? subnavTrailing : null}
  />
{/if}

{#if invoiceId}
  {#if docLoading}
    <p>Loading...</p>
  {:else if error}
    <p class="error"><strong>Error:</strong> {error}</p>
  {:else if invoice}
  <div class="page-body">
  <div class="toolbar">
    <span class="page-title">Invoice: {invoice.display_number}</span>
    <span class="status-badge status-{invoice.status}">{invoice.status}</span>
    {#if $canManageFinancials}
      {#if allLinesHaveCategory}
        <a class="action-link" href="#/invoices/{invoice.invoice_id}/send">
          {invoice.qbo_id ? 'Resend Invoice' : 'Send Invoice'}
        </a>
      {:else}
        <button type="button" disabled class="action-link send-blocked">
          {invoice.qbo_id ? 'Resend Invoice' : 'Send Invoice'}
        </button>
        <span class="send-blocked-note">Assign an accounting category to every line before sending.</span>
      {/if}
    {/if}
    {#if canSeeRevise}
      <button type="button" disabled title="Invoice revisions are not available yet.">
        Revise (coming soon)
      </button>
    {/if}
    {#if canEditLineItems}
      {#if mode === 'reconcile'}
        <button type="button" onclick={() => setMode('lines')}>Back to lines</button>
      {:else}
        <button type="button" onclick={() => setMode('reconcile')}>Reconcile</button>
      {/if}
    {/if}
  </div>

  {#if success}
    <p class="success-msg">{success}</p>
  {/if}

  <table class="data-table">
    <tbody>
      <tr><th>Field</th><th>Value</th></tr>
      <tr><td>Invoice Number</td><td>{invoice.display_number}</td></tr>
      <tr><td>Status</td><td>{invoice.status}</td></tr>
      <tr><td>Created Date</td><td>{fmtDate(invoice.created_date)}</td></tr>
      <tr><td>Sent Date</td><td>{invoice.sent_date ? fmtDate(invoice.sent_date) : 'Not sent yet'}</td></tr>
      <tr><td>Due Date</td><td>{invoice.due_date ? fmtDate(invoice.due_date) : '—'}{#if invoice.is_late} <span class="late-flag">(late)</span>{/if}</td></tr>
      <tr><td>Closed Date</td><td>{invoice.closed_date ? fmtDate(invoice.closed_date) : 'Not closed yet'}</td></tr>
      {#if invoice.qbo_id}
        <tr><td>QBO ID</td><td>{invoice.qbo_id}</td></tr>
        <tr><td>QBO Payment Status</td><td>{invoice.qbo_payment_status || 'Pending'}</td></tr>
        {#if invoice.qbo_amount_paid}
          <tr><td>Amount Paid</td><td>${Number(invoice.qbo_amount_paid).toFixed(2)}</td></tr>
        {/if}
      {/if}
    </tbody>
  </table>

  {#if mode === 'reconcile'}
    <ReconcileMode
      docType="invoice"
      docId={invoice.invoice_id}
      onChanged={loadInvoice}
      onExit={() => setMode('lines')}
    />
  {:else}
  {#if invoice.status === 'draft' && unappliedCredits.length > 0}
    <div class="deposit-credit-notice">
      {#each unappliedCredits as credit (credit.lineItem.line_item_id)}
        <div class="deposit-credit-row">
          <span>Unapplied deposit credit — {formatMoney(creditAmount(credit.lineItem))} from {credit.invoice.display_number}</span>
          {#if canEditLineItems}
            <button type="button" onclick={() => applyDepositCredit(credit)}
              disabled={applyingCreditId === credit.lineItem.line_item_id}>
              {applyingCreditId === credit.lineItem.line_item_id ? 'Applying…' : 'Apply deposit credit'}
            </button>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
  {#if showFallbackAdjustmentWarning}
    <div class="fallback-warning-notice">
      This invoice has a targeted percentage adjustment, but targeted adjustments never include uncategorized lines. Review the flagged line(s) below.
    </div>
  {/if}
  <h3>Line Items</h3>
  {#if canEditLineItems}
    {#if lineItems.length === 0}
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
    <p>
      <button type="button" onclick={openAddItem}>Add Line Item</button>
      <button type="button" onclick={() => { adjustmentModalOpen = true; }}>Add Adjustment</button>
      {#if hasBillables}
        <button type="button" onclick={() => setMode('reconcile')}>Show Billables</button>
      {/if}
    </p>
  {/if}

  {#snippet actionsSnippet(li, i)}
    <button type="button" onclick={() => openEditItem(li)}>Edit</button>
    <button type="button" onclick={() => moveUp(i)} disabled={i === 0}>&#9650;</button>
    <button type="button" onclick={() => moveDown(i)} disabled={i === lineItems.length - 1}>&#9660;</button>
    <button type="button" onclick={() => handleDeleteItem(li)}>Delete</button>
  {/snippet}

  <LineItemTable
    {lineItems}
    categories={displayCategories}
    showSource={true}
    canEdit={canEditLineItems}
    actions={canEditLineItems ? actionsSnippet : null}
  />

  <PriceListPicker
    open={pickerOpen}
    onChoose={handleChoose}
    onclose={() => { pickerOpen = false; }}
  />

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
    mode={modalMode}
    apiBase={`/api/invoices/${invoice.invoice_id}`}
    item={modalItem}
    {categories}
    onSaved={handleSaved}
    onClose={() => { modalOpen = false; }}
  />

  <AdjustmentModal
    open={adjustmentModalOpen}
    apiBase={`/api/invoices/${invoice.invoice_id}`}
    {categories}
    onSaved={() => { adjustmentModalOpen = false; loadInvoice(); }}
    onClose={() => { adjustmentModalOpen = false; }}
  />
  {/if}
  </div>
  {/if}
{:else if !listLoaded}
  <p>Loading...</p>
{:else}
  <div class="page-body">
    {#if job?.can_manage && jobBillable}
      <button type="button" onclick={startInvoice} disabled={startingInvoice}>
        {startingInvoice ? 'Starting…' : 'Start Invoice'}
      </button>
      <!-- This branch only renders when the job has zero invoices (see
           JobInvoicePage's docId derivation — invoiceId is only null when
           there truly are none), so showDepositButton/depositButtonLabel
           here always resolve to state 1 ("Add Deposit Invoice") — reusing
           the same derived values as the version-bar placement below keeps
           the gate/label logic single-sourced, but this button keeps its
           own (unstyled, like Start Invoice) markup rather than the
           subnav-trailing snippet's compact ".new-invoice-btn" styling. -->
      {#if showDepositButton}
        <button type="button" onclick={() => { depositModalOpen = true; }}
          disabled={!hasDepositCategory}
          title={hasDepositCategory ? '' : 'Set a deposit category in Settings first'}>
          {depositButtonLabel}
        </button>
      {/if}
    {:else if job?.can_manage}
      <p>No invoices yet. Invoicing becomes available once the job is approved.</p>
    {:else}
      <p>No invoices yet.</p>
    {/if}
  </div>
{/if}

<DepositInvoiceModal
  open={depositModalOpen}
  {job}
  onCreated={handleDepositCreated}
  onClose={() => { depositModalOpen = false; }}
/>

<style>
  .error { color: #a8071a; }
  /* Trailing "+ New invoice" action on the version bar: a compact button that
     reads as an action against the whole invoice set (sits in .doc-subnav-trailing). */
  .new-invoice-btn {
    font-size: 12px; padding: 3px 10px; border-radius: 4px;
    border: 1px solid #cbd5e1; background: #fff; color: #1f2937; cursor: pointer;
  }
  .new-invoice-btn:hover:not(:disabled) { background: #f1f5f9; }
  .new-invoice-btn:disabled { opacity: 0.6; cursor: default; }
  /* .toolbar / .action-link / .page-title come from app.css. */
  /* Status pill styling and colors come from the global .status-badge /
     .status-{status} classes (app.css). */
  .late-flag { color: #b91c1c; font-weight: 600; }
  /* Content aligns to the .page-body gutter (like EstimatePanel and the
     toolbar) — no extra horizontal inset. */
  .success-msg { padding: 8px 0; color: #166534; }
  .send-blocked { opacity: 0.5; cursor: not-allowed; }
  .send-blocked-note { font-size: 12px; color: #6b7280; }
  /* Unapplied deposit credit notice — same boxed-banner vocabulary as
     JobDetail's .change-request-banner (an actionable "needs a decision"
     note, not an error/success message). */
  .deposit-credit-notice {
    background: #ffedd5;
    border: 1px solid #fdba74;
    color: #9a3412;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    margin: 14px 0 4px;
  }
  .deposit-credit-row {
    display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px;
  }
  .deposit-credit-row + .deposit-credit-row {
    margin-top: 6px; padding-top: 6px; border-top: 1px solid #fdba74;
  }
  /* Targeted-adjustment + fallback-AC warning (task-owned-money Phase 3,
     Task 4) — display-level only, same boxed-banner vocabulary as
     .deposit-credit-notice but a distinct (red-leaning) palette since this
     is a caution rather than an actionable-but-benign notice. */
  .fallback-warning-notice {
    background: #fef2f2;
    border: 1px solid #fca5a5;
    color: #991b1b;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    margin: 14px 0 4px;
  }
</style>
