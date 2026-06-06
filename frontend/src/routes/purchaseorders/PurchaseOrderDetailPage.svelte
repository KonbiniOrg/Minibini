<script>
  import { api } from '../../lib/api.js';
  import { canManageFinancials as canManageFinancialsStore } from '../../stores/permissions.js';
  import { push, querystring } from 'svelte-spa-router';
  import PurchaseOrderDetail from '../../components/purchaseorders/PurchaseOrderDetail.svelte';
  import LineItemForm from '../../components/purchaseorders/LineItemForm.svelte';
  import ReceiveItemsForm from '../../components/purchaseorders/ReceiveItemsForm.svelte';
  import MaterialSeverDialog from '../../components/purchaseorders/MaterialSeverDialog.svelte';
  import HistoryPanel from '../../components/HistoryPanel.svelte';

  const { params = {} } = $props();

  let po = $state(null);
  let history = $state(null);
  let categories = $state([]);
  let loading = $state(true);
  let loadError = $state(null);
  let error = $state(null);
  let success = $state(null);
  let showAddLineItem = $state(false);
  let showReceiveForm = $state(false);
  let busy = $state(false);
  let severPrompt = $state(null); // { items, onSubmit } when showing

  // Prefill state when navigating in with ?prefill_material=...&default_job=...
  const initialQs = new URLSearchParams($querystring);
  const prefillMaterialId = initialQs.get('prefill_material');
  const defaultJobId = initialQs.get('default_job');
  let prefilledJob = $state(null);
  let prefilledMaterial = $state(null);
  let prefilledMaterialIdNum = $state(null);
  let prefillLoaded = $state(false);

  function collectLinkedMaterials(lines) {
    return (lines || [])
      .filter(li => li.material && li.material.consumption_state === 'pending')
      .map(li => ({
        material_id: li.material.material_id,
        line_item_id: li.line_item_id,
        job_number: li.material.job_number,
        quantity: li.material.quantity,
        description: li.description,
      }));
  }

  let canManageFinancials = $derived($canManageFinancialsStore);

  async function loadPO() {
    loading = true;
    loadError = null;
    try {
      po = await api.get(`/api/purchase-orders/${params.id}/`);
      const [histData, catData] = await Promise.all([
        api.get(`/api/purchase-orders/${params.id}/history/`),
        api.get('/api/accounting-categories/?page_size=100'),
      ]);
      history = histData;
      categories = catData.results || catData;
      await loadPrefill();
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function loadPrefill() {
    if (prefillLoaded) return;
    prefillLoaded = true;
    if (defaultJobId) {
      try {
        prefilledJob = await api.get(`/api/jobs/${defaultJobId}/`);
      } catch {
        prefilledJob = null;
      }
    }
    if (prefillMaterialId) {
      try {
        prefilledMaterial = await api.get(`/api/materials/${prefillMaterialId}/`);
        prefilledMaterialIdNum = Number(prefillMaterialId);
      } catch {
        prefilledMaterial = null;
        prefilledMaterialIdNum = null;
      }
    }
    // Auto-open the add-line-item form when we have any prefill context
    // and the PO is still in draft.
    if ((prefilledJob || prefilledMaterial) && po?.status === 'draft') {
      showAddLineItem = true;
    }
  }

  async function reload() {
    error = null;
    try {
      po = await api.get(`/api/purchase-orders/${params.id}/`);
      history = await api.get(`/api/purchase-orders/${params.id}/history/`);
    } catch (e) {
      error = e.message;
    }
  }

  async function handleStatusAction(actionName, data = {}) {
    busy = true;
    error = null;
    success = null;
    try {
      await api.post(`/api/purchase-orders/${po.po_id}/${actionName}/`, data);
      await reload();
      success = `Purchase order ${actionName}d.`;
    } catch (e) {
      error = e.data?.detail || e.data?.reason?.[0] || e.message;
    } finally {
      busy = false;
    }
  }

  async function handleIssue() {
    const reason = prompt('Note (optional, e.g. "ordered by phone"):');
    if (reason === null) return;
    await handleStatusAction('issue', reason ? { reason } : {});
  }

  async function handleCancel() {
    const reason = prompt('Reason for cancellation:');
    if (!reason) return;
    const linkedMaterials = collectLinkedMaterials(po.line_items);
    const runCancel = async (severDecision) => {
      busy = true;
      error = null;
      success = null;
      try {
        const payload = { reason };
        if (severDecision) payload.sever_decision = severDecision;
        await api.post(`/api/purchase-orders/${po.po_id}/cancel/`, payload);
        await reload();
        success = 'Purchase order cancelled.';
      } catch (e) {
        error = e.data?.detail || e.data?.reason?.[0] || e.message;
      } finally {
        busy = false;
        severPrompt = null;
      }
    };
    if (linkedMaterials.length > 0) {
      severPrompt = {
        items: linkedMaterials,
        onSubmit: (decisions) => runCancel(decisions),
      };
    } else {
      await runCancel(null);
    }
  }

  async function handleDelete() {
    if (!confirm('Delete this purchase order? This cannot be undone.')) return;
    const linkedMaterials = collectLinkedMaterials(po.line_items);
    const runDelete = async (severDecision) => {
      busy = true;
      error = null;
      try {
        const payload = severDecision ? { sever_decision: severDecision } : null;
        await api.delete(`/api/purchase-orders/${po.po_id}/?confirm=true`, payload);
        severPrompt = null;
        push('/purchase-orders');
      } catch (e) {
        error = e.data?.detail || e.message;
        busy = false;
        severPrompt = null;
      }
    };
    if (linkedMaterials.length > 0) {
      severPrompt = {
        items: linkedMaterials,
        onSubmit: (decisions) => runDelete(decisions),
      };
    } else {
      await runDelete(null);
    }
  }

  async function handleAddLineItem(data) {
    error = null;
    try {
      await api.post(`/api/purchase-orders/${po.po_id}/line-items/`, data);
      showAddLineItem = false;
      await reload();
    } catch (e) {
      error = e.data ? JSON.stringify(e.data) : e.message;
    }
  }

  async function handleEditLineItem(lineItemId, data) {
    error = null;
    try {
      await api.patch(
        `/api/purchase-orders/${po.po_id}/line-items/${lineItemId}/`,
        data
      );
      await reload();
    } catch (e) {
      error = e.data ? JSON.stringify(e.data) : e.message;
    }
  }

  async function handleDeleteLineItem(lineItem) {
    // No confirm: draft-only line edit, re-addable by hand.
    error = null;
    try {
      await api.delete(
        `/api/purchase-orders/${po.po_id}/line-items/${lineItem.line_item_id}/`
      );
      await reload();
    } catch (e) {
      error = e.message;
    }
  }

  async function handleReorder(itemIds) {
    error = null;
    try {
      await api.post(
        `/api/purchase-orders/${po.po_id}/line-items/reorder/`,
        { item_ids: itemIds }
      );
      await reload();
    } catch (e) {
      error = e.message;
    }
  }

  async function handleReceiveAll() {
    // No confirm: reversible via the Reverse Receipt action.
    busy = true;
    error = null;
    success = null;
    try {
      await api.post(`/api/purchase-orders/${po.po_id}/receive-all/`);
      success = 'All items received.';
      await reload();
    } catch (e) {
      error = e.data?.detail || e.message;
    } finally {
      busy = false;
    }
  }

  async function handleReceiveItems(items) {
    busy = true;
    error = null;
    success = null;
    try {
      await api.post(`/api/purchase-orders/${po.po_id}/receive/`, { items });
      showReceiveForm = false;
      success = 'Items received.';
      await reload();
    } catch (e) {
      error = e.data?.detail || e.message;
    } finally {
      busy = false;
    }
  }

  async function handleCancelLineItem(lineItemId, note) {
    const line = (po.line_items || []).find(li => li.line_item_id === lineItemId);
    const linked = (line && line.material && line.material.consumption_state === 'pending')
      ? [{
          material_id: line.material.material_id,
          line_item_id: line.line_item_id,
          job_number: line.material.job_number,
          quantity: line.material.quantity,
          description: line.description,
        }]
      : [];
    const runCancelLine = async (severDecision) => {
      busy = true;
      error = null;
      success = null;
      try {
        const payload = { line_item_id: lineItemId, note };
        if (severDecision) payload.sever_decision = severDecision;
        await api.post(`/api/purchase-orders/${po.po_id}/cancel-line-item/`, payload);
        success = 'Line item cancelled.';
        await reload();
      } catch (e) {
        error = e.data?.detail || e.message;
      } finally {
        busy = false;
        severPrompt = null;
      }
    };
    if (linked.length > 0) {
      severPrompt = {
        items: linked,
        onSubmit: (decisions) => runCancelLine(decisions),
      };
    } else {
      await runCancelLine(null);
    }
  }

  async function handleReverseReceipt(lineItemId, note) {
    busy = true;
    error = null;
    success = null;
    try {
      await api.post(`/api/purchase-orders/${po.po_id}/reverse-receipt/`, {
        line_item_id: lineItemId,
        note,
      });
      success = 'Receipt reversed.';
      await reload();
    } catch (e) {
      error = e.data?.detail || e.message;
    } finally {
      busy = false;
    }
  }

  async function handleChangeLineJob(lineItemId, newJobId, existingMaterial) {
    const runPatch = async (severDecision) => {
      busy = true;
      error = null;
      try {
        const payload = { job: newJobId };
        if (severDecision) payload.sever_decision = severDecision;
        await api.patch(
          `/api/purchase-orders/${po.po_id}/line-items/${lineItemId}/`,
          payload,
        );
        await reload();
      } catch (e) {
        error = e.data?.detail || e.message;
      } finally {
        busy = false;
        severPrompt = null;
      }
    };
    if (existingMaterial && existingMaterial.consumption_state === 'pending') {
      const line = (po.line_items || []).find(li => li.line_item_id === lineItemId);
      severPrompt = {
        items: [{
          material_id: existingMaterial.material_id,
          line_item_id: lineItemId,
          job_number: existingMaterial.job_number,
          quantity: existingMaterial.quantity,
          description: line?.description ?? existingMaterial.description ?? '',
        }],
        onSubmit: (decisions) => runPatch(decisions[lineItemId]),
      };
    } else {
      await runPatch(null);
    }
  }

  async function handleAddNote(text) {
    try {
      await api.post(`/api/purchase-orders/${params.id}/notes/`, { text });
      history = await api.get(`/api/purchase-orders/${params.id}/history/`);
    } catch (e) {
      error = e.message;
    }
  }

  $effect(() => {
    void params.id;
    loadPO();
  });
</script>

{#if error}
  <div class="error-overlay">
    <div class="error-overlay-content">
      <button class="error-overlay-close" onclick={() => { error = null; }}>&times;</button>
      <p><strong>Error:</strong> {error}</p>
    </div>
  </div>
{/if}

{#if loading}
  <p>Loading...</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else if po}
  {#if success}
    <p><strong>{success}</strong></p>
  {/if}

  <PurchaseOrderDetail
    {po}
    {canManageFinancials}
    {busy}
    onIssue={handleIssue}
    onCancel={handleCancel}
    onDelete={handleDelete}
    onDeleteLineItem={handleDeleteLineItem}
    onEditLineItem={handleEditLineItem}
    onReorder={handleReorder}
    onSend={() => { push(`/purchase-orders/${po.po_id}/send`); }}
    onReceiveAll={handleReceiveAll}
    onReceiveItems={() => { showReceiveForm = true; }}
    onCancelLineItem={handleCancelLineItem}
    onReverseReceipt={handleReverseReceipt}
    onChangeLineJob={handleChangeLineJob}
  />

  {#if showReceiveForm}
    <ReceiveItemsForm
      lineItems={po.line_items || []}
      onSubmit={handleReceiveItems}
      onCancel={() => { showReceiveForm = false; }}
    />
  {/if}

  {#if canManageFinancials && po.status === 'draft'}
    <p>
      {#if showAddLineItem}
        <LineItemForm
          {categories}
          defaultJob={prefilledJob}
          materialId={prefilledMaterialIdNum}
          prefillMaterial={prefilledMaterial}
          onSubmit={handleAddLineItem}
          onCancel={() => { showAddLineItem = false; }}
        />
      {:else}
        <button onclick={() => { showAddLineItem = true; }}>Add Line Item</button>
      {/if}
    </p>
  {/if}

  <HistoryPanel {history} onAddNote={handleAddNote} />

  <p><a href="#/purchase-orders">Back to list</a></p>
{/if}

{#if severPrompt}
  <MaterialSeverDialog
    items={severPrompt.items}
    onSubmit={severPrompt.onSubmit}
    onCancel={() => { severPrompt = null; }}
  />
{/if}

<style>
  .error-overlay {
    position: fixed; top: 0; left: 0; right: 0;
    background: #fee2e2; border-bottom: 2px solid #dc2626;
    padding: 12px 16px; z-index: 500;
  }
  .error-overlay-content {
    max-width: 800px; margin: 0 auto; position: relative;
  }
  .error-overlay-close {
    position: absolute; top: 0; right: 0;
    background: none; border: none; font-size: 20px;
    cursor: pointer; color: #dc2626;
  }
</style>
