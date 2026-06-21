<script>
  // What an expense bought (optional). Inventoried PLI → a stock purchase
  // (adds to inventory; cost flows at consumption). Freeform / non-inventoried
  // PLI → a consumable material at the entered unit cost. Expenses never link to
  // an existing material — this only creates new ones.
  import InventoryItemPicker from '../InventoryItemPicker.svelte';

  let {
    jobId = null,
    newMaterial = $bindable(null),
    defaultDescription = '',
    defaultAmount = '',
  } = $props();

  let adding = $state(false);
  let pli = $state(null);          // selected PLI object, or null (freeform)
  let description = $state('');
  let quantity = $state(1);
  let unitCost = $state('');

  let isStock = $derived(!!(pli && pli.is_inventoried));

  function startAdd() {
    adding = true;
    description = defaultDescription || '';
    unitCost = defaultAmount || '';
  }
  function removeItem() {
    adding = false; pli = null; description = ''; quantity = 1; unitCost = '';
  }
  function onPli(item) {
    pli = item;
    if (item && item.description) description = item.description;
  }

  // Keep the bound newMaterial in sync while drafting (job_id is injected by the
  // parent form, which owns the job).
  $effect(() => {
    if (!adding || !jobId) { newMaterial = null; return; }
    if (isStock) {
      newMaterial = {
        inventory_item_id: pli.inventory_item_id,
        quantity: Number(quantity) || 1,
      };
    } else {
      newMaterial = {
        inventory_item_id: pli ? pli.inventory_item_id : null,
        description,
        quantity: Number(quantity) || 1,
        price: unitCost === '' ? null : unitCost,
      };
    }
  });
</script>

<fieldset>
  <legend><strong>Purchased item (optional)</strong></legend>

  {#if !jobId}
    <p><em>Choose a job above to record what this bought. The expense is recorded
      against the job either way.</em></p>
  {:else if !adding}
    <button type="button" onclick={startAdd}>+ Add a purchased item</button>
  {:else}
    <p>
      <label for="mp-pli">Price list item</label><br>
      <InventoryItemPicker onSelect={onPli} params={{ is_active: true }} />
    </p>

    {#if isStock}
      <p><em>Inventoried item — recorded as a <strong>stock purchase</strong>
        (adds to inventory; its cost is charged when the job consumes it).</em></p>
      <p>
        <label for="mp-qty">Quantity</label><br>
        <input id="mp-qty" type="number" min="0" step="0.01" bind:value={quantity}>
      </p>
    {:else}
      {#if !pli}
        <p>
          <label for="mp-desc">Item description</label><br>
          <input id="mp-desc" type="text" bind:value={description}>
        </p>
      {/if}
      <p>
        <label for="mp-qty">Quantity</label><br>
        <input id="mp-qty" type="number" min="0" step="0.01" bind:value={quantity}>
      </p>
      <p>
        <label for="mp-cost">Unit cost</label><br>
        <input id="mp-cost" type="number" min="0" step="0.01" bind:value={unitCost}>
      </p>
    {/if}

    <p><button type="button" onclick={removeItem}>remove item</button></p>
  {/if}
</fieldset>
