<script>
  import { link, push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import COLineItemModal from '../../components/changeorders/COLineItemModal.svelte';

  let { params = {} } = $props();

  let co = $state(null);
  let job = $state(null);
  let contact = $state(null);
  let estimateLines = $state([]);  // lines from the accepted estimate for target picking
  let agreementLines = $state([]);
  let agreementTotal = $state(null);
  let loading = $state(true);
  let error = $state('');

  let modalOpen = $state(false);
  let modalMode = $state('create');
  let modalItem = $state(null);

  let actionBusy = $state(false);

  const canManageJobs = $derived(
    $userStore?.permissions?.includes('can_manage_jobs') ?? false
  );

  let isDraft = $derived(co?.status === 'draft');
  let isOpen = $derived(co?.status === 'open');
  let isTerminal = $derived(['accepted', 'rejected'].includes(co?.status));

  let sortedLineItems = $derived(
    (co?.line_items || []).slice().sort((a, b) => (a.line_number ?? 0) - (b.line_number ?? 0))
  );

  async function loadCO() {
    loading = true;
    error = '';
    try {
      co = await api.get(`/api/change-orders/${params.id}/`);
      if (co?.job) {
        try {
          job = await api.get(`/api/jobs/${co.job}/`);
          if (job?.contact) {
            try { contact = await api.get(`/api/contacts/${job.contact}/`); } catch (_) { contact = null; }
          }
          // Load agreement-of-record
          try {
            const agr = await api.get(`/api/jobs/${co.job}/agreement/`);
            agreementLines = agr.lines || [];
            agreementTotal = agr.grand_total ?? null;
          } catch (_) {
            agreementLines = [];
            agreementTotal = null;
          }
          // Load estimate lines for target picking (from accepted estimates)
          try {
            const estResp = await api.get(`/api/estimates/?job=${co.job}`);
            const estList = estResp?.results || estResp || [];
            // Use accepted or the most recent non-superseded estimate for target picking
            const accepted = estList.find(e => e.status === 'accepted');
            const source = accepted || estList.findLast(e => e.status !== 'superseded') || estList[estList.length - 1];
            if (source?.estimate_id) {
              const est = await api.get(`/api/estimates/${source.estimate_id}/`);
              estimateLines = (est.line_items || []).slice().sort((a, b) => a.line_number - b.line_number);
            }
          } catch (_) {
            estimateLines = [];
          }
        } catch (_) {
          job = null;
        }
      }
    } catch (e) {
      error = e.message || 'Could not load change order.';
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (params.id) loadCO();
  });

  // Status actions
  async function markOpen() {
    if (!confirm('Mark this change order as sent? This will lock line items.')) return;
    actionBusy = true;
    try {
      await api.post(`/api/change-orders/${co.id}/mark-open/`);
      await loadCO();
    } catch (e) {
      alert(e.message || 'Could not mark as sent.');
    } finally {
      actionBusy = false;
    }
  }

  async function handleStatusChange(newStatus) {
    const labels = { accepted: 'Accept', rejected: 'Reject' };
    const label = labels[newStatus] || newStatus;
    if (!confirm(`${label} this change order?${newStatus === 'accepted' ? ' This will advance the job back to in_progress.' : ''}`)) return;
    actionBusy = true;
    try {
      await api.patch(`/api/change-orders/${co.id}/`, { status: newStatus });
      await loadCO();
    } catch (e) {
      alert(e.message || 'Could not update status.');
    } finally {
      actionBusy = false;
    }
  }

  async function discard() {
    if (!confirm('Discard this change order? This cannot be undone.')) return;
    actionBusy = true;
    try {
      await api.delete(`/api/change-orders/${co.id}/`);
      window.location.hash = `/jobs/${co.job}`;
    } catch (e) {
      alert(e.message || 'Could not discard change order.');
      actionBusy = false;
    }
  }

  async function seedNew() {
    if (!confirm('Start a new change order for this job? A new draft will be created.')) return;
    actionBusy = true;
    try {
      const newCo = await api.post(`/api/change-orders/${co.id}/seed-new/`);
      window.location.hash = `/change-orders/${newCo.id}`;
    } catch (e) {
      alert(e.message || 'Could not create new change order.');
      actionBusy = false;
    }
  }

  // Line item editing
  function openAddItem() {
    modalItem = null;
    modalMode = 'create';
    modalOpen = true;
  }

  function openEditItem(li) {
    modalItem = li;
    modalMode = 'edit';
    modalOpen = true;
  }

  function handleSaved() {
    modalOpen = false;
    modalItem = null;
    loadCO();
  }

  async function handleDeleteItem(li) {
    if (!confirm(`Delete this line item?`)) return;
    try {
      await api.delete(`/api/change-orders/${co.id}/line-items/${li.id}/`);
      await loadCO();
    } catch (e) {
      alert(e.message || 'Could not delete line item.');
    }
  }

  async function handleReorder(itemIds) {
    try {
      await api.post(`/api/change-orders/${co.id}/line-items/reorder/`, { item_ids: itemIds });
      await loadCO();
    } catch (e) {
      alert(e.message || 'Could not reorder.');
    }
  }

  function moveUp(index) {
    if (index === 0) return;
    const ids = sortedLineItems.map(li => li.id);
    [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]];
    handleReorder(ids);
  }

  function moveDown(index) {
    if (index >= sortedLineItems.length - 1) return;
    const ids = sortedLineItems.map(li => li.id);
    [ids[index], ids[index + 1]] = [ids[index + 1], ids[index]];
    handleReorder(ids);
  }

  function fmtMoney(n) { return `$${Number(n ?? 0).toFixed(2)}`; }
  function lineTotal(li) { return Number(li.qty || 0) * Number(li.price || 0); }

  function actionBadgeClass(action) {
    if (action === 'add') return 'action-add';
    if (action === 'remove') return 'action-remove';
    if (action === 'replace') return 'action-replace';
    return '';
  }

  function originLabel(origin) {
    if (!origin) return '';
    if (origin === 'original') return 'Original';
    if (origin === 'change_order') return 'Change Order';
    return origin;
  }
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p class="error">{error}</p>
{:else if co}
  <!-- Header / toolbar -->
  <div class="co-header">
    <div class="co-header-left">
      <a href={`/jobs/${co.job}`} use:link class="back-link">&laquo; back to job{job ? ` ${job.job_number}` : ''}</a>
      <h2 class="co-number">{co.co_number || `CO #${co.id}`}</h2>
      {#if job}
        <span class="co-job-ref">
          for <a href={`/jobs/${co.job}`} use:link>{job.job_number}{job.name ? `: ${job.name}` : ''}</a>
          {#if contact} · <a href={`/contacts/${contact.contact_id}`} use:link>{contact.name}</a>{/if}
        </span>
      {/if}
    </div>
    <div class="co-header-right">
      <span class="status-badge status-co-{co.status}">{co.status}</span>
    </div>
  </div>

  <!-- Action bar -->
  {#if canManageJobs}
    <div class="action-bar">
      {#if isDraft}
        <button type="button" onclick={markOpen} disabled={actionBusy}>
          {actionBusy ? 'Saving…' : 'Mark as Sent'}
        </button>
        <button type="button" class="btn-danger" onclick={discard} disabled={actionBusy}>
          Discard
        </button>
      {:else if isOpen}
        <button type="button" class="btn-accept" onclick={() => handleStatusChange('accepted')} disabled={actionBusy}>
          {actionBusy ? 'Saving…' : 'Record Accepted'}
        </button>
        <button type="button" class="btn-danger" onclick={() => handleStatusChange('rejected')} disabled={actionBusy}>
          {actionBusy ? 'Saving…' : 'Record Rejected'}
        </button>
      {:else if isTerminal}
        <button type="button" onclick={seedNew} disabled={actionBusy}>
          {actionBusy ? 'Creating…' : 'Start new change order'}
        </button>
      {/if}
    </div>
  {/if}

  <!-- Line items (editable when draft) -->
  <section class="section">
    <div class="section-head">
      <h3>Line Items</h3>
      {#if canManageJobs && isDraft}
        <button type="button" onclick={openAddItem}>Add Line Item</button>
      {/if}
    </div>

    {#if sortedLineItems.length > 0}
      <table class="co-lines-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Action</th>
            <th>Target line</th>
            <th>Description</th>
            <th class="text-right">Qty</th>
            <th>Units</th>
            <th class="text-right">Price</th>
            <th class="text-right">Total</th>
            {#if canManageJobs && isDraft}<th>Actions</th>{/if}
          </tr>
        </thead>
        <tbody>
          {#each sortedLineItems as li, i}
            <tr>
              <td>{li.line_number}</td>
              <td><span class="action-badge {actionBadgeClass(li.action)}">{li.action}</span></td>
              <td class="target-col">
                {#if li.target_line_item}
                  {#if li.target_description}
                    <span class="target-desc">#{li.target_line_number ?? li.target_line_item}: {li.target_description}</span>
                  {:else}
                    <span class="target-desc">Line #{li.target_line_item}</span>
                  {/if}
                {:else}
                  <span class="dim">—</span>
                {/if}
              </td>
              <td>{li.description || '—'}</td>
              <td class="text-right">{li.action !== 'remove' ? (li.qty ?? '—') : '—'}</td>
              <td>{li.action !== 'remove' ? (li.units || '—') : '—'}</td>
              <td class="text-right">{li.action !== 'remove' ? fmtMoney(li.price) : '—'}</td>
              <td class="text-right">{li.action !== 'remove' ? fmtMoney(lineTotal(li)) : '—'}</td>
              {#if canManageJobs && isDraft}
                <td class="actions-cell">
                  <button type="button" onclick={() => openEditItem(li)}>Edit</button>
                  <button type="button" onclick={() => moveUp(i)} disabled={i === 0}>&#9650;</button>
                  <button type="button" onclick={() => moveDown(i)} disabled={i >= sortedLineItems.length - 1}>&#9660;</button>
                  <button type="button" onclick={() => handleDeleteItem(li)}>Delete</button>
                </td>
              {/if}
            </tr>
          {/each}
        </tbody>
        {#if sortedLineItems.filter(li => li.action !== 'remove').length > 0}
          {@const addTotal = sortedLineItems
            .filter(li => li.action !== 'remove')
            .reduce((s, li) => s + lineTotal(li), 0)}
          <tfoot>
            <tr>
              <td colspan={canManageJobs && isDraft ? 7 : 7} style="text-align:right"><strong>Subtotal (additions/replacements):</strong></td>
              <td class="text-right"><strong>{fmtMoney(addTotal)}</strong></td>
              {#if canManageJobs && isDraft}<td></td>{/if}
            </tr>
          </tfoot>
        {/if}
      </table>
    {:else}
      <p class="empty-msg">No line items on this change order yet.</p>
    {/if}
  </section>

  <!-- Agreement of record -->
  <section class="section">
    <h3>Agreement of Record</h3>
    <p class="section-desc">The full scope of work as currently agreed — original estimate lines plus any accepted change orders.</p>

    {#if agreementLines.length > 0}
      <table class="agreement-table">
        <thead>
          <tr>
            <th>Description</th>
            <th class="text-right">Qty</th>
            <th>Units</th>
            <th class="text-right">Price</th>
            <th class="text-right">Amount</th>
            <th>Origin</th>
          </tr>
        </thead>
        <tbody>
          {#each agreementLines as line}
            <tr class="origin-{line.origin}">
              <td>{line.description || '—'}</td>
              <td class="text-right">{line.qty ?? '—'}</td>
              <td>{line.units || '—'}</td>
              <td class="text-right">{fmtMoney(line.price)}</td>
              <td class="text-right">{fmtMoney(line.amount)}</td>
              <td><span class="origin-badge origin-{line.origin}">{originLabel(line.origin)}</span></td>
            </tr>
          {/each}
        </tbody>
        <tfoot>
          <tr class="grand-total-row">
            <td colspan="4" style="text-align:right"><strong>Grand Total:</strong></td>
            <td class="text-right"><strong>{fmtMoney(agreementTotal)}</strong></td>
            <td></td>
          </tr>
        </tfoot>
      </table>
    {:else}
      <p class="empty-msg">No agreement data available.</p>
    {/if}
  </section>

  <COLineItemModal
    open={modalOpen}
    mode={modalMode}
    coId={co.id}
    item={modalItem}
    {estimateLines}
    onSaved={handleSaved}
    onClose={() => { modalOpen = false; }}
  />
{/if}

<style>
  .error { color: #a8071a; padding: 16px; }

  .co-header {
    display: flex; justify-content: space-between; align-items: flex-start;
    padding: 16px 24px; background: #1f2937; color: #fff;
  }
  .co-header-left { display: flex; flex-direction: column; gap: 4px; }
  .co-header-right { display: flex; align-items: center; }
  .back-link { font-size: 13px; color: rgba(255,255,255,0.7); text-decoration: none; }
  .back-link:hover { color: #fff; text-decoration: underline; }
  .co-number { margin: 0; font-size: 22px; font-weight: 700; color: #fff; }
  .co-job-ref { font-size: 13px; color: rgba(255,255,255,0.8); }
  .co-job-ref a { color: #fff; text-decoration: underline; }

  .status-badge {
    padding: 4px 14px; border-radius: 12px; font-size: 13px; font-weight: 600; text-transform: capitalize;
  }
  .status-co-draft { background: #f3f4f6; color: #374151; }
  .status-co-open { background: #fef3c7; color: #92400e; }
  .status-co-accepted { background: #dcfce7; color: #166534; }
  .status-co-rejected { background: #fee2e2; color: #991b1b; }

  .action-bar {
    display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
    padding: 10px 24px; background: #f3f4f6; border-bottom: 1px solid #e5e7eb;
  }
  .btn-danger { background: #fee2e2; color: #991b1b; border-color: #fca5a5; }
  .btn-danger:hover { background: #fecaca; }
  .btn-accept { background: #dcfce7; color: #166534; border-color: #86efac; }
  .btn-accept:hover { background: #bbf7d0; }

  .section { padding: 16px 24px; }
  .section-head { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
  .section-head h3 { margin: 0; }
  .section-desc { font-size: 13px; color: #666; margin: 0 0 10px; }

  .co-lines-table { width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 8px; }
  .co-lines-table th { padding: 8px 10px; text-align: left; background: #fee2e2; color: #7f1d1d; font-weight: 600; border-bottom: 2px solid #fca5a5; }
  .co-lines-table td { padding: 7px 10px; border-bottom: 1px solid #fee2e2; vertical-align: top; }
  .co-lines-table .text-right { text-align: right; font-variant-numeric: tabular-nums; }
  .co-lines-table tfoot td { padding: 8px 10px; background: #f9fafb; }
  .actions-cell { white-space: nowrap; }
  .actions-cell button { margin-right: 3px; }
  .target-col { font-size: 13px; }
  .target-desc { color: #555; }
  .dim { color: #aaa; }

  .action-badge {
    display: inline-block; padding: 1px 8px; border-radius: 8px;
    font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.3px;
  }
  .action-add { background: #dcfce7; color: #166534; }
  .action-remove { background: #fee2e2; color: #991b1b; }
  .action-replace { background: #fef3c7; color: #92400e; }

  .empty-msg { color: #888; font-size: 14px; padding: 8px 0; }

  /* Agreement-of-record table */
  .agreement-table { width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 8px; }
  .agreement-table th {
    padding: 8px 10px; text-align: left; font-weight: 600;
    background: #e0e7ff; color: #3730a3; border-bottom: 2px solid #c7d2fe;
  }
  .agreement-table td { padding: 7px 10px; border-bottom: 1px solid #e0e7ff; vertical-align: top; }
  .agreement-table .text-right { text-align: right; font-variant-numeric: tabular-nums; }
  .agreement-table tfoot td { padding: 8px 10px; background: #eef2ff; }
  .grand-total-row td { font-size: 15px; }

  .agreement-table tr.origin-change_order td { background: #fefce8; }
  .agreement-table tr.origin-original td { background: #fff; }

  .origin-badge {
    display: inline-block; padding: 1px 8px; border-radius: 8px;
    font-size: 11px; font-weight: 500;
  }
  .origin-original { background: #f3f4f6; color: #374151; }
  .origin-change_order { background: #fef3c7; color: #92400e; }
</style>
