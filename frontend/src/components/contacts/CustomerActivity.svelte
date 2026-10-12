<script>
  // CustomerActivity — the right-hand column of the contact/business detail
  // pages (contacts UI redesign, 2026-10-10). Sections in canonical order:
  // Contacts (business pages only) → Recent Jobs → Open Invoices → Purchase
  // orders → History. Each list section hides its closed rows behind a
  // "show N completed / paid / closed" toggle that extends the table in
  // place. Every section always renders its heading (.section-title) and
  // its action; when nothing is on display a dashed box says why — "No jobs
  // yet." when the section is empty, "No open jobs." when the rows are all
  // hidden behind the toggle (2026-10-11). Populated sections precede empty
  // ones. The rules live in lib/customerActivity.js — this component renders.
  //
  // Modals are hosted by the caller: this component only calls back
  // (onNewContact, onNewJobFor(contactId), onSetDefault(contactId)).
  import DataTable from '../DataTable.svelte';
  import HistoryPanel from '../HistoryPanel.svelte';
  import { canManageJobs, canManageFinancials } from '../../stores/permissions.js';
  import { formatMoney } from '../../lib/format.js';
  import {
    isClosedJob, isClosedInvoice, isClosedPO, splitRows, showLabel, orderSections, statusLabel,
  } from '../../lib/customerActivity.js';

  const {
    jobs = [],
    invoices = [],
    purchaseOrders = [],
    // Business pages only. `contacts === null` → no Contacts section.
    contacts = null,
    defaultContactId = null,
    showContactColumn = false,
    newPOHref = null,
    history = null,
    onAddNote = null,
    onNewContact = null,
    onNewJobFor = null,
    onSetDefault = null,
  } = $props();

  // Per-section "show closed" state.
  let expanded = $state({ jobs: false, invoices: false, pos: false });

  let jobSplit = $derived(splitRows(jobs, isClosedJob));
  let invSplit = $derived(splitRows(invoices, isClosedInvoice));
  let poSplit = $derived(splitRows(purchaseOrders, isClosedPO));

  // Expanded = every row in its original order; collapsed = open rows only.
  let jobRows = $derived(expanded.jobs ? jobs : jobSplit.open);
  let invRows = $derived(expanded.invoices ? invoices : invSplit.open);
  let poRows = $derived(expanded.pos ? purchaseOrders : poSplit.open);

  let sections = $derived(orderSections([
    ...(contacts !== null ? [{ key: 'contacts', total: contacts.length }] : []),
    { key: 'jobs', total: jobs.length },
    { key: 'invoices', total: invoices.length },
    { key: 'pos', total: purchaseOrders.length },
  ]));

  const money = (v) => (v == null || v === '' ? '—' : formatMoney(v));
  const shortDate = (iso) => (iso
    ? new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    : '—');
  const jobNo = (n) => (n || '').replace(/^JOB-/, '');

  let jobColumns = $derived([
    { id: 'number', label: 'Job #', cell: jobNumberCell },
    { id: 'name', label: 'Name', field: 'name' },
    ...(showContactColumn ? [{ id: 'contact', label: 'Contact', cell: jobContactCell }] : []),
    { id: 'status', label: 'Status', cell: jobStatusCell },
    { id: 'started', label: 'Started', cell: jobStartedCell },
    { id: 'estimate', label: 'Estimate', cell: jobEstimateCell, align: 'right' },
  ]);
  const invoiceColumns = [
    { id: 'number', label: 'Invoice #', cell: invNumberCell },
    { id: 'job', label: 'Job', cell: invJobCell },
    { id: 'status', label: 'Status', cell: invStatusCell },
    { id: 'sent', label: 'Sent', cell: invSentCell },
    { id: 'total', label: 'Total', cell: invTotalCell, align: 'right' },
    { id: 'paid', label: 'Paid', cell: invPaidCell, align: 'right' },
    { id: 'balance', label: 'Balance', cell: invBalanceCell, align: 'right' },
  ];
  const poColumns = [
    { id: 'number', label: 'PO #', cell: poNumberCell },
    { id: 'status', label: 'Status', cell: poStatusCell },
    { id: 'issued', label: 'Issued', cell: poIssuedCell },
  ];
  let contactColumns = $derived([
    { id: 'name', label: 'Name', cell: contactNameCell },
    { id: 'email', label: 'Email', cell: contactEmailCell },
    { id: 'phone', label: 'Phone', cell: contactPhoneCell },
    ...($canManageJobs ? [{ id: 'actions', label: '', cell: contactActionsCell }] : []),
  ]);
