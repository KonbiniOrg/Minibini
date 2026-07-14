<script>
  import { api } from '../../lib/api.js';
  import { canManageFinancials, canManageConfig } from '../../stores/permissions.js';
  import InventoryItemForm from '../../components/inventory/InventoryItemForm.svelte';
  import StockOrderDialog from '../../components/inventory/StockOrderDialog.svelte';
  import { stockShortfall } from '../../lib/stockShortfall.js';
  import Modal from '../../components/Modal.svelte';
  import CatalogTabs from '../../components/CatalogTabs.svelte';

  // Write access: either the money role or the admin role.
  let canManage = $derived($canManageFinancials || $canManageConfig);

  let items = $state([]);
  let loading = $state(true);
  let error = $state('');

  // Create/edit form state
  let showForm = $state(false);
  let editingItem = $state(null);

  function newItem() { editingItem = null; showForm = true; }
  function editItem(it) { editingItem = it; showForm = true; }
  function onSaved() { showForm = false; editingItem = null; load(); }
  function onCancel() { showForm = false; editingItem = null; }

  // Order dialog: qty prompt (prefilled from shortfall) -> draft-append-or-create
  let orderItem = $state(null);

  // Write-off (irreversible). Opens a small panel to enter how much to waste
  // (defaults to the full on-hand; the Confirm button is the explicit gesture).
  let writeOffItem = $state(null);
  let writeOffQty = $state('');
  let writeOffReason = $state('');
  let writeOffError = $state('');

  function startWriteOff(it) {
    writeOffItem = it;
    writeOffQty = it.qty_on_hand;   // default: whole balance
    writeOffReason = '';
    writeOffError = '';
  }
  function cancelWriteOff() { writeOffItem = null; }

  async function doWriteOff() {
    writeOffError = '';
    const qty = Number(writeOffQty);
    const onHand = Number(writeOffItem.qty_on_hand);
    if (!(qty > 0)) { writeOffError = 'Enter a quantity greater than 0.'; return; }
    if (qty > onHand) { writeOffError = `Only ${writeOffItem.qty_on_hand} on hand.`; return; }
    try {
      await api.post(`/api/inventory/${writeOffItem.inventory_item_id}/write-off/`, {
        qty: writeOffQty, reason: writeOffReason,
      });
      writeOffItem = null;
      load();
    } catch (err) {
      writeOffError = err.message || 'Write-off failed.';
    }
  }

  // Merge (irreversible). Any item can be the discard; the server enforces
  // unit-match rules and an explicit confirm lives here in the UI.
  let showMerge = $state(false);
  let mergeKeep = $state('');
  let mergeDiscard = $state('');
  let mergeError = $state('');
  let lotOptions = $derived(items);

  async function doMerge() {
    mergeError = '';
    if (!mergeKeep || !mergeDiscard) { mergeError = 'Pick both a keep and a discard item.'; return; }
    if (String(mergeKeep) === String(mergeDiscard)) { mergeError = 'Pick two different items.'; return; }
    try {
      await api.post('/api/inventory/merge/', {
        keep_id: mergeKeep, discard_id: mergeDiscard,
      });
      showMerge = false; mergeKeep = ''; mergeDiscard = '';
      load();
    } catch (err) {
      mergeError = err.message || 'Merge failed.';
    }
  }

  // Filters
  let search = $state('');
  let activeOnly = $state(true);

  async function load() {
    loading = true;
    error = '';
    try {
      // Walk every page so the client-side search/filters see the whole catalog.
      // (StandardPagination caps page_size at 100, so a single big request would
      // silently truncate.) We follow `next` by incrementing `page` locally to
      // keep requests proxy-relative.
      const params = new URLSearchParams();
      params.set('page_size', '100');  // the server's max
      if (activeOnly) params.set('is_active', 'true');
      const all = [];
      let page = 1;
      while (page <= 200) {  // safety cap (20k items)
        params.set('page', String(page));
        const data = await api.get('/api/inventory/?' + params.toString());
        if (Array.isArray(data)) { all.push(...data); break; }  // unpaginated fallback
        all.push(...(data.results || []));
        if (!data.next) break;
        page += 1;
      }
      items = all;
    } catch (err) {
      error = err.message || 'Could not load inventory.';
    } finally {
      loading = false;
    }
  }

  // Client-side text filter over the loaded page.
  let shown = $derived(
    !search.trim()
      ? items
      : items.filter((it) => {
          const q = search.trim().toLowerCase();
          return (it.code || '').toLowerCase().includes(q)
            || (it.description || '').toLowerCase().includes(q);
        })
  );

  load();
</script>

<div class="page-body">
<CatalogTabs />

