<script>
  import FullOnly from '../FullOnly.svelte';
  import { viewMode } from '../../stores/viewMode.js';

  const {
    job,
    contact = null,
    estimates = null,
    worksheets = null,
    workOrders = null,
    invoices = null,
    history = null,
    onAddNote = null,
  } = $props();

  let noteText = $state('');

  const terminalInvoiceStatuses = ['paid', 'cancelled', 'defaulted', 'superseded'];

  let visibleEstimates = $derived(
    estimates?.results
      ? $viewMode === 'full'
        ? estimates.results
        : (() => {
            const accepted = estimates.results.filter(e => e.status === 'accepted');
            if (accepted.length > 0) return accepted;
            return estimates.results.length > 0 ? [estimates.results[0]] : [];
          })()
      : []
  );

  let visibleWorksheets = $derived(
    worksheets?.results
      ? $viewMode === 'full'
        ? worksheets.results
        : estimates?.results?.length > 0
          ? []
          : worksheets.results.filter(w => w.status !== 'superseded')
      : []
  );

  let visibleWorkOrders = $derived(
    workOrders?.results
      ? $viewMode === 'full'
        ? workOrders.results
        : workOrders.results
      : []
  );

  let visibleInvoices = $derived(
    invoices?.results
      ? $viewMode === 'full'
        ? invoices.results
        : invoices.results.filter(i => !terminalInvoiceStatuses.includes(i.status))
      : []
  );

  let showWorksheetSection = $derived(
    $viewMode === 'full' || (visibleWorksheets.length > 0)
  );

  let showWorkOrderSection = $derived(
    $viewMode === 'full' || (visibleWorkOrders.length > 0)
  );

  let showEstimateSection = $derived(
    $viewMode === 'full' || (visibleEstimates.length > 0)
  );

  let showInvoiceSection = $derived(
    $viewMode === 'full' || (visibleInvoices.length > 0)
  );

  let visibleHistory = $derived(
    history?.results
      ? $viewMode === 'full'
        ? history.results
        : history.results.filter(h => h.entry_type === 'note')
      : []
  );

  async function submitNote() {
    if (!noteText.trim() || !onAddNote) return;
    await onAddNote(noteText.trim());
    noteText = '';
  }
</script>

<dl>
  <dt>Job Number</dt>
  <dd>{job.job_number}</dd>

  <dt>Name</dt>
  <dd>{job.name}</dd>

  <dt>Status</dt>
  <dd>{job.status}</dd>

  {#if job.customer_po_number}
    <dt>Customer PO</dt>
    <dd>{job.customer_po_number}</dd>
  {/if}

  {#if job.description}
    <dt>Description</dt>
    <dd>{job.description}</dd>
  {/if}

  <dt>Created Date</dt>
  <dd>{job.created_date}</dd>

  {#if job.start_date}
    <dt>Start Date</dt>
    <dd>{job.start_date}</dd>
  {/if}

  {#if job.due_date}
    <dt>Due Date</dt>
    <dd>{job.due_date}</dd>
  {/if}
</dl>

<h3>Contact</h3>
{#if contact}
  <p>
    <a href="#/contacts/{contact.contact_id}">{contact.name}</a>
    {#if contact.business}
      (<a href="#/businesses/{contact.business.business_id}">{contact.business.business_name}</a>)
    {/if}
  </p>
{:else}
  <p>No contact.</p>
{/if}

{#if showEstimateSection}
  <h3>Estimates</h3>
  {#if visibleEstimates.length > 0}
    <table border="1">
      <thead>
        <tr><th>Estimate #</th><th>Version</th><th>Status</th><th>Created</th></tr>
      </thead>
      <tbody>
        {#each visibleEstimates as estimate}
          <tr>
            <td><a href="#/estimates/{estimate.estimate_id}">{estimate.estimate_number}</a></td>
            <td>{estimate.version}</td>
            <td>{estimate.status}</td>
            <td>{estimate.created_date}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p>No estimates.</p>
  {/if}
{/if}

{#if showWorksheetSection}
  <h3>Est Worksheets</h3>
  {#if visibleWorksheets.length > 0}
    <table border="1">
      <thead>
        <tr><th>Worksheet ID</th><th>Status</th><th>Version</th><th>Created</th></tr>
      </thead>
      <tbody>
        {#each visibleWorksheets as ws}
          <tr>
            <td><a href="#/worksheets/{ws.est_worksheet_id}">{ws.est_worksheet_id}</a></td>
            <td>{ws.status}</td>
            <td>{ws.version}</td>
            <td>{ws.created_date}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p>No est worksheets.</p>
  {/if}
{/if}

{#if showWorkOrderSection}
  <h3>Work Orders</h3>
  {#if visibleWorkOrders.length > 0}
    <table border="1">
      <thead>
        <tr><th>Work Order ID</th><th>Status</th></tr>
      </thead>
      <tbody>
        {#each visibleWorkOrders as wo}
          <tr>
            <td><a href="#/work-orders/{wo.work_order_id}">{wo.work_order_id}</a></td>
            <td>{wo.status}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p>No work orders.</p>
  {/if}
{/if}

{#if showInvoiceSection}
  <h3>Invoices</h3>
  {#if visibleInvoices.length > 0}
    <table border="1">
      <thead>
        <tr><th>Invoice #</th><th>Status</th><th>Created</th></tr>
      </thead>
      <tbody>
        {#each visibleInvoices as invoice}
          <tr>
            <td><a href="#/invoices/{invoice.invoice_id}">{invoice.invoice_number}</a></td>
            <td>{invoice.status}</td>
            <td>{invoice.created_date}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <p>No {$viewMode === 'lite' ? 'active ' : ''}invoices.</p>
  {/if}
{/if}

<h3>History</h3>
{#if onAddNote}
  <p>
    <textarea bind:value={noteText} rows="2" placeholder="Add a note..."></textarea><br>
    <button onclick={submitNote} disabled={!noteText.trim()}>Add Note</button>
  </p>
{/if}
{#if visibleHistory.length > 0}
  {#each visibleHistory as entry}
    {#if entry.entry_type === 'note'}
      <p>
        <strong>{entry.username || 'Unknown'}</strong>
        ({new Date(entry.timestamp).toLocaleString()}):<br>
        {entry.text}
      </p>
    {:else}
      <p><small>
        <strong>{entry.username || 'System'}</strong>
        ({new Date(entry.timestamp).toLocaleString()})
        [{entry.entry_type}] {entry.object_type}
        {#if entry.changes}
          — {Object.entries(entry.changes).map(([k, v]) => `${k}: ${v.old} → ${v.new}`).join(', ')}
        {/if}
        {#if entry.text}
          — {entry.text}
        {/if}
      </small></p>
    {/if}
  {/each}
{:else}
  <p>No {$viewMode === 'lite' ? 'notes' : 'history'}.</p>
{/if}
