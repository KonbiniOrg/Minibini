<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { showError, showSuccess } from '../../stores/messages.js';
  import { orderPrefillQty } from '../../lib/materials.js';
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
  let showAddLineItem = $state(false);
  let showReceiveForm = $state(false);
  let busy = $state(false);
  let severPrompt = $state(null); // { items, onSubmit } when showing

  // Prefill state when navigating in with ?prefill_material / ?prefill_inventory_item
  // (+ optional ?default_job). The neutral `prefilledLine` is what LineItemForm
  // consumes; it's derived here from whichever source the URL named.
  const initialQs = new URLSearchParams($querystring);
  const prefillMaterialId = initialQs.get('prefill_material');
  const prefillInventoryItemId = initialQs.get('prefill_inventory_item');
  const defaultJobId = initialQs.get('default_job');
  let prefilledJob = $state(null);
  let prefilledMaterialIdNum = $state(null);
  let prefilledLine = $state(null);   // { inventory_item?, qty?, description?, price?, accounting_category? }
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
        const mat = await api.get(`/api/materials/${prefillMaterialId}/`);
        prefilledMaterialIdNum = Number(prefillMaterialId);
        // Derive the neutral prefill from the Material here, so LineItemForm
        // stays model-agnostic. (PLI-backed → inventory_item drives it; freeform
        // → description/cost.)
        prefilledLine = {
          qty: orderPrefillQty(mat),
          inventory_item: mat.inventory_item || null,
          description: mat.description,
          price: mat.unit_cost,
          accounting_category: mat.accounting_category,
        };
      } catch {
        prefilledMaterialIdNum = null;
        prefilledLine = null;
      }
    } else if (prefillInventoryItemId) {
      // Inventory "order" flow: just point the line at the item; LineItemForm
      // fetches it and fills code/description/units/price.
      prefilledLine = { inventory_item: Number(prefillInventoryItemId) };
    }
    // Auto-open the add-line-item form when we have any prefill context
    // and the PO is still in draft.
    if ((prefilledJob || prefilledLine) && po?.status === 'draft') {
      showAddLineItem = true;
    }
  }

  async function reload() {
    try {
      po = await api.get(`/api/purchase-orders/${params.id}/`);
      history = await api.get(`/api/purchase-orders/${params.id}/history/`);
    } catch (e) {
      showError(errorMessage(e, 'Could not reload purchase order.'));
    }
  }

  async function handleStatusAction(actionName, data = {}) {
    busy = true;
    try {
      await api.post(`/api/purchase-orders/${po.po_id}/${actionName}/`, data);
      await reload();
      showSuccess(`Purchase order ${actionName}d.`);
    } catch (e) {
      showError(errorMessage(e, `Could not ${actionName} purchase order.`));
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
    const runCancel = async (severDecisions) => {
      busy = true;
      try {
        const payload = { reason };
        if (severDecisions) payload.sever_decisions = severDecisions;
        await api.post(`/api/purchase-orders/${po.po_id}/cancel/`, payload);
        await reload();
        showSuccess('Purchase order cancelled.');
      } catch (e) {
        showError(errorMessage(e, 'Could not cancel purchase order.'));
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
    const runDelete = async (severDecisions) => {
      busy = true;
      try {
        const payload = severDecisions ? { sever_decisions: severDecisions } : null;
        await api.delete(`/api/purchase-orders/${po.po_id}/?confirm=true`, payload);
        severPrompt = null;
        push('/purchase-orders');
      } catch (e) {
        showError(errorMessage(e, 'Could not delete purchase order.'));
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
    try {
      await api.post(`/api/purchase-orders/${po.po_id}/line-items/`, data);
      showAddLineItem = false;
      // The "order this material" prefill is one-shot: it applies only to the
      // first line. Clear it after a successful add so a second line doesn't
      // re-send the same material_id (which is now linked) — the job stays
      // selected for convenience on the same job's subsequent lines.
      prefilledMaterialIdNum = null;
      prefilledLine = null;
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not add line item.'));
    }
  }

  async function handleEditLineItem(lineItemId, data) {
    try {
      await api.patch(
        `/api/purchase-orders/${po.po_id}/line-items/${lineItemId}/`,
        data
      );
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not update line item.'));
    }
  }

  async function handleDeleteLineItem(lineItem) {
    // No confirm: draft-only line edit, re-addable by hand.
    try {
      await api.delete(
        `/api/purchase-orders/${po.po_id}/line-items/${lineItem.line_item_id}/`
      );
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not delete line item.'));
    }
  }

  async function handleReorder(itemIds) {
    try {
      await api.post(
        `/api/purchase-orders/${po.po_id}/line-items/reorder/`,
        { item_ids: itemIds }
      );
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not reorder line items.'));
    }
  }

  async function handleReceiveAll() {
    // No confirm: reversible via the Reverse Receipt action.
    busy = true;
    try {
      await api.post(`/api/purchase-orders/${po.po_id}/receive-all/`);
      showSuccess('All items received.');
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not receive items.'));
    } finally {
      busy = false;
    }
  }

  async function handleReceiveItems(items) {
    busy = true;
    try {
      await api.post(`/api/purchase-orders/${po.po_id}/receive/`, { items });
      showReceiveForm = false;
      showSuccess('Items received.');
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not receive items.'));
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
      try {
        const payload = { line_item_id: lineItemId, note };
        if (severDecision) payload.sever_decision = severDecision;
        await api.post(`/api/purchase-orders/${po.po_id}/cancel-line-item/`, payload);
        showSuccess('Line item cancelled.');
        await reload();
      } catch (e) {
        showError(errorMessage(e, 'Could not cancel line item.'));
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
    try {
      await api.post(`/api/purchase-orders/${po.po_id}/reverse-receipt/`, {
        line_item_id: lineItemId,
        note,
      });
      showSuccess('Receipt reversed.');
      await reload();
    } catch (e) {
      showError(errorMessage(e, 'Could not reverse receipt.'));
    } finally {
      busy = false;
    }
  }

  async function handleChangeLineJob(lineItemId, newJobId, existingMaterial) {
    const runPatch = async (severDecision) => {
      busy = true;
      try {
        const payload = { job: newJobId };
        if (severDecision) payload.sever_decision = severDecision;
        await api.patch(
          `/api/purchase-orders/${po.po_id}/line-items/${lineItemId}/`,
          payload,
        );
        await reload();
      } catch (e) {
        showError(errorMessage(e, 'Could not change the line item\'s job.'));
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
      showError(errorMessage(e, 'Could not add note.'));
    }
  }

  $effect(() => {
    void params.id;
    loadPO();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if loadError}
  <p><em>Error: {loadError}</em></p>
{:else if po}
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
          prefill={prefilledLine}
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