{#if canManage}
  <p>
    {#if !showForm}
      <button type="button" onclick={newItem}>+ New item</button>
      <button type="button" onclick={() => { showMerge = !showMerge; mergeError = ''; }}>
        {showMerge ? 'Cancel merge' : 'Merge items'}
      </button>
    {/if}
  </p>
  <!-- Modal so editing a row far down a long catalog doesn't jump the user
       to a top-of-page form and lose their scroll position. -->
  <Modal open={showForm} onCancel={onCancel} maxWidth="780px">
    <h3>{editingItem ? 'Edit item' : 'New item'}</h3>
    <!-- key on the edited item so the form re-seeds when switching rows -->
    {#key editingItem}
      <InventoryItemForm item={editingItem} {onSaved} {onCancel} />
    {/key}
  </Modal>
  {#if showMerge}
    <div style="border: 1px solid #ccc; padding: 10px; margin-bottom: 10px">
      <h3>Merge items</h3>
      <p>Fold one item's stock and references into a keep item, then delete the
        discard. Units must match.</p>
      {#if mergeError}<p style="color:#c00">{mergeError}</p>{/if}
      <p><label>Keep (survivor):
        <select bind:value={mergeKeep}>
          <option value="">-- select --</option>
          {#each items as it (it.inventory_item_id)}
            <option value={it.inventory_item_id}>{it.code} — {it.description || ''} ({it.units})</option>
          {/each}
        </select></label></p>
      <p><label>Discard (folded in &amp; deleted):
        <select bind:value={mergeDiscard}>
          <option value="">-- select --</option>
          {#each lotOptions as it (it.inventory_item_id)}
            <option value={it.inventory_item_id}>{it.code} — {it.description || ''} ({it.units})</option>
          {/each}
        </select></label></p>
      <p><button type="button" onclick={doMerge}>Merge</button></p>
    </div>
  {/if}
  {#if writeOffItem}
    <div style="border: 1px solid #ccc; padding: 10px; margin-bottom: 10px">
      <h3>Write off — {writeOffItem.code}</h3>
      <p>{writeOffItem.qty_on_hand} {writeOffItem.units} on hand. How many are
        wasted (damaged, mis-cut)? This can't be undone.</p>
      {#if writeOffError}<p style="color:#c00">{writeOffError}</p>{/if}
      <p><label>Quantity to write off:
        <input type="number" step="0.01" min="0" max={writeOffItem.qty_on_hand}
          bind:value={writeOffQty}></label></p>
      <p><label>Reason (optional):
        <input type="text" bind:value={writeOffReason} placeholder="e.g. damaged in storage"></label></p>
      <p>
        <button type="button" onclick={doWriteOff}>Confirm write-off</button>
        <button type="button" onclick={cancelWriteOff}>Cancel</button>
      </p>
    </div>
  {/if}
{/if}

{#if orderItem}
  <StockOrderDialog item={orderItem} prefillQty={stockShortfall(orderItem)}
    onDone={() => { orderItem = null; load(); }}
    onCancel={() => orderItem = null} />
{/if}

<fieldset style="margin-bottom: 10px">
  <legend>Filters</legend>
  <label>Search: <input type="search" bind:value={search} placeholder="code or description"></label>
  <label><input type="checkbox" bind:checked={activeOnly} onchange={load}> Active only</label>
</fieldset>

{#if loading}
  <p><em>Loading...</em></p>
{:else if error}
  <p><em>{error}</em></p>
{:else if shown.length === 0}
  <p><em>No inventory items match.</em></p>
{:else}
  <table class="data-table" style="width: 100%">
    <thead>
      <tr>
        <th>Code</th>
        <th>Description</th>
        <th>Units</th>
        <th style="text-align: right">On hand</th>
        <th style="text-align: right">Earmarked</th>
        <th style="text-align: right">Available</th>
        <th style="text-align: right">On order</th>
        <th>Status</th>
        <th style="text-align: right">Cost</th>
        <th style="text-align: right">Sell</th>
        {#if canManage}<th>Actions</th>{/if}
      </tr>
    </thead>
    <tbody>
      {#each shown as it (it.inventory_item_id)}
        <tr
          class:short={Number(it.qty_available) < 0}
        >
          <td>{it.code}</td>
          <td class="preserve-breaks">{it.description || '—'}</td>
          <td>{it.units}</td>
          <td style="text-align: right">{it.qty_on_hand}</td>
          <td style="text-align: right">{it.qty_earmarked}</td>
          <td style="text-align: right">{it.qty_available}</td>
          <td style="text-align: right">{Number(it.qty_on_order) > 0 ? it.qty_on_order : '—'}</td>
          <td>{it.is_active ? 'active' : 'inactive'}</td>
          <td style="text-align: right">${it.purchase_price}</td>
          <td style="text-align: right">${it.selling_price}</td>
          {#if canManage}
            <td>
              <button type="button" onclick={() => editItem(it)}>edit</button>
              {#if Number(it.qty_on_hand) > 0}
                <button type="button" onclick={() => startWriteOff(it)}>write off</button>
              {/if}
              {#if $canManageFinancials}
                <button type="button" onclick={() => orderItem = it}>order</button>
              {/if}
            </td>
          {/if}
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
</div>

<style>
  /* Available < 0: earmarked exceeds on-hand — oversubscribed / shortfall. */
  .short td {
    background: #fff1f0;
  }
</style>
