<script>
  import { link, push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { canManageJobs as canManageJobsStore } from '../../stores/permissions.js';
  import COLineItemModal from '../../components/changeorders/COLineItemModal.svelte';
  import JobHeader from '../../components/jobs/JobHeader.svelte';
  import UnitsSelect from '../../components/UnitsSelect.svelte';

  let { params = {} } = $props();

  let co = $state(null);
  let job = $state(null);
  let contact = $state(null);
  let estimateLines = $state([]);  // lines from the accepted estimate for target picking
  let siblingCOs = $state([]);     // all COs for this job (used for display-status relabelling)
  let loading = $state(true);
  let error = $state('');

  // Deliverables diff state
  let liveDeliverables = $state([]);
  let delivBaseline = $state([]);
  // Inline edit form state: deliverable id currently being edited, or null
  let delivEditId = $state(null);
  let delivEditDescription = $state('');
  let delivEditQty = $state('');
  let delivEditUnits = $state('ea');
  // New deliverable form
  let delivNewOpen = $state(false);
  let delivNewDescription = $state('');
  let delivNewQty = $state('1');
  let delivNewUnits = $state('ea');
  let delivSaving = $state(false);

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

  // Save button transient state
  let saveLabel = $state('Save');

  const canManageJobs = $derived($canManageJobsStore);

  let isDraft = $derived(co?.status === 'draft');
  let isOpen = $derived(co?.status === 'open');
  let isTerminal = $derived(['accepted', 'rejected'].includes(co?.status));

  // --------------------------------------------------------------------------
  // Merged diff: derive display rows from estimateLines ⊕ co.line_items
  //
  // Ordering is intentional and fixed — no reordering allowed:
  //   1. Estimate lines in line_number order; each replacement appears directly
  //      above its struck replacee at the same line_number position.
  //   2. Added (new) lines appended after all estimate lines, sorted by their
  //      own line_number.
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
          // Load all COs for the job (for display-status relabelling)
          try {
            const cosResp = await api.get(`/api/change-orders/?job=${co.job}`);
            siblingCOs = cosResp?.results || cosResp || [];
          } catch (_) {
            siblingCOs = [];
          }
          // Load live deliverables + baseline snapshot
          try {
            const [liveDel, baselineResp] = await Promise.all([
              api.get(`/api/jobs/${co.job}/deliverables/`),
              api.get(`/api/change-orders/${params.id}/deliverables-baseline/`),
            ]);
            liveDeliverables = liveDel || [];
            delivBaseline = baselineResp?.baseline || [];
          } catch (_) {
            liveDeliverables = [];
            delivBaseline = [];
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

  // --------------------------------------------------------------------------
  // Deliverables diff
  // --------------------------------------------------------------------------

  /**
   * Each deliverable merged row has:
   *   kind:        'unchanged' | 'changed' | 'changed-orig' | 'removed' | 'added'
   *   live:        the live Deliverable object (null for removed/changed-orig)
   *   baseline:    the DeliverableSnapshot baseline row (null for added)
   *   anchored:    boolean — live deliverable has qty_picked_up > 0 or qty_prepped > 0
   *   description, qty, units: display values
   */
  let delivMergedRows = $derived.by(() => {
    const live = (liveDeliverables || []).slice().sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
    const base = (delivBaseline || []).slice().sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));

    // Map: live deliverable id → live deliverable object
    const liveById = new Map(live.map(d => [d.id, d]));
    // Set of live ids that are referenced by any baseline row
    const baselinedLiveIds = new Set(base.map(b => b.source_deliverable).filter(Boolean));

    const rows = [];

    for (const snap of base) {
      const liveRow = snap.source_deliverable ? liveById.get(snap.source_deliverable) : null;
      if (!liveRow) {
        // source was deleted → removed
        rows.push({
          kind: 'removed',
          live: null,
          baseline: snap,
          anchored: false,
          description: snap.description,
          qty: snap.qty_ordered,
          units: snap.units,
        });
      } else {
        const anchored = Number(liveRow.qty_picked_up ?? 0) > 0 || Number(liveRow.qty_prepped ?? 0) > 0;
        const changed =
          liveRow.description !== snap.description ||
          String(Number(liveRow.qty_ordered)) !== String(Number(snap.qty_ordered)) ||
          liveRow.units !== snap.units;
        if (changed) {
          // changed: new-value row (amber) + struck original row beneath
          rows.push({
            kind: 'changed',
            live: liveRow,
            baseline: snap,
            anchored,
            description: liveRow.description,
            qty: liveRow.qty_ordered,
            units: liveRow.units,
          });
          rows.push({
            kind: 'changed-orig',
            live: null,
            baseline: snap,
            anchored: false,
            description: snap.description,
            qty: snap.qty_ordered,
            units: snap.units,
          });
        } else {
          rows.push({
            kind: 'unchanged',
            live: liveRow,
            baseline: snap,
            anchored,
            description: liveRow.description,
            qty: liveRow.qty_ordered,
            units: liveRow.units,
          });
        }
      }
    }

    // Added: live deliverables not referenced by any baseline row
    for (const d of live) {
      if (!baselinedLiveIds.has(d.id)) {
        const anchored = Number(d.qty_picked_up ?? 0) > 0 || Number(d.qty_prepped ?? 0) > 0;
        rows.push({
          kind: 'added',
          live: d,
          baseline: null,
          anchored,
          description: d.description,
          qty: d.qty_ordered,
          units: d.units,
        });
      }
    }

    return rows;
  });

  function fmtQty(v) {
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v);
    return Number.isFinite(n) ? n.toString() : String(v);
  }

  // Open inline edit for a live deliverable
  function openDelivEdit(liveRow) {
    delivEditId = liveRow.id;
    delivEditDescription = liveRow.description;
    delivEditQty = String(Number(liveRow.qty_ordered));
    delivEditUnits = liveRow.units;
  }

  function cancelDelivEdit() {
    delivEditId = null;
  }

  async function saveDelivEdit(liveId) {
    delivSaving = true;
    try {
      await api.patch(`/api/jobs/${co.job}/deliverables/${liveId}/`, {
        description: delivEditDescription,
        qty_ordered: delivEditQty,
        units: delivEditUnits,
      });
      delivEditId = null;
      await loadCO();
    } catch (e) {
      alert(e.message || 'Could not save deliverable.');
    } finally {
      delivSaving = false;
    }
  }

  async function deleteDeliverable(liveId) {
    try {
      await api.delete(`/api/jobs/${co.job}/deliverables/${liveId}/`);
      await loadCO();
    } catch (e) {
      alert(e.message || 'Could not delete deliverable.');
    }
  }

  /** Undo a changed deliverable: PATCH live back to baseline values */
  async function undoDelivChange(liveId, snap) {
    try {
      await api.patch(`/api/jobs/${co.job}/deliverables/${liveId}/`, {
        description: snap.description,
        qty_ordered: snap.qty_ordered,
        units: snap.units,
      });
      await loadCO();
    } catch (e) {
      alert(e.message || 'Could not undo change.');
    }
  }

  /** Undo a removed deliverable: POST a new live deliverable with baseline values */
  async function undoDelivRemove(snap) {
    try {
      await api.post(`/api/jobs/${co.job}/deliverables/`, {
        description: snap.description,
        qty_ordered: snap.qty_ordered,
        units: snap.units,
      });
      await loadCO();
    } catch (e) {
      alert(e.message || 'Could not restore deliverable.');
    }
  }

  function openDelivNew() {
    delivNewDescription = '';
    delivNewQty = '1';
    delivNewUnits = 'ea';
    delivNewOpen = true;
  }

  function cancelDelivNew() {
    delivNewOpen = false;
  }

  async function saveDelivNew() {
    if (!delivNewDescription.trim()) { alert('Description is required.'); return; }
    delivSaving = true;
    try {
      await api.post(`/api/jobs/${co.job}/deliverables/`, {
        description: delivNewDescription,
        qty_ordered: delivNewQty,
        units: delivNewUnits,
      });
      delivNewOpen = false;
      await loadCO();
    } catch (e) {
      alert(e.message || 'Could not add deliverable.');
    } finally {
      delivSaving = false;
    }
  }

  // Keyboard handler for deliverable inline-edit rows (Enter = save, Esc = cancel)
  function delivEditKeydown(event, saveHandler, cancelHandler) {
    if (event.key === 'Enter') {
      event.preventDefault();
      saveHandler();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      cancelHandler();
    }
  }

  // --------------------------------------------------------------------------

  // Status actions
  async function handleStatusChange(newStatus) {
    const labels = { accepted: 'Accept', rejected: 'Reject' };
    const label = labels[newStatus] || newStatus;
    if (!confirm(`${label} this change order?${newStatus === 'accepted' ? ' This will move the job to approved so you can verify the details before releasing it to the floor.' : ''}`)) return;
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
    // No confirm: the new draft CO is trivially discardable.
    actionBusy = true;
    try {
      const newCo = await api.post(`/api/change-orders/${co.change_order_id}/seed-new/`);
      window.location.hash = `/change-orders/${newCo.change_order_id}`;
    } catch (e) {
      alert(e.message || 'Could not create new change order.');
      actionBusy = false;
    }
  }

  /** Save button: everything is already persisted per-edit; just show reassurance. */
  function handleSaveButton() {
    saveLabel = 'Saved ✓';
    setTimeout(() => { saveLabel = 'Save'; }, 1500);
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
    try {
      await api.delete(`/api/change-orders/${co.change_order_id}/line-items/${coItem.line_item_id}/`);
      await loadCO();
    } catch (e) {
      alert(e.message || 'Could not undo change.');
    }
  }

  /** Added row → [Delete]: DELETE the CO line item */
  async function deleteAddedLine(coItem) {
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

  // Display status for change orders: show "amended" instead of "accepted" when
  // a later accepted CO exists on the same job (ordered by change_order_id).
  // Only an accepted later CO triggers the relabel — draft/open/rejected/etc. do not.
  function changeOrderDisplayStatus(co, allCosForJob) {
    if (co?.status === 'accepted' && (allCosForJob || []).some(
      other => other.change_order_id > co.change_order_id
               && other.status === 'accepted'
    )) {
      return 'amended';
    }
    return co?.status;
  }

  function fmtMoney(n) { return `$${Number(n ?? 0).toFixed(2)}`; }
  function fmtDiff(n) {
    const v = Number(n ?? 0);
    if (v === 0) return '$0.00';
    return (v > 0 ? '+' : '') + `$${Math.abs(v).toFixed(2)}`;
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
    <span class="status-badge status-co-{co.status}">{changeOrderDisplayStatus(co, siblingCOs)}</span>
    {#if canManageJobs}
      {#if isDraft}
        <button type="button" onclick={handleSaveButton} disabled={actionBusy}>
          {saveLabel}
        </button>
        <a href={`/change-orders/${co.change_order_id}/send`} use:link class="send-link">
          Send to customer
        </a>
        <span class="toolbar-spacer"></span>
        <button type="button" class="btn-danger" onclick={discard} disabled={actionBusy}>
          Discard
        </button>
      {:else if isOpen}
        <a href={`/change-orders/${co.change_order_id}/send`} use:link class="send-link">
          Resend to customer
        </a>
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

  <!-- Deliverables: diff editor -->
  <section class="section">
    <div class="section-head">
      <h3>Deliverables</h3>
      <span class="spacer"></span>
      {#if canManageJobs && isDraft && !delivNewOpen}
        <button type="button" onclick={openDelivNew}>+ New deliverable</button>
      {/if}
    </div>

    <table class="diff-table deliv-table">
      <colgroup>
        <col style="width:90px">
        <col>
        <col style="width:160px">
      </colgroup>
      <tbody>
        {#if delivMergedRows.length === 0 && !delivNewOpen}
          <tr>
            <td colspan="3" class="empty-msg">No deliverables yet.</td>
          </tr>
        {:else}
          {#each delivMergedRows as row}
            {#if row.kind === 'unchanged'}
              {#if delivEditId === row.live.id}
                <!-- Inline edit form for this row -->
                <tr class="row-editing">
                  <td colspan="3">
                    <div class="edit-row-layout">
                      <input class="qty-input" bind:value={delivEditQty}
                        onkeydown={(e) => delivEditKeydown(e, () => saveDelivEdit(row.live.id), cancelDelivEdit)} />
                      <UnitsSelect bind:value={delivEditUnits} />
                      <input class="desc-input-inline" bind:value={delivEditDescription}
                        onkeydown={(e) => delivEditKeydown(e, () => saveDelivEdit(row.live.id), cancelDelivEdit)} />
                      <button type="button" onclick={() => saveDelivEdit(row.live.id)} disabled={delivSaving}>Save</button>
                      <button type="button" onclick={cancelDelivEdit} disabled={delivSaving}>Cancel</button>
                    </div>
                  </td>
                </tr>
              {:else}
                <tr>
                  <td class="num">{fmtQty(row.qty)} {row.units}</td>
                  <td>{row.description || '—'}</td>
                  <td class="acts">
                    {#if canManageJobs && isDraft}
                      {#if row.anchored}
                        <span class="anchored-note">shipped</span>
                      {:else}
                        <button type="button" onclick={() => openDelivEdit(row.live)}>Change</button>
                        <button type="button" onclick={() => deleteDeliverable(row.live.id)}>Delete</button>
                      {/if}
                    {/if}
                  </td>
                </tr>
              {/if}
            {:else if row.kind === 'changed'}
              {#if delivEditId === row.live.id}
                <tr class="row-editing">
                  <td colspan="3">
                    <div class="edit-row-layout">
                      <input class="qty-input" bind:value={delivEditQty}
                        onkeydown={(e) => delivEditKeydown(e, () => saveDelivEdit(row.live.id), cancelDelivEdit)} />
                      <UnitsSelect bind:value={delivEditUnits} />
                      <input class="desc-input-inline" bind:value={delivEditDescription}
                        onkeydown={(e) => delivEditKeydown(e, () => saveDelivEdit(row.live.id), cancelDelivEdit)} />
                      <button type="button" onclick={() => saveDelivEdit(row.live.id)} disabled={delivSaving}>Save</button>
                      <button type="button" onclick={cancelDelivEdit} disabled={delivSaving}>Cancel</button>
                    </div>
                  </td>
                </tr>
              {:else}
                <tr class="row-changed">
                  <td class="num">{fmtQty(row.qty)} {row.units}</td>
                  <td>{row.description || '—'}</td>
                  <td class="acts">
                    {#if canManageJobs && isDraft}
                      {#if row.anchored}
                        <span class="anchored-note">shipped</span>
                      {:else}
                        <button type="button" onclick={() => openDelivEdit(row.live)}>Edit</button>
                        <button type="button" onclick={() => undoDelivChange(row.live.id, row.baseline)}>Undo</button>
                      {/if}
                    {/if}
                  </td>
                </tr>
              {/if}
            {:else if row.kind === 'changed-orig'}
              <tr class="row-gone">
                <td class="num keep">{fmtQty(row.qty)} {row.units}</td>
                <td>{row.description || '—'}</td>
                <td></td>
              </tr>
            {:else if row.kind === 'removed'}
              <tr class="row-gone">
                <td class="num keep">{fmtQty(row.qty)} {row.units}</td>
                <td>{row.description || '—'}</td>
                <td class="acts keep">
                  {#if canManageJobs && isDraft}
                    <button type="button" onclick={() => undoDelivRemove(row.baseline)}>Undo</button>
                  {/if}
                </td>
              </tr>
            {:else if row.kind === 'added'}
              {#if delivEditId === row.live.id}
                <tr class="row-editing">
                  <td colspan="3">
                    <div class="edit-row-layout">
                      <input class="qty-input" bind:value={delivEditQty}
                        onkeydown={(e) => delivEditKeydown(e, () => saveDelivEdit(row.live.id), cancelDelivEdit)} />
                      <UnitsSelect bind:value={delivEditUnits} />
                      <input class="desc-input-inline" bind:value={delivEditDescription}
                        onkeydown={(e) => delivEditKeydown(e, () => saveDelivEdit(row.live.id), cancelDelivEdit)} />
                      <button type="button" onclick={() => saveDelivEdit(row.live.id)} disabled={delivSaving}>Save</button>
                      <button type="button" onclick={cancelDelivEdit} disabled={delivSaving}>Cancel</button>
                    </div>
                  </td>
                </tr>
              {:else}
                <tr class="row-added">
                  <td class="num"><span class="added-tag">+</span>{fmtQty(row.qty)} {row.units}</td>
                  <td>{row.description || '—'}</td>
                  <td class="acts">
                    {#if canManageJobs && isDraft}
                      {#if row.anchored}
                        <span class="anchored-note">shipped</span>
                      {:else}
                        <button type="button" onclick={() => openDelivEdit(row.live)}>Edit</button>
                        <button type="button" onclick={() => deleteDeliverable(row.live.id)}>Delete</button>
                      {/if}
                    {/if}
                  </td>
                </tr>
              {/if}
            {/if}
          {/each}
        {/if}
        {#if delivNewOpen}
          <tr class="row-editing">
            <td colspan="3">
              <div class="edit-row-layout">
                <input class="qty-input" bind:value={delivNewQty}
                  onkeydown={(e) => delivEditKeydown(e, saveDelivNew, cancelDelivNew)} />
                <UnitsSelect bind:value={delivNewUnits} />
                <input class="desc-input-inline" bind:value={delivNewDescription} placeholder="Description"
                  onkeydown={(e) => delivEditKeydown(e, saveDelivNew, cancelDelivNew)} />
                <button type="button" onclick={saveDelivNew} disabled={delivSaving}>Add</button>
                <button type="button" onclick={cancelDelivNew} disabled={delivSaving}>Cancel</button>
              </div>
            </td>
          </tr>
        {/if}
      </tbody>
    </table>
  </section>

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
            Estimate <span class="est-struck">{fmtMoney(estimateTotal)}</span> &rarr; proposed
          </td>
          <td class="num"><strong>{fmtMoney(proposedTotal)}</strong></td>
          <td class="num footer-diff">{fmtDiff(diffTotal)}</td>
        </tr>
      </tfoot>
    </table>
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

  /* Pushes Discard to the far right in the draft toolbar */
  .toolbar-spacer { flex: 1; }

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

  /* Deliverables table — no line-number column; qty+units in first col */
  .deliv-table td.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
  /* The + tag inside the added qty cell */
  .deliv-table .added-tag { color: #166534; font-weight: 600; margin-right: 4px; }

  /* Inline editing row — uses a flex layout spanning all columns */
  .diff-table tr.row-editing { background: #f0f9ff; }
  .diff-table tr.row-editing td { padding: 4px 8px; }

  /* Flex row: qty input | units select | description (grows) | action buttons */
  .edit-row-layout {
    display: flex; align-items: center; gap: 6px;
  }
  .qty-input { width: 3.5em; flex-shrink: 0; }
  .desc-input-inline { flex: 1; min-width: 0; box-sizing: border-box; }

  /* Anchored note */
  .anchored-note { font-size: 11px; color: #9ca3af; font-style: italic; }
</style>
