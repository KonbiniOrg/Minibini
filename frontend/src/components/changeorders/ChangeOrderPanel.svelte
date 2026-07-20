<script>
  // Change-order panel: the CO document surface hosted by the job workspace
  // (routes/jobs/JobChangeOrderPage → JobShell → this), the same shape as
  // EstimatePanel / InvoicePanel. Owns CO-scoped loading, the toolbar +
  // status actions, and the add-line/edit modals; the two diff grids are
  // CODeliverablesSection / COLineItemsSection over lib/changeOrderDiff
  // derivations. Extracted from the old ChangeOrderDetailPage route
  // (2026-07-19).
  import { link } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import COAddLineForm from './COAddLineForm.svelte';
  import COLineItemModal from './COLineItemModal.svelte';
  import CODeliverablesSection from './CODeliverablesSection.svelte';
  import COLineItemsSection from './COLineItemsSection.svelte';
  import DocSubnav from '../jobs/DocSubnav.svelte';
  import { buildEstimateDocItems, changeOrderDisplayStatus } from '../../lib/estimateDocs.js';
  import {
    buildMergedRows, lineDiffTotals, buildDeliverableRows,
  } from '../../lib/changeOrderDiff.js';
  import PriceListPicker from '../PriceListPicker.svelte';

  let {
    job,
    coId,
    onJobChange = () => {},
  } = $props();

  let co = $state(null);
  let estimateLines = $state([]);  // lines from the accepted estimate for target picking
  let estimatesForNav = $state([]); // all estimate versions for this job (version subnav)
  let siblingCOs = $state([]);     // all COs for this job (used for display-status relabelling)
  let loading = $state(true);
  let error = $state('');

  // Deliverables diff state
  let liveDeliverables = $state([]);
  let delivBaseline = $state([]);

  let modalOpen = $state(false);
  let modalMode = $state('create');
  let modalItem = $state(null);
  // Add-line flow: PriceListPicker → COAddLineForm (service / inventory / freeform)
  let pickerOpen = $state(false);
  let addLineChoice = $state(null);
  let addLineFormOpen = $state(false);
  let categories = $state([]);
  let defaultMaterialCategoryId = $state(null);
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

  // Per-object gate: atom-holder OR this job's project_manager (server-computed).
  const canManageJobs = $derived(co?.can_manage ?? false);

  let isDraft = $derived(co?.status === 'draft');
  let isOpen = $derived(co?.status === 'open');
  let isTerminal = $derived(['accepted', 'rejected'].includes(co?.status));

  // Diff derivations — pure functions in lib/changeOrderDiff.js (unit-tested;
  // the backend's compose_change_order_diff mirrors buildMergedRows).
  let mergedRows = $derived(buildMergedRows(estimateLines, co?.line_items));
  let totals = $derived(lineDiffTotals(estimateLines, mergedRows));
  let delivMergedRows = $derived(buildDeliverableRows(liveDeliverables, delivBaseline));

  async function loadCO() {
    loading = true;
    error = '';
    try {
      co = await api.get(`/api/change-orders/${coId}/`);
      if (co?.job) {
        // Load estimate lines for target picking (from accepted estimates)
        try {
          const estResp = await api.get(`/api/estimates/?job=${co.job}`);
          const estList = estResp?.results || estResp || [];
          estimatesForNav = estList;
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
            api.get(`/api/change-orders/${coId}/deliverables-baseline/`),
          ]);
          liveDeliverables = liveDel || [];
          delivBaseline = baselineResp?.baseline || [];
        } catch (_) {
          liveDeliverables = [];
          delivBaseline = [];
        }
      }
    } catch (e) {
      error = e.message || 'Could not load change order.';
    } finally {
      loading = false;
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

  async function loadSettings() {
    try {
      const s = await api.get('/api/settings/');
      const raw = s.default_material_accounting_category;
      defaultMaterialCategoryId = raw != null ? Number(raw) : null;
    } catch (_) {
      defaultMaterialCategoryId = null;
    }
  }

  $effect(() => {
    if (coId) {
      loadCO();
    }
  });

  // Categories/settings don't depend on the CO identity — load once.
  $effect(() => {
    loadCategories();
    loadSettings();
  });

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
  // Diff-editor actions (the section is a dumb renderer; API calls live here)
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
      showError(errorMessage(e, 'Could not remove estimate line.'));
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
      showError(errorMessage(e, 'Could not undo change.'));
    }
  }

  /** Added row → [Delete]: DELETE the CO line item */
  async function deleteAddedLine(coItem) {
    try {
      await api.delete(`/api/change-orders/${co.change_order_id}/line-items/${coItem.line_item_id}/`);
      await loadCO();
    } catch (e) {
      showError(errorMessage(e, 'Could not delete line item.'));
    }
  }

  /** [+ New line] button → unified picker (service / inventory / freeform),
      same entry point as the estimate panel's Add Line. */
  function openAddItem() {
    pickerOpen = true;
  }

  function handleAddLineChoice(choice) {
    pickerOpen = false;
    addLineChoice = choice;
    addLineFormOpen = true;
  }

  function handleAddLineSaved() {
    addLineFormOpen = false;
    addLineChoice = null;
    loadCO();
  }

  function handleSaved() {
    modalOpen = false;
    modalItem = null;
    loadCO();
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
  </div>

  <CODeliverablesSection
    jobId={co.job}
    rows={delivMergedRows}
    canEdit={canManageJobs && isDraft}
    onReload={loadCO}
  />

  <COLineItemsSection
    rows={mergedRows}
    {estimateLines}
    {totals}
    canEdit={canManageJobs && isDraft}
    onAddItem={openAddItem}
    onChangeLine={openChangeEstimateLine}
    onRemoveLine={removeEstimateLine}
    onEditLine={openEditCOLine}
    onUndoLine={undoCOLine}
    onDeleteLine={deleteAddedLine}
  />

  <COLineItemModal
    open={modalOpen}
    mode={modalMode}
    coId={co.change_order_id}
    item={modalItem}
    {estimateLines}
    {categories}
    initialAction={modalInitialAction}
    initialTarget={modalInitialTarget}
    initialDescription={modalInitialDescription}
    initialQty={modalInitialQty}
    initialUnits={modalInitialUnits}
    initialPrice={modalInitialPrice}
    onSaved={handleSaved}
    onClose={() => { modalOpen = false; }}
  />

  <PriceListPicker
    open={pickerOpen}
    onChoose={handleAddLineChoice}
    onclose={() => { pickerOpen = false; }}
  />

  <COAddLineForm
    open={addLineFormOpen}
    choice={addLineChoice}
    coId={co.change_order_id}
    {categories}
    {defaultMaterialCategoryId}
    onSaved={handleAddLineSaved}
    onClose={() => { addLineFormOpen = false; addLineChoice = null; }}
  />
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
