<!-- frontend/src/routes/invoices/InvoiceDetailPage.svelte -->
<script>
  import { onMount } from 'svelte';
  import { link } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import { canManageFinancials } from '../../stores/permissions.js';
  import JobHeader from '../../components/jobs/JobHeader.svelte';
  import LineItemTable from '../../components/LineItemTable.svelte';
  import LineItemModal from '../../components/LineItemModal.svelte';
  import AdjustmentModal from '../../components/AdjustmentModal.svelte';

  const { params = {} } = $props();

  let invoice = $state(null);
  let job = $state(null);
  let contact = $state(null);
  let categories = $state([]);
  let loading = $state(true);
  let error = $state(null);
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
    loading = true;
    error = null;
    try {
      invoice = await api.get(`/api/invoices/${params.id}/`);
      if (invoice?.job) await loadJobContext(invoice.job);
    } catch (e) {
      error = e.message || 'Failed to load invoice';
    } finally {
      loading = false;
    }
  }

  async function loadJobContext(jobId) {
    try {
      job = await api.get(`/api/jobs/${jobId}/`);
      if (job.contact) {
        try { contact = await api.get(`/api/contacts/${job.contact}/`); }
        catch (e) { contact = null; }
      }
    } catch (e) { job = null; contact = null; }
  }

  async function loadCategories() {
    try {
      const resp = await api.get('/api/accounting-categories/?page_size=100');
      categories = resp.results || resp;
    } catch (_) { categories = []; }
  }


  function fmtDate(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleString();
  }

  onMount(() => {
    loadInvoice();
    loadCategories();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p class="error"><strong>Error:</strong> {error}</p>
{:else if invoice}
  {#if job}
    <JobHeader {job} {contact} onStatusChange={loadInvoice} />
  {/if}

  <div class="toolbar">
    <a href={`/jobs/${invoice.job}`} use:link class="back-link">&laquo; back to overview</a>
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
  </div>

  {#if success}
    <p class="success-msg">{success}</p>
  {/if}

  <table class="metadata-table">
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
        <a href={`/invoices/${invoice.invoice_id}/wizard`} use:link>Show Billables</a>
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

<style>
  .error { color: #a8071a; }
  .toolbar {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
    padding: 8px 24px;
  }
  .back-link { font-size: 13px; }
  .action-link {
    display: inline-block; padding: 4px 12px;
    border: 1px solid #d1d5db; border-radius: 3px;
    background: #fff; color: #2563eb; text-decoration: none;
    font-size: 13px; cursor: pointer;
  }
  .action-link:hover { background: #f3f4f6; }
  .page-title { font-size: 18px; font-weight: 600; }
  .status-badge {
    padding: 4px 12px; border-radius: 12px; font-size: 13px;
    font-weight: 600; text-transform: capitalize;
  }
  .status-draft { background: #f3f4f6; color: #374151; }
  .status-sent { background: #dbeafe; color: #1e40af; }
  .status-paid { background: #dcfce7; color: #166534; }
  .status-cancelled { background: #fef3c7; color: #92400e; }
  .late-flag { color: #b91c1c; font-weight: 600; }
  .success-msg { padding: 8px 24px; color: #166534; }
  .metadata-table { border-collapse: collapse; margin: 0 24px 16px; }
  .metadata-table th, .metadata-table td { padding: 6px 10px; }
  h3 { padding: 0 24px; }
  .seed-buttons { padding: 0 24px; }
  .send-blocked { opacity: 0.5; cursor: not-allowed; }
  .send-blocked-note { font-size: 12px; color: #6b7280; }
</style>
