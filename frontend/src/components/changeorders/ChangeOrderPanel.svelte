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
  import DocSubnav from '../jobs/DocSubnav.svelte';
  import { buildEstimateDocItems, changeOrderDisplayStatus } from '../../lib/estimateDocs.js';
  import { buildDeliverableRows } from '../../lib/changeOrderDiff.js';

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
  let defaultMaterialCategoryId = $state(null);
  let loading = $state(true);
  let error = $state('');

  // Deliverables diff state
  let liveDeliverables = $state([]);
  let delivBaseline = $state([]);

  let actionBusy = $state(false);

  // Save button transient state
  let saveLabel = $state('Save');

  // Per-object gate: atom-holder OR this job's project_manager (server-computed).
  const canManageJobs = $derived(co?.can_manage ?? false);

  let isDraft = $derived(co?.status === 'draft');
  let isOpen = $derived(co?.status === 'open');
  let isTerminal = $derived(['accepted', 'rejected'].includes(co?.status));

  let delivMergedRows = $derived(buildDeliverableRows(liveDeliverables, delivBaseline));

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

  // Nav list / categories / settings don't depend on the CO identity — load
  // once per job.
  $effect(() => {
    if (job?.job_id) {
      loadEstimatesForNav();
    }
    loadCategories();
    loadSettings();
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
  </div>

  <CODeliverablesSection
    jobId={co.job}
    rows={delivMergedRows}
    canEdit={canManageJobs && isDraft}
    onReload={loadCO}
  />

  <COEditView
    {co}
    canEdit={canManageJobs && isDraft}
    onChanged={handleEditChanged}
    {amended}
    {sourcePool}
    {categories}
    {defaultMaterialCategoryId}
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
