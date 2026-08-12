<script>
  // Change-order panel: the CO document surface hosted by the job workspace
  // (routes/jobs/JobChangeOrderPage → JobShell → this), the same shape as
  // EstimatePanel / InvoicePanel. Owns CO-scoped loading, the toolbar +
  // status actions; the two edit surfaces are CODeliverablesSection (over
  // lib/changeOrderDiff's buildDeliverableRows) and COEditView (over the
  // server-composed amended-agreement — Tasks 5-8). Extracted from the old
  // ChangeOrderDetailPage route (2026-07-19); COEditView replaced the old
  // flat line-item diff table (COLineItemsSection) 2026-08-09.
  import { link } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import CODeliverablesSection from './CODeliverablesSection.svelte';
  import COEditView from './COEditView.svelte';
  import COCustomerView from './COCustomerView.svelte';
  import DocModeBar from '../docsurface/DocModeBar.svelte';
  import DocReorderView from '../docsurface/DocReorderView.svelte';
  import DocSubnav from '../jobs/DocSubnav.svelte';
  import { buildEstimateDocItems, changeOrderDisplayStatus } from '../../lib/estimateDocs.js';
  import { buildDeliverableRows } from '../../lib/changeOrderDiff.js';
  import { getJobWs, rememberMode } from '../../stores/jobWorkspace.js';

  let {
    job,
    coId,
    onJobChange = () => {},
  } = $props();

  let co = $state(null);
  let amended = $state(null);      // amended-agreement payload (rows + totals)
  let sourcePool = $state(null);   // CO source-pool (uncovered work)
  let estimatesForNav = $state([]); // all estimate versions for this job (version subnav)
  let siblingCOs = $state([]);     // all COs for this job (used for display-status relabelling)
  let categories = $state([]);
  let loading = $state(true);
  let error = $state('');

  // Deliverables diff state
  let liveDeliverables = $state([]);
  let delivBaseline = $state([]);
  let deliverablesDiff = $state([]); // server-composed kind rows (Customer mode)

  let actionBusy = $state(false);

  // Save button transient state
  let saveLabel = $state('Save');

  // Per-object gate: atom-holder OR this job's project_manager (server-computed).
  const canManageJobs = $derived(co?.can_manage ?? false);

  let isDraft = $derived(co?.status === 'draft');
  let isOpen = $derived(co?.status === 'open');
  let isTerminal = $derived(['accepted', 'rejected'].includes(co?.status));
  let canEdit = $derived(canManageJobs && isDraft);

  let delivMergedRows = $derived(buildDeliverableRows(liveDeliverables, delivBaseline));

  // The mode bar is a surface of this panel, not a separate route — same
  // shape as EstimatePanel's mode wiring. Reorder is only restorable while
  // the CO is still an editable draft (someone may have sent it since the
  // mode was remembered).
  let mode = $state('edit');
  let modeInitializedFor = $state(null);
  let modes = $derived(canEdit ? ['edit', 'customer', 'reorder'] : ['edit', 'customer']);
  // Read-only documents relabel the mode: same surface, but it's now the
  // shop-facing Detail view, not an editor (RM 2026-08-09).
  let modeLabels = $derived(
    { edit: canEdit ? 'Edit' : 'Detail', customer: 'Customer', reorder: 'Reorder' });
  $effect(() => {
    if (co && String(co.change_order_id) === String(coId)
        && modeInitializedFor !== String(coId)) {
      const remembered = getJobWs(job?.job_id).modes[`co:${coId}`] ?? 'edit';
      mode = (remembered === 'reorder' && !canEdit) ? 'edit' : remembered;
      modeInitializedFor = String(coId);
    }
  });

  function setMode(next) {
    mode = next;
    rememberMode(job?.job_id, `co:${coId}`, next);
  }

  function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString();
  }

  // Reorder mode operates over the CO's OWN add+replace rows only (labeled
  // "CO {co_index} — {description}"), taken from the amended-agreement
  // payload so the display order/label match the edit view exactly.
  let reorderLines = $derived(
    (amended?.rows || [])
      .filter((r) => r.kind === 'added' || r.kind === 'replaced')
      .slice()
      .sort((a, b) => (a.co_index ?? 0) - (b.co_index ?? 0))
      .map((r) => ({
        line_id: r.co_line_id,
        line_number: r.co_index,
        description: `CO ${r.co_index} — ${r.line.description || 'No description'}`,
        qty: r.line.qty,
        units: r.line.units,
        price: r.line.price,
        amount: Number(r.line.amount || 0),
      }))
  );
  let reorderGrandTotal = $derived(
    reorderLines.reduce((sum, l) => sum + Number(l.amount || 0), 0)
  );

  // The CO's own remove-line ids, in their existing line_number order — the
  // reorder endpoint renumbers every listed line from 1, so these must ride
  // along at the end of every reorder POST or they'd collide with the
  // renumbered add/replace lines.
  let removeLineIds = $derived(
    (co?.line_items || [])
      .filter((li) => li.action === 'remove')
      .slice()
      .sort((a, b) => (a.line_number ?? 0) - (b.line_number ?? 0))
      .map((li) => li.line_item_id)
  );

  async function handleReorderDoc(lineId, direction) {
    const ids = reorderLines.map((l) => l.line_id);
    const idx = ids.indexOf(lineId);
    if (idx === -1) return;
    const swapIdx = direction === 'up' ? idx - 1 : idx + 1;
    if (swapIdx < 0 || swapIdx >= ids.length) return;
    [ids[idx], ids[swapIdx]] = [ids[swapIdx], ids[idx]];
    try {
      await api.post(`/api/change-orders/${co.change_order_id}/line-items/reorder/`, {
        item_ids: [...ids, ...removeLineIds],
      });
      await loadCO();
    } catch (e) {
      showError(errorMessage(e, 'Could not reorder line items.'));
    }
  }

  // `silent`: post-gesture refreshes from COEditView (add-atoms, create-a-line,
  // remove, replace, adjustments...) must NOT flip `loading` — that would
  // swap the `{#if loading}` branch to "Loading…", destroying and
  // remounting COEditView on every single gesture and losing its local
  // state (the just-opened edit modal, the in-progress atom selection). A
  // silent failure doesn't blank the surface either — it reports through the
  // global overlay and leaves the last-good doc on screen (mirrors
  // EstimatePanel's loadEstimate).
  async function loadCO({ silent = false } = {}) {
    if (!silent) {
      loading = true;
      error = '';
    }
    try {
      co = await api.get(`/api/change-orders/${coId}/`);
      if (co?.job) {
        // Load all COs for the job (for display-status relabelling)
        try {
          const cosResp = await api.get(`/api/change-orders/?job=${co.job}`);
          siblingCOs = cosResp?.results || cosResp || [];
        } catch (_) {
          siblingCOs = [];
        }
        // Load live deliverables + baseline snapshot + server-composed diff
        // (the diff drives Customer mode; same rows as the portal/PDF).
        try {
          const [liveDel, baselineResp, diffResp] = await Promise.all([
            api.get(`/api/jobs/${co.job}/deliverables/`),
            api.get(`/api/change-orders/${coId}/deliverables-baseline/`),
            api.get(`/api/change-orders/${coId}/deliverables-diff/`),
          ]);
          liveDeliverables = liveDel || [];
          delivBaseline = baselineResp?.baseline || [];
          deliverablesDiff = diffResp?.rows || [];
        } catch (_) {
          liveDeliverables = [];
          delivBaseline = [];
          deliverablesDiff = [];
        }
        // Amended agreement + source pool — COEditView's own data.
        try {
          amended = await api.get(`/api/change-orders/${coId}/amended-agreement/`);
        } catch (_) {
          amended = null;
        }
        try {
          sourcePool = await api.get(`/api/change-orders/${coId}/source-pool/`);
        } catch (_) {
          sourcePool = { atoms: [] };
        }
      }
    } catch (e) {
      if (silent) {
        showError(errorMessage(e, 'Could not refresh the change order.'));
      } else {
        error = e.message || 'Could not load change order.';
      }
    } finally {
      if (!silent) loading = false;
    }
  }

  async function loadEstimatesForNav() {
    try {
      const estResp = await api.get(`/api/estimates/?job=${job.job_id}`);
      estimatesForNav = estResp?.results || estResp || [];
    } catch (_) {
      estimatesForNav = [];
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
    if (coId) {
      loadCO();
    }
  });

  // Nav list / categories / settings don't depend on the CO identity — load
  // once per job.
  $effect(() => {
    if (job?.job_id) {
      loadEstimatesForNav();
    }
    loadCategories();
  });

  // COEditView is presentation + gestures only — every mutation it makes
  // (add/remove atoms, add/edit/remove/replace a line, undo...) calls back
  // here so the amended agreement and the uncovered-work pool stay in sync.
  // Silent: see loadCO's comment above — COEditView awaits this to look up
  // the fresh copy of a just-created line, so it must resolve without ever
  // tearing the view down mid-gesture.
  async function handleEditChanged() {
    await loadCO({ silent: true });
  }

  // --------------------------------------------------------------------------

  // Status actions
  async function handleStatusChange(newStatus) {
    const labels = { accepted: 'Accept', rejected: 'Reject' };
    const label = labels[newStatus] || newStatus;
    if (!confirm(`${label} this change order?${newStatus === 'accepted' ? ' Only confirm if the customer has definitely approved it.' : ''}`)) return;
    actionBusy = true;
    try {
      await api.patch(`/api/change-orders/${co.change_order_id}/`, { status: newStatus });
      await loadCO();
      // Acceptance crystallizes onto the job's atoms — refresh the host's job.
      onJobChange();
    } catch (e) {
      showError(errorMessage(e, 'Could not update status.'));
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
      showError(errorMessage(e, 'Could not discard change order.'));
      actionBusy = false;
    }
  }

  async function seedNew() {
    // No confirm: the new draft CO is trivially discardable.
    actionBusy = true;
    try {
      const newCo = await api.post(`/api/change-orders/${co.change_order_id}/seed-new/`);
      window.location.hash = `/jobs/${co.job}/change-order/${newCo.change_order_id}`;
    } catch (e) {
      showError(errorMessage(e, 'Could not create new change order.'));
      actionBusy = false;
    }
  }

  /** Save button: everything is already persisted per-edit; just show reassurance. */
  function handleSaveButton() {
    saveLabel = 'Saved ✓';
    setTimeout(() => { saveLabel = 'Save'; }, 1500);
  }

  // --------------------------------------------------------------------------

  // Version subnav: estimate versions then this job's change orders, with this
  // CO marked active. Shares the estimate panel's builder so the two stay in
  // lockstep (changeOrderDisplayStatus is imported from the same module).
  let subnavItems = $derived(
    job
      ? buildEstimateDocItems({
          estimates: estimatesForNav,
          changeOrders: siblingCOs,
          jobId: job.job_id,
          currentKey: `co-${coId}`,
        })
      : []
  );
