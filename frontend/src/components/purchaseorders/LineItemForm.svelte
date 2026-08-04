<script>
  import { api } from '../../lib/api.js';
  import InventoryItemPicker from '../InventoryItemPicker.svelte';
  import UnitsSelect from '../UnitsSelect.svelte';
  import JobPicker from '../JobPicker.svelte';
  import TaskLinkPicker from '../TaskLinkPicker.svelte';

  const {
    categories = [],
    onSubmit,
    onCancel,
    defaultJob = null,
    materialId = null,
    prefill = null,
  } = $props();

  let mode = $state('manual'); // 'manual' or 'pli'
  let selectedPLI = $state(null);
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  let jobId = $state(defaultJob?.job_id ?? null);
  // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
  let jobRow = $state(defaultJob ?? null);

  // Cost→sell task attribution (task-owned-money Phase 5, spec §7 rule 1) —
  // independent of the material `jobId` above: a PO line may serve one
  // job via its material and attribute cost to a task on a DIFFERENT job.
  let taskId = $state(null);

  let form = $state({
    description: '',
    qty: '',
    units: 'none',
    price: '',
    accounting_category: '',
  });

  // Generic prefill when opened via an "order" flow:
  //   { inventory_item?, qty?, description?, price?, accounting_category? }
  // An `inventory_item` switches to 'pli' mode and fills from the item; otherwise
  // the supplied fields seed manual mode. This form knows nothing about Materials
  // — callers build the prefill (e.g. PO detail derives it from a Material for the
  // "order this material" flow, or `{inventory_item}` for the inventory "order").
  $effect(() => {
    if (!prefill) return;
    if (prefill.qty != null && prefill.qty !== '') form.qty = String(prefill.qty);
    if (prefill.inventory_item) {
      mode = 'pli';
      api.get(`/api/inventory/${prefill.inventory_item}/`)
        .then(pli => { handlePLISelect(pli); })
        .catch(() => {
          // Fall back to manual mode if the item fetch fails
          mode = 'manual';
          if (prefill.description != null) form.description = prefill.description;
          if (prefill.price != null) form.price = String(prefill.price);
          if (prefill.accounting_category) form.accounting_category = prefill.accounting_category;
        });
    } else {
      if (prefill.description != null) form.description = prefill.description;
      if (prefill.price != null) form.price = String(prefill.price);
      if (prefill.accounting_category) form.accounting_category = prefill.accounting_category;
    }
  });

  function handlePLISelect(item) {
    selectedPLI = item;
    if (item) {
      form.description = item.description;
      form.units = item.units || 'none';
      form.price = item.purchase_price || '';
      form.accounting_category = item.accounting_category || '';
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    const data = {};

    if (mode === 'pli' && selectedPLI) {
      data.inventory_item = selectedPLI.inventory_item_id;
      data.qty = Number(form.qty);
    } else {
      data.description = form.description;
      data.qty = Number(form.qty);
      data.units = form.units;
      data.price = form.price;
      if (form.accounting_category) {
        data.accounting_category = Number(form.accounting_category);
      }
    }

    if (jobId) {
      data.job = jobId;
    }
    if (materialId) {
      data.material_id = materialId;
    }
    if (taskId) {
      data.task = taskId;
    }

    onSubmit(data);
  }
</script>

<fieldset>
  <legend><strong>Add Line Item</strong></legend>

  <p>
    <label>
      <input type="radio" bind:group={mode} value="manual"> Manual
    </label>
    <label>
      <input type="radio" bind:group={mode} value="pli"> From Inventory
    </label>
  </p>

  <form onsubmit={handleSubmit}>
    {#if mode === 'pli'}
      <p>
        <label><strong>Inventory Item *</strong></label><br>
        <InventoryItemPicker
          value={selectedPLI?.inventory_item_id}
          selectedItem={selectedPLI}
          onSelect={handlePLISelect}
          params={{ is_active: true }}
        />
      </p>
      <p>
        <label for="qty"><strong>Qty *</strong></label><br>
        <input type="number" id="qty" bind:value={form.qty} step="any" min="0" required>
      </p>
    {:else}
      <p>
        <label for="description"><strong>Description *</strong></label><br>
        <input type="text" id="description" bind:value={form.description} required>
      </p>
      <p>
        <label for="qty"><strong>Qty *</strong></label><br>
        <input type="number" id="qty" bind:value={form.qty} step="any" min="0" required>
      </p>
      <p>
        <label for="units"><strong>Units</strong></label><br>
        <UnitsSelect bind:value={form.units} />
      </p>
      <p>
        <label for="price"><strong>Price *</strong></label><br>
        <input type="number" id="price" bind:value={form.price} step="0.01" min="0" required>
      </p>
      <p>
        <label for="accounting_category"><strong>Category</strong></label><br>
        <select id="accounting_category" bind:value={form.accounting_category}>
          <option value="">-- None --</option>
          {#each categories as cat}
            <option value={cat.id}>{cat.name}</option>
          {/each}
        </select>
      </p>
    {/if}

    <p>
      <label><strong>Job (optional)</strong></label><br>
      <JobPicker bind:value={jobId} selectedItem={jobRow} onSelect={(j) => { jobRow = j; }} openOnly />
    </p>

    <p>
      <label><strong>Task Link (optional)</strong></label><br>
      <TaskLinkPicker bind:value={taskId} />
    </p>

    <p>
      <button type="submit">Add</button>
      <button type="button" onclick={onCancel}>Cancel</button>
    </p>
  </form>
</fieldset>
