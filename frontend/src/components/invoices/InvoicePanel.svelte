<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import { canManageFinancials } from '../../stores/permissions.js';
  import LineItemTable from '../LineItemTable.svelte';
  import LineItemModal from '../LineItemModal.svelte';
  import AdjustmentModal from '../AdjustmentModal.svelte';
  import DocSubnav from '../jobs/DocSubnav.svelte';
  import ReconcileMode from '../wizards/ReconcileMode.svelte';
  import { getJobWs, rememberMode } from '../../stores/jobWorkspace.js';

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
  let modalMode = $state('create');
  let modalItem = $state(null);
  let adjustmentModalOpen = $state(false);

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
    // Returning to lines must show fresh data — reconcile mode may have mutated
    // the invoice's line items.
    if (next === 'lines') loadInvoice();
  }

  let lineItems = $derived(
    (invoice?.line_items || []).slice().sort((a, b) => a.line_number - b.line_number)
  );

  let allLinesHaveCategory = $derived(
    lineItems.every(li => li.accounting_category != null)
  );

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

  function openAddItem() { modalItem = null; modalMode = 'create'; modalOpen = true; }
  function openEditItem(li) { modalItem = li; modalMode = 'edit'; modalOpen = true; }
  function handleSaved() { modalOpen = false; modalItem = null; loadInvoice(); }

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

  $effect(() => {
    if (invoiceId) {
      loadInvoice();
      loadCategories();
    }
  });

  $effect(() => {
    if (jobId) {
      loadInvoices();
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
      label: inv.invoice_number,
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
</script>

{#snippet newInvoiceAction()}
  <button type="button" class="new-invoice-btn" onclick={startInvoice} disabled={startingInvoice}>
    {startingInvoice ? 'Starting…' : '+ New invoice'}
  </button>
{/snippet}

{#if subnavItems.length > 0}
  <DocSubnav
    items={subnavItems}
    section="invoice"
    trailing={canCreateInvoice ? newInvoiceAction : null}
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
    <span class="page-title">Invoice: {invoice.invoice_number}</span>
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
      <tr><td>Invoice Number</td><td>{invoice.invoice_number}</td></tr>
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
    {categories}
    showSource={true}
    canEdit={canEditLineItems}
    actions={canEditLineItems ? actionsSnippet : null}
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
    {#if job?.can_manage}
      <button type="button" onclick={startInvoice} disabled={startingInvoice}>
        {startingInvoice ? 'Starting…' : 'Start Invoice'}
      </button>
    {:else}
      <p>No invoices yet.</p>
    {/if}
  </div>
{/if}

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
</style>