</script>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p class="error">{error}</p>
{:else if co}
  {#if subnavItems.length > 0}
    <DocSubnav items={subnavItems} section="estimate" />
  {/if}

  <div class="page-body">
  <!-- CO toolbar -->
  <div class="toolbar">
    <span class="page-title">{co.change_order_number || `CO #${co.change_order_id}`}</span>
    <span class="status-badge status-{co.status}">{changeOrderDisplayStatus(co, siblingCOs)}</span>
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
    <!-- Compact date chips (mirrors EstimatePanel): number/job/status live in
         the header and surrounding context; the parent-revision link is
         covered by the DocSubnav version pills. Dates only, right end of the
         title row. -->
    <div class="stat-chips doc-stat-chips">
      <div class="stat-chip">
        <div class="stat-chip-header">Created</div>
        <div class="stat-chip-body">{fmtDate(co.created_date)}</div>
      </div>
      <div class="stat-chip">
        <div class="stat-chip-header">Sent</div>
        <div class="stat-chip-body"><span class:muted={!co.sent_date}>{co.sent_date ? fmtDate(co.sent_date) : '-'}</span></div>
      </div>
      <div class="stat-chip">
        <div class="stat-chip-header">Expires</div>
        <div class="stat-chip-body"><span class:muted={!co.expiration_date}>{co.expiration_date ? fmtDate(co.expiration_date) : '-'}</span></div>
      </div>
      <div class="stat-chip">
        <div class="stat-chip-header">Closed</div>
        <div class="stat-chip-body"><span class:muted={!co.closed_date}>{co.closed_date ? fmtDate(co.closed_date) : '-'}</span></div>
      </div>
    </div>
  </div>

  <DocModeBar {mode} onMode={setMode} {modes} labels={modeLabels} />

  {#if mode === 'edit'}
    <CODeliverablesSection
      jobId={co.job}
      rows={delivMergedRows}
      canEdit={canEdit}
      onReload={loadCO}
    />

    <COEditView
      {co}
      {canEdit}
      onChanged={handleEditChanged}
      {amended}
      {sourcePool}
      {categories}
    />
  {:else if mode === 'customer'}
    <COCustomerView
      title={`Change Order ${co.change_order_number || `CO #${co.change_order_id}`}`}
      rows={amended?.rows || []}
      deliverables={deliverablesDiff}
      originalTotal={amended?.original_total}
      coDelta={amended?.co_delta}
      revisedTotal={amended?.revised_total}
    />
  {:else if mode === 'reorder'}
    <DocReorderView
      title={`Change Order ${co.change_order_number || `CO #${co.change_order_id}`}`}
      lines={reorderLines}
      grandTotal={reorderGrandTotal}
      onReorder={handleReorderDoc}
    />
  {/if}
  </div>
{/if}

<style>
  .error { color: #a8071a; padding: 16px; }

  /* .toolbar / .page-title come from app.css. */

  /* Pushes Discard to the far right in the draft toolbar */
  .toolbar-spacer { flex: 1; }

  /* Status pill styling and colors come from the global .status-badge /
     .status-{status} classes (app.css). */

  .btn-danger { background: #fee2e2; color: #991b1b; border-color: #fca5a5; }
  .btn-danger:hover { background: #fecaca; }
  .btn-accept { background: #dcfce7; color: #166534; border-color: #86efac; }
  .btn-accept:hover { background: #bbf7d0; }
</style>