</script>

<div class="activity">
  {#each sections as s (s.key)}
    {#if s.key === 'contacts'}
      <section data-section="contacts">
        <div class="section-head">
          <h3 class="section-title">Contacts</h3>
          <span class="hint">
            {#if $canManageJobs && onNewContact}
              <button type="button" class="action-link" onclick={onNewContact}>New contact</button>
            {/if}
          </span>
        </div>
        {#if contacts.length}
          <DataTable rows={contacts} key={(c) => c.contact_id} columns={contactColumns} />
        {:else}
          <p class="empty-box">No contacts yet.</p>
        {/if}
      </section>
    {:else if s.key === 'jobs'}
      <section data-section="jobs">
        <div class="section-head">
          <h3 class="section-title">Recent Jobs</h3>
          <span class="hint">
            {#if showLabel(jobSplit.closed.length, 'completed', expanded.jobs)}
              <button type="button" class="link-btn" onclick={() => { expanded.jobs = !expanded.jobs; }}>
                {showLabel(jobSplit.closed.length, 'completed', expanded.jobs)}
              </button>
            {/if}
          </span>
        </div>
        {#if jobRows.length}
          <DataTable rows={jobRows} key={(j) => j.job_id} columns={jobColumns} />
        {:else}
          <p class="empty-box">{s.total ? 'No open jobs.' : 'No jobs yet.'}</p>
        {/if}
      </section>
    {:else if s.key === 'invoices'}
      <section data-section="invoices">
        <div class="section-head">
          <h3 class="section-title">Open Invoices</h3>
          <span class="hint">
            {#if showLabel(invSplit.closed.length, 'paid', expanded.invoices)}
              <button type="button" class="link-btn" onclick={() => { expanded.invoices = !expanded.invoices; }}>
                {showLabel(invSplit.closed.length, 'paid', expanded.invoices)}
              </button>
            {/if}
          </span>
        </div>
        {#if invRows.length}
          <DataTable rows={invRows} key={(i) => i.invoice_id} columns={invoiceColumns} />
        {:else}
          <p class="empty-box">{s.total ? 'No open invoices.' : 'No invoices yet.'}</p>
        {/if}
      </section>
    {:else if s.key === 'pos'}
      <section data-section="pos">
        <div class="section-head">
          <h3 class="section-title">Purchase orders</h3>
          <span class="hint">
            {#if showLabel(poSplit.closed.length, 'closed', expanded.pos)}
              <button type="button" class="link-btn" onclick={() => { expanded.pos = !expanded.pos; }}>
                {showLabel(poSplit.closed.length, 'closed', expanded.pos)}
              </button>
            {/if}
            {#if $canManageFinancials && newPOHref}
              <a class="action-link" href={newPOHref}>New purchase order</a>
            {/if}
          </span>
        </div>
        {#if poRows.length}
          <DataTable rows={poRows} key={(p) => p.po_id} columns={poColumns} />
        {:else}
          <p class="empty-box">{s.total ? 'No open purchase orders.' : 'No purchase orders yet.'}</p>
        {/if}
      </section>
    {/if}
  {/each}

  <section class="panel history" data-section="history">
    <HistoryPanel {history} {onAddNote} />
  </section>
</div>

{#snippet jobNumberCell(job)}<a href="#/jobs/{job.job_id}">{jobNo(job.job_number)}</a>{/snippet}
{#snippet jobContactCell(job)}{#if job.contact}<a href="#/contacts/{job.contact}">{job.contact_name}</a>{/if}{/snippet}
{#snippet jobStatusCell(job)}<span class="status-badge status-{job.status}">{statusLabel(job.status)}</span>{/snippet}
{#snippet jobStartedCell(job)}<span class="date">{shortDate(job.start_date || job.created_date)}</span>{/snippet}
{#snippet jobEstimateCell(job)}{money(job.estimated_amount)}{/snippet}
{#snippet invNumberCell(inv)}<a href="#/invoices/{inv.invoice_id}">{inv.display_number}</a>{/snippet}
{#snippet invJobCell(inv)}<a href="#/jobs/{inv.job}">{jobNo(inv.job_number)}</a>{/snippet}
{#snippet invStatusCell(inv)}<span class="status-badge status-{inv.status}">{statusLabel(inv.status)}</span>{/snippet}
{#snippet invSentCell(inv)}<span class="date">{shortDate(inv.sent_date)}</span>{/snippet}
{#snippet invTotalCell(inv)}{money(inv.total)}{/snippet}
{#snippet invPaidCell(inv)}{money(inv.amount_paid)}{/snippet}
{#snippet invBalanceCell(inv)}{money(inv.balance)}{/snippet}
{#snippet poNumberCell(po)}<a href="#/purchase-orders/{po.po_id}">{po.po_number}</a>{/snippet}
{#snippet poStatusCell(po)}<span class="status-badge status-{po.status}">{statusLabel(po.status)}</span>{/snippet}
{#snippet poIssuedCell(po)}<span class="date">{shortDate(po.issued_date || po.created_date)}</span>{/snippet}
{#snippet contactNameCell(c)}
  <a href="#/contacts/{c.contact_id}">{c.name}</a>
  {#if c.contact_id === defaultContactId}<span class="chip-default">default</span>{/if}
{/snippet}
{#snippet contactEmailCell(c)}{#if c.email}<a href="mailto:{c.email}">{c.email}</a>{/if}{/snippet}
{#snippet contactPhoneCell(c)}{c.phone || '—'}{/snippet}
{#snippet contactActionsCell(c)}
  <span class="row-actions">
    {#if onNewJobFor}<button type="button" onclick={() => onNewJobFor(c.contact_id)}>New job</button>{/if}
    {#if onSetDefault}
      <button type="button" disabled={c.contact_id === defaultContactId}
        title={c.contact_id === defaultContactId ? 'Already the default' : undefined}
        onclick={() => onSetDefault(c.contact_id)}>Set as default</button>
    {/if}
  </span>
{/snippet}

<style>
  .activity { display: grid; gap: 18px; min-width: 0; }
  .section-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; }
  .section-head .hint { margin-left: auto; display: flex; gap: 12px; align-items: center; font-size: 12px; }
  .link-btn { background: none; border: 0; padding: 0; color: #2563eb; cursor: pointer; font: inherit; font-size: 12px; text-decoration: underline; }
  button.action-link { font: inherit; }
  /* What a section shows when nothing is on display (empty, or all rows
     hidden behind the toggle). Same box either way; the words differ. */
  .empty-box { margin: 0; border: 1.5px dashed #e2e8f0; border-radius: 8px; padding: 10px 16px; color: #94a3b8; font-size: 13px; }
  .date { white-space: nowrap; color: #64748b; }
  .chip-default {
    display: inline-block; margin-left: 6px; padding: 1px 8px; border-radius: 999px;
    font-size: 11px; font-weight: 600; background: #fde68a; color: #78350f;
  }
  /* The app-wide .status-badge is sized for pages; the dense table wants the
     job header's compact pill (sizing only — colors stay global). */
  .activity :global(.status-badge) { padding: 3px 10px; font-size: 12px; }
  .history :global(h3) { margin-top: 0; }
</style>
