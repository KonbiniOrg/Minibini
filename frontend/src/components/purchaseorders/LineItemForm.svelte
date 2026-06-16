<script>
  import { api } from '../../lib/api.js';
  import PriceListItemPicker from '../PriceListItemPicker.svelte';
  import UnitsSelect from '../UnitsSelect.svelte';
  import JobPicker from '../JobPicker.svelte';

  const {
    categories = [],
    onSubmit,
    onCancel,
    defaultJob = null,
    materialId = null,
    prefillMaterial = null,
  } = $props();

  let mode = $state('manual'); // 'manual' or 'pli'
  let selectedPLI = $state(null);
  let selectedJob = $state(defaultJob);

  let form = $state({
    description: '',
    qty: '',
    units: 'none',
    price: '',
    accounting_category: '',
  });

  // Pre-populate from a Material when this form was opened via the
  // "Order this material" flow. PLI-backed materials switch to 'pli' mode
  // (and fetch the PLI to fill description/units/price); PLI-less materials
  // stay in manual mode and copy description/qty/unit_cost.
  $effect(() => {
    if (!prefillMaterial) return;
    form.qty = String(prefillMaterial.quantity ?? '');
    if (prefillMaterial.price_list_item) {
      mode = 'pli';
      api.get(`/api/inventory/${prefillMaterial.price_list_item}/`)
        .then(pli => { handlePLISelect(pli); })
        .catch(() => {
          // Fall back to manual mode if PLI fetch fails
          mode = 'manual';
          form.description = prefillMaterial.description || '';
          form.price = String(prefillMaterial.unit_cost ?? '');
        });
    } else {
      form.description = prefillMaterial.description || '';
      form.price = String(prefillMaterial.unit_cost ?? '');
      if (prefillMaterial.accounting_category) {
        form.accounting_category = prefillMaterial.accounting_category;
      }
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
      data.price_list_item = selectedPLI.price_list_item_id;
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

    if (selectedJob?.job_id) {
      data.job = selectedJob.job_id;
    }
    if (materialId) {
      data.material_id = materialId;
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
      <input type="radio" bind:group={mode} value="pli"> From Price List
    </label>
  </p>

  <form onsubmit={handleSubmit}>
    {#if mode === 'pli'}
      <p>
        <label><strong>Price List Item *</strong></label><br>
        <PriceListItemPicker
          value={selectedPLI?.price_list_item_id}
          selectedItem={selectedPLI}
          onSelect={handlePLISelect}
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
      <JobPicker bind:value={selectedJob} />
    </p>

    <p>
      <button type="submit">Add</button>
      <button type="button" onclick={onCancel}>Cancel</button>
    </p>
  </form>
</fieldset>
