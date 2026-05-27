<script>
  import { link, push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import COLineItemModal from '../../components/changeorders/COLineItemModal.svelte';
  import JobHeader from '../../components/jobs/JobHeader.svelte';

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
  // Pre-seed props for the modal
  let modalInitialAction = $state(null);
  let modalInitialTarget = $state(null);
  let modalInitialDescription = $state(null);
  let modalInitialQty = $state(null);
  let modalInitialUnits = $state(null);
  let modalInitialPrice = $state(null);

  let actionBusy = $state(false);

  const canManageJobs = $derived(
    $userStore?.permissions?.includes('can_manage_jobs') ?? false
  );

  let isDraft = $derived(co?.status === 'draft');
  let isOpen = $derived(co?.status === 'open');
  let isTerminal = $derived(['accepted', 'rejected'].includes(co?.status));

  // --------------------------------------------------------------------------
  // Merged diff: derive display rows from estimateLines ⊕ co.line_items
  // --------------------------------------------------------------------------

  /**
   * Each merged row has:
   *   kind:        'unchanged' | 'changed' | 'removed' | 'added' | 'changed-orig'
   *   lineNumber:  display line number
   *   description, qty, units, price, total: display values
   *   coItem:      the backing CO line item (for edit/delete/undo) — null for unchanged/changed-orig
   *   estLine:     the backing estimate line (null for 'added')
   */
  let mergedRows = $derived.by(() => {
    const coItems = (co?.line_items || []).slice().sort((a, b) => (a.line_number ?? 0) - (b.line_number ?? 0));
    const estLines = estimateLines.slice().sort((a, b) => a.line_number - b.line_number);

    // Build lookup: estimate line_item_id → CO item targeting it
    const replaceByCOTarget = new Map(); // target_line_item id → CO 'replace' item
    const removeByCOTarget  = new Map(); // target_line_item id → CO 'remove' item
    const addItems = [];

    for (const ci of coItems) {
      if (ci.action === 'replace' && ci.target_line_item) {
        replaceByCOTarget.set(ci.target_line_item, ci);
      } else if (ci.action === 'remove' && ci.target_line_item) {
        removeByCOTarget.set(ci.target_line_item, ci);
      } else if (ci.action === 'add') {
        addItems.push(ci);
      }
    }

    const rows = [];

    for (const el of estLines) {
      const replaceCI = replaceByCOTarget.get(el.line_item_id);
      const removeCI  = removeByCOTarget.get(el.line_item_id);

      if (replaceCI) {
        // changed: new value row (amber) + struck original row
        rows.push({
          kind: 'changed',
          lineNumber: el.line_number,
          description: replaceCI.description,
          qty: replaceCI.qty,
          units: replaceCI.units,
          price: replaceCI.price,
          total: Number(replaceCI.qty || 0) * Number(replaceCI.price || 0),
          coItem: replaceCI,
          estLine: el,
        });
        rows.push({
          kind: 'changed-orig',
          lineNumber: el.line_number,
          description: el.description,
          qty: el.qty,
          units: el.units,
          price: el.price,
          total: Number(el.qty || 0) * Number(el.price || 0),
          coItem: null,
          estLine: el,
        });
      } else if (removeCI) {
        // removed: struck alone, with Undo
        rows.push({
          kind: 'removed',
          lineNumber: el.line_number,
          description: el.description,
          qty: el.qty,
          units: el.units,
          price: el.price,
          total: Number(el.qty || 0) * Number(el.price || 0),
          coItem: removeCI,
          estLine: el,
        });
      } else {
        // unchanged
        rows.push({
          kind: 'unchanged',
          lineNumber: el.line_number,
          description: el.description,
          qty: el.qty,
          units: el.units,
          price: el.price,
          total: Number(el.qty || 0) * Number(el.price || 0),
          coItem: null,
          estLine: el,
        });
      }
    }

    // Appended added rows (sorted by their line_number)
    for (const ci of addItems) {
      rows.push({
        kind: 'added',
        lineNumber: ci.line_number,
        description: ci.description,
        qty: ci.qty,
        units: ci.units,
        price: ci.price,
        total: Number(ci.qty || 0) * Number(ci.price || 0),
        coItem: ci,
        estLine: null,
      });
    }

    return rows;
  });

  // Footer totals
  let estimateTotal = $derived(
    estimateLines.reduce((s, el) => s + Number(el.qty || 0) * Number(el.price || 0), 0)
  );
  let proposedTotal = $derived(
    mergedRows
      .filter(r => r.kind === 'unchanged' || r.kind === 'changed' || r.kind === 'added')
      .reduce((s, r) => s + r.total, 0)
  );
  let diffTotal = $derived(proposedTotal - estimateTotal);

  // --------------------------------------------------------------------------

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
      await api.post(`/api/change-orders/${co.change_order_id}/mark-open/`);
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
      await api.patch(`/api/change-orders/${co.change_order_id}/`, { status: newStatus });
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
      await api.delete(`/api/change-orders/${co.change_order_id}/`);
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
      const newCo = await api.post(`/api/change-orders/${co.change_order_id}/seed-new/`);
      window.location.hash = `/change-orders/${newCo.change_order_id}`;
    } catch (e) {
      alert(e.message || 'Could not create new change order.');
      actionBusy = false;
    }
  }

  // --------------------------------------------------------------------------
  // Diff-editor actions
  // --------------------------------------------------------------------------

  /** Unchanged estimate line → [Change]: open modal pre-set to 'replace' with prefill */
  function openChangeEstimateLine(estLine) {
    modalMode = 'create';
    modalItem = null;
    modalInitialAction = 'replace';
    modalInitialTarget = estLine.line_item_id;
    modalInitialDescription = estLine.description;
    modalInitialQty = estLine.qty ?? '';
    modalInitialUnits = estLine.units ?? 'none';
    modalInitialPrice = estLine.price ?? '';
    modalOpen = true;
  }

  /** Unchanged estimate line → [Delete]: POST a 'remove' CO line item, no modal */
  async function removeEstimateLine(estLine) {
    if (!confirm(`Remove line ${estLine.line_number} "${estLine.description}" from this change order?`)) return;
    try {
      await api.post(`/api/change-orders/${co.change_order_id}/line-items/`, {
        action: 'remove',
        target_line_item: estLine.line_item_id,
      });
      await loadCO();
    } catch (e) {
      alert(e.message || 'Could not remove estimate line.');
    }
  }

  /** Changed row (replace CO line) → [Edit]: open modal to PATCH the existing CO line */
  function openEditCOLine(coItem) {
    modalMode = 'edit';
    modalItem = coItem;
    modalInitialAction = null;
    modalInitialTarget = null;
    modalInitialDescription = null;
    modalInitialQty = null;
    modalInitialUnits = null;
    modalInitialPrice = null;
    modalOpen = true;
  }

  /** Changed or removed row → [Undo]: DELETE the CO line item (reverts to unchanged) */
  async function undoCOLine(coItem) {
    if (!confirm('Undo this change? The line will revert to its original estimate value.')) return;
    try {
      await api.delete(`/api/change-orders/${co.change_order_id}/line-items/${coItem.line_item_id}/`);
      await loadCO();
    } catch (e) {
      alert(e.message || 'Could not undo change.');
    }
  }

  /** Added row → [Delete]: DELETE the CO line item */
  async function deleteAddedLine(coItem) {
    if (!confirm('Delete this added line?')) return;
    try {
      await api.delete(`/api/change-orders/${co.change_order_id}/line-items/${coItem.line_item_id}/`);
      await loadCO();
    } catch (e) {
      alert(e.message || 'Could not delete line item.');
    }
  }

  /** [+ New line] button → add mode */
  function openAddItem() {
    modalMode = 'create';
    modalItem = null;
    modalInitialAction = 'add';
    modalInitialTarget = null;
    modalInitialDescription = null;
    modalInitialQty = null;
    modalInitialUnits = null;
    modalInitialPrice = null;
    modalOpen = true;
  }

  function handleSaved() {
    modalOpen = false;
    modalItem = null;
    loadCO();
  }

  // --------------------------------------------------------------------------

  function fmtMoney(n) { return `$${Number(n ?? 0).toFixed(2)}`; }
  function fmtDiff(n) {
    const v = Number(n ?? 0);
    if (v === 0) return '$0.00';
    return (v > 0 ? '+' : '') + `$${Math.abs(v).toFixed(2)}`;
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
  {#if job}
    <JobHeader {job} {contact} onStatusChange={loadCO} />
  {/if}

  <!-- CO toolbar -->
  <div class="toolbar">
    <a href={`/jobs/${co.job}`} use:link class="back-link">&laquo; back to job{job ? ` ${job.job_number}` : ''}</a>
    <span class="page-title">{co.change_order_number || `CO #${co.change_order_id}`}</span>
    <span class="status-badge status-co-{co.status}">{co.status}</span>
    {#if canManageJobs}
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
    {/if}
  </div>

  <!-- Line items: merged diff editor -->
  <section class="section">
    <div class="section-head">
      <h3>Line items</h3>
      <span class="spacer"></span>
      {#if canManageJobs && isDraft}
        <button type="button" onclick={openAddItem}>+ New line</button>
      {/if}
    </div>

    <table class="diff-table">
      <colgroup>
        <col style="width:30px">
        <col>
        <col style="width:50px">
        <col style="width:50px">
        <col style="width:75px">
        <col style="width:80px">
        <col style="width:150px">
      </colgroup>
      <thead>
        <tr>
          <th>#</th>
          <th>Description</th>
          <th class="num">Qty</th>
          <th>Units</th>
          <th class="num">Price</th>
          <th class="num">Total</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {#if mergedRows.length === 0 && estimateLines.length === 0}
          <tr>
            <td colspan="7" class="empty-msg">No estimate lines or CO lines yet.</td>
          </tr>
        {:else}
          {#each mergedRows as row}
            {#if row.kind === 'unchanged'}
              <tr>
                <td>{row.lineNumber}</td>
                <td>{row.description || '—'}</td>
                <td class="num">{row.qty ?? '—'}</td>
                <td>{row.units || '—'}</td>
                <td class="num">{fmtMoney(row.price)}</td>
                <td class="num">{fmtMoney(row.total)}</td>
                <td class="acts">
                  {#if canManageJobs && isDraft}
                    <button type="button" onclick={() => openChangeEstimateLine(row.estLine)}>Change</button>
                    <button type="button" onclick={() => removeEstimateLine(row.estLine)}>Delete</button>
                  {/if}
                </td>
              </tr>
            {:else if row.kind === 'changed'}
              <tr class="row-changed">
                <td>{row.lineNumber}</td>
                <td>{row.description || '—'}</td>
                <td class="num">{row.qty ?? '—'}</td>
                <td>{row.units || '—'}</td>
                <td class="num">{fmtMoney(row.price)}</td>
                <td class="num">{fmtMoney(row.total)}</td>
                <td class="acts">
                  {#if canManageJobs && isDraft}
                    <button type="button" onclick={() => openEditCOLine(row.coItem)}>Edit</button>
                    <button type="button" onclick={() => undoCOLine(row.coItem)}>Undo</button>
                  {/if}
                </td>
              </tr>
            {:else if row.kind === 'changed-orig'}
              <tr class="row-gone">
                <td class="keep">{row.lineNumber}</td>
                <td>{row.description || '—'}</td>
                <td class="num">{row.qty ?? '—'}</td>
                <td>{row.units || '—'}</td>
                <td class="num">{fmtMoney(row.price)}</td>
                <td class="num">{fmtMoney(row.total)}</td>
                <td></td>
              </tr>
            {:else if row.kind === 'removed'}
              <tr class="row-gone">
                <td class="keep">{row.lineNumber}</td>
                <td>{row.description || '—'}</td>
                <td class="num">{row.qty ?? '—'}</td>
                <td>{row.units || '—'}</td>
                <td class="num">{fmtMoney(row.price)}</td>
                <td class="num">{fmtMoney(row.total)}</td>
                <td class="acts keep">
                  {#if canManageJobs && isDraft}
                    <button type="button" onclick={() => undoCOLine(row.coItem)}>Undo</button>
                  {/if}
                </td>
              </tr>
            {:else if row.kind === 'added'}
              <tr class="row-added">
                <td>{row.lineNumber}</td>
                <td><span class="added-tag">+</span>{row.description || '—'}</td>
                <td class="num">{row.qty ?? '—'}</td>
                <td>{row.units || '—'}</td>
                <td class="num">{fmtMoney(row.price)}</td>
                <td class="num">{fmtMoney(row.total)}</td>
                <td class="acts">
                  {#if canManageJobs && isDraft}
                    <button type="button" onclick={() => openEditCOLine(row.coItem)}>Edit</button>
                    <button type="button" onclick={() => deleteAddedLine(row.coItem)}>Delete</button>
                  {/if}
                </td>
              </tr>
            {/if}
          {/each}
        {/if}
      </tbody>
      <tfoot>
        <tr>
          <td colspan="5" class="num footer-left">
            Estimate <span class="est-struck">{fmtMoney(estimateTotal)}</span>
            &rarr; <strong>proposed {fmtMoney(proposedTotal)}</strong>
          </td>
          <td class="num footer-diff">{fmtDiff(diffTotal)}</td>
          <td></td>
        </tr>
      </tfoot>
    </table>
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
    coId={co.change_order_id}
    item={modalItem}
    {estimateLines}
    initialAction={modalInitialAction}
    initialTarget={modalInitialTarget}
    initialDescription={modalInitialDescription}
    initialQty={modalInitialQty}
    initialUnits={modalInitialUnits}
    initialPrice={modalInitialPrice}
    onSaved={handleSaved}
    onClose={() => { modalOpen = false; }}
  />
{/if}

<style>
  .error { color: #a8071a; padding: 16px; }

  .toolbar {
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
    padding: 8px 24px;
  }
  .back-link { font-size: 13px; }
  .page-title { font-size: 18px; font-weight: 600; }

  .status-badge {
    padding: 4px 12px; border-radius: 12px; font-size: 13px; font-weight: 600; text-transform: capitalize;
  }
  .status-co-draft { background: #f3f4f6; color: #374151; }
  .status-co-open { background: #fef3c7; color: #92400e; }
  .status-co-accepted { background: #dcfce7; color: #166534; }
  .status-co-rejected { background: #fee2e2; color: #991b1b; }

  .btn-danger { background: #fee2e2; color: #991b1b; border-color: #fca5a5; }
  .btn-danger:hover { background: #fecaca; }
  .btn-accept { background: #dcfce7; color: #166534; border-color: #86efac; }
  .btn-accept:hover { background: #bbf7d0; }

  .section { padding: 16px 24px; }
  .section-head {
    display: flex; align-items: center; gap: 12px; margin-bottom: 8px;
  }
  .section-head h3 { margin: 0; }
  .spacer { flex: 1; }
  .section-desc { font-size: 13px; color: #666; margin: 0 0 10px; }

  /* ---- Merged diff table ---- */
  .diff-table {
    width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 13px;
  }
  .diff-table th {
    text-align: left; color: #6b7280; font-size: 12px; font-weight: 600;
    padding: 5px 8px; border-bottom: 1px solid #e5e7eb;
  }
  .diff-table td { padding: 6px 8px; vertical-align: middle; }
  .diff-table tbody tr { border-bottom: 1px solid #f3f4f6; }

  .diff-table .num { text-align: right; font-variant-numeric: tabular-nums; }
  .diff-table .acts { text-align: right; white-space: nowrap; }
  .diff-table .acts button { margin-left: 4px; }

  /* Row tints */
  .diff-table tr.row-changed { background: #fff7ed; }
  .diff-table tr.row-added   { background: #dcfce7; }
  .diff-table tr.row-gone td { color: #9ca3af; text-decoration: line-through; }
  /* line-number cell in gone rows: no strikethrough, keep muted colour */
  .diff-table tr.row-gone td.keep { text-decoration: none; color: #9ca3af; }
  /* acts cell in gone rows: no strikethrough */
  .diff-table tr.row-gone td.acts.keep { text-decoration: none; }

  .added-tag { color: #166534; font-weight: 600; margin-right: 5px; }

  /* Footer */
  .diff-table tfoot td { padding: 8px; border-top: 2px solid #e5e7eb; font-size: 13px; }
  .footer-left { color: #6b7280; }
  .est-struck { text-decoration: line-through; }
  .footer-diff { font-weight: 700; }

  .empty-msg { color: #888; font-size: 13px; padding: 8px 0; }

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
