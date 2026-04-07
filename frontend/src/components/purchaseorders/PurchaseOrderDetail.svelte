<script>
  import UnitsSelect from '../UnitsSelect.svelte';

  const {
    po,
    canManageFinancials = false,
    busy = false,
    onIssue = null,
    onCancel = null,
    onDelete = null,
    onDeleteLineItem = null,
    onReorder = null,
    onEditLineItem = null,
  } = $props();

  let lineItems = $derived(
    (po.line_items || []).slice().sort((a, b) => a.line_number - b.line_number)
  );

  let total = $derived(
    lineItems.reduce((sum, li) => sum + Number(li.qty) * Number(li.price), 0)
  );

  let editingId = $state(null);
  let editForm = $state({});

  function formatDate(d) {
    if (!d) return '—';
    return new Date(d).toLocaleDateString();
  }

  function moveUp(index) {
    if (index === 0 || !onReorder) return;
    const ids = lineItems.map(li => li.line_item_id);
    [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]];
    onReorder(ids);
  }

  function moveDown(index) {
    if (index >= lineItems.length - 1 || !onReorder) return;
    const ids = lineItems.map(li => li.line_item_id);
    [ids[index], ids[index + 1]] = [ids[index + 1], ids[index]];
    onReorder(ids);
  }

  function startEdit(li) {
    editingId = li.line_item_id;
    editForm = {
      description: li.description,
      qty: li.qty,
      units: li.units || 'none',
      price: li.price,
    };
  }

  function cancelEdit() {
    editingId = null;
    editForm = {};
  }

  function saveEdit() {
    if (onEditLineItem) {
      onEditLineItem(editingId, {
        description: editForm.description,
        qty: Number(editForm.qty),
        units: editForm.units,
        price: editForm.price,
      });
    }
    editingId = null;
    editForm = {};
  }

  let isReceiving = $derived(
    po.status === 'partly_received' || po.status === 'received_in_full'
  );
</script>

<h2>Purchase Order {po.po_number}</h2>

<div class="status-line">
  <span class="status-badge status-{po.status}">{po.status.replace(/_/g, ' ')}</span>
</div>

<p><strong>Vendor:</strong>
  {#if po.business}
    <a href="#/businesses/{po.business}">{po.business_name}</a>
  {:else}
    —
  {/if}
</p>
{#if po.contact}
  <p><strong>Contact:</strong> <a href="#/contacts/{po.contact}">{po.contact_name || `Contact #${po.contact}`}</a></p>
{/if}
<p><strong>Created:</strong> {formatDate(po.created_date)}</p>
{#if po.requested_date}
  <p><strong>Requested:</strong> {formatDate(po.requested_date)}</p>
{/if}
{#if po.issued_date}
  <p><strong>Issued:</strong> {formatDate(po.issued_date)}</p>
{/if}
{#if po.received_date}
  <p><strong>Received:</strong> {formatDate(po.received_date)}</p>
{/if}
{#if po.cancel_date}
  <p><strong>Cancelled:</strong> {formatDate(po.cancel_date)}</p>
{/if}

{#if canManageFinancials}
  <div class="action-bar">
    {#if po.status === 'draft'}
      <a href="#/purchase-orders/{po.po_id}/edit"><button disabled={busy}>Edit</button></a>
      <button onclick={onIssue} disabled={busy || !lineItems.length}>Mark as Issued</button>
      <button onclick={onDelete} disabled={busy}>Delete</button>
    {/if}
    {#if po.status === 'issued'}
      <button onclick={onCancel} disabled={busy}>Cancel</button>
    {/if}
  </div>
{/if}

<h3>Line Items</h3>
{#if lineItems.length === 0}
  <p>No line items.</p>
{:else}
  <table border="1">
    <thead>
      <tr>
        <th>#</th>
        <th>Description</th>
        <th class="text-right">Qty</th>
        <th>Units</th>
        <th class="text-right">Price</th>
        <th class="text-right">Total</th>
        {#if isReceiving}
          <th class="text-right">Received</th>
        {/if}
        {#if canManageFinancials && po.status === 'draft'}
          <th>Actions</th>
        {/if}
      </tr>
    </thead>
    <tbody>
      {#each lineItems as li, i}
        {#if editingId === li.line_item_id}
          <tr>
            <td>{li.line_number}</td>
            <td><input type="text" bind:value={editForm.description} style="width:100%;box-sizing:border-box;"></td>
            <td><input type="number" bind:value={editForm.qty} step="any" min="0" style="width:70px;text-align:right;"></td>
            <td><UnitsSelect bind:value={editForm.units} /></td>
            <td><input type="number" bind:value={editForm.price} step="0.01" min="0" style="width:80px;text-align:right;"></td>
            <td class="text-right">${(Number(editForm.qty) * Number(editForm.price)).toFixed(2)}</td>
            <td>
              <button onclick={saveEdit}>Save</button>
              <button onclick={cancelEdit}>Cancel</button>
            </td>
          </tr>
        {:else}
          <tr>
            <td>{li.line_number}</td>
            <td>{li.description}</td>
            <td class="text-right">{li.qty}</td>
            <td>{li.units || ''}</td>
            <td class="text-right">${Number(li.price).toFixed(2)}</td>
            <td class="text-right">${(Number(li.qty) * Number(li.price)).toFixed(2)}</td>
            {#if isReceiving}
              <td class="text-right">
                {#if li.qty_received}
                  {li.qty_received}
                  {#if li.received_date}
                    <br><small>{formatDate(li.received_date)}</small>
                  {/if}
                {:else}
                  —
                {/if}
              </td>
            {/if}
            {#if canManageFinancials && po.status === 'draft'}
              <td>
                <button onclick={() => startEdit(li)}>Edit</button>
                <button onclick={() => moveUp(i)} disabled={i === 0}>&#9650;</button>
                <button onclick={() => moveDown(i)} disabled={i === lineItems.length - 1}>&#9660;</button>
                <button onclick={() => onDeleteLineItem(li)}>Delete</button>
              </td>
            {/if}
          </tr>
        {/if}
      {/each}
    </tbody>
    <tfoot>
      <tr>
        <td colspan="5" class="text-right"><strong>Total</strong></td>
        <td class="text-right"><strong>${total.toFixed(2)}</strong></td>
        {#if isReceiving}
          <td></td>
        {/if}
        {#if canManageFinancials && po.status === 'draft'}
          <td></td>
        {/if}
      </tr>
    </tfoot>
  </table>
{/if}

<style>
  .text-right { text-align: right; }
  .status-line { margin-bottom: 12px; }
  .status-badge {
    padding: 4px 12px; border-radius: 12px; font-size: 13px;
    font-weight: 600; text-transform: capitalize;
  }
  .status-draft { background: #f3f4f6; color: #374151; }
  .status-issued { background: #dbeafe; color: #1e40af; }
  .status-partly_received { background: #fef3c7; color: #92400e; }
  .status-received_in_full { background: #d1fae5; color: #065f46; }
  .status-cancelled { background: #fee2e2; color: #991b1b; }
  .action-bar { display: flex; gap: 8px; margin: 12px 0; }
  .action-bar button {
    padding: 6px 14px; border: 1px solid #d1d5db; border-radius: 4px;
    background: #fff; cursor: pointer; font-size: 13px;
  }
  .action-bar button:hover { background: #f3f4f6; }
  .action-bar button:disabled { opacity: 0.5; cursor: default; }
  small { color: #666; }
</style>
