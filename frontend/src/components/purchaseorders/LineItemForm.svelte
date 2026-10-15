<script>
  import { api } from '../../lib/api.js';
  import InventoryItemPicker from '../InventoryItemPicker.svelte';
  import UnitsSelect from '../UnitsSelect.svelte';
  import JobPicker from '../JobPicker.svelte';
  import TaskLinkPicker from '../TaskLinkPicker.svelte';

  const { categories = [], onSubmit, onCancel } = $props();

  let mode = $state('manual'); // 'manual' or 'pli'
  let selectedPLI = $state(null);
  let jobId = $state(null);
  let jobRow = $state(null);
  // Explicit material picker (PO order flow §5.3): once a job is chosen and
  // no task is picked, list its pending unlinked materials and make the
  // attach-or-create choice explicit. Null = nothing chosen yet.
  let jobMaterials = $state(null);   // null = loading / no job
  let materialChoice = $state(null); // null | material_id | 'new'
  let itemLocked = $state(false);

  // Cost→sell task attribution (outsourced-work port, spec §7 rule 1),
  // cascading from the ONE Job picker above (PO Job/Task consolidation,
  // RM 2026-09-21 — this form used to have a second, independent Job
  // picker feeding TaskLinkPicker's own cascade, which let a caller fill
  // BOTH and crash at save; see docs/designs/materials-inventory-and-
  // purchasing.md §10a). A task pick means "pure cost attribution" — the
  // task implies its job, so `job` is withheld from the payload and no
  // Material is ever created for this line.
  let taskId = $state(null);

  let form = $state({
    description: '',
    qty: '',
    units: 'none',
    price: '',
    accounting_category: '',
  });
  let isComment = $state(false);

  function isAttachable(m) {
    return m.consumption_state === 'pending' && m.po_line_item_id == null
      && m.cost_source !== 'customer_supplied';
  }

  $effect(() => {
    const id = jobId;
    materialChoice = null;
    itemLocked = false;
    jobMaterials = null;
    if (!id) return;
    api.get(`/api/jobs/${id}/`)
      .then((job) => { if (jobId === id) jobMaterials = (job.materials || []).filter(isAttachable); })
      .catch(() => { if (jobId === id) jobMaterials = []; });
  });

  async function chooseMaterial(value) {
    materialChoice = value;
    itemLocked = false;
    if (value === 'new' || mode !== 'pli') return;
    const m = jobMaterials.find((x) => x.material_id === value);
    if (!m?.inventory_item) return;   // provisional: the user still picks the item
    const item = await api.get(`/api/inventory/${m.inventory_item}/`);
    handlePLISelect(item);
    itemLocked = true;
  }

  const materialChoiceNeeded = $derived(
    !isComment && !!jobId && !taskId && (jobMaterials?.length ?? 0) > 0 && materialChoice == null);

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
    } else if (isComment) {
      data.description = form.description;
      data.is_comment = true;
      data.qty = 0;
      data.units = 'none';
      data.price = 0;
    } else {
      data.description = form.description;
      data.qty = Number(form.qty);
      data.units = form.units;
      data.price = form.price;
      if (form.accounting_category) {
        data.accounting_category = Number(form.accounting_category);
      }
    }

    // Task picked -> pure cost-attribution line: send `task`, withhold
    // `job`/`material_id` entirely. Otherwise the explicit material choice
    // decides: attach (material_id) or create a new material (job).
    if (taskId) {
      data.task = taskId;
    } else if (jobId && !isComment) {
      if (materialChoice && materialChoice !== 'new') data.material_id = materialChoice;
      else data.job = jobId;
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
          disabled={itemLocked}
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
        <label>
          <input type="checkbox" bind:checked={isComment}
            onchange={(e) => { if (e.target.checked) { jobId = null; jobRow = null; taskId = null; } }}>
          Comment line (informational only — no charge)
        </label>
      </p>
      {#if !isComment}
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
            {#each categories.filter((c) => !c.is_fallback) as cat}
              <option value={cat.id}>{cat.name}</option>
            {/each}
          </select>
        </p>
      {/if}
    {/if}

    <p>
      <label><strong>Job (optional)</strong></label><br>
      <JobPicker bind:value={jobId} selectedItem={jobRow} onSelect={(j) => { jobRow = j; }} openOnly disabled={isComment} />
    </p>

    {#if jobId}
      <p>
        <label><strong>Task Link (optional)</strong></label><br>
        <TaskLinkPicker bind:value={taskId} job={jobId} />
        {#if taskId}
          <br><small>Cost will be attributed to this task — no material is created.</small>
        {/if}
      </p>
      {#if !taskId && !isComment}
        {#if jobMaterials === null}
          <p><small>Loading materials…</small></p>
        {:else if jobMaterials.length === 0}
          <p><small>No unordered materials on this job — a new material will be created.</small></p>
        {:else}
          <fieldset class="material-choice">
            <legend><strong>Attach to a material</strong></legend>
            {#each jobMaterials as m (m.material_id)}
              <label>
                <input type="radio" name="material-choice" value={m.material_id}
                  checked={materialChoice === m.material_id} onchange={() => chooseMaterial(m.material_id)}>
                {#if m.item_code && !m.item_code.startsWith('LOT-')}{m.item_code + ' · '}{/if}{String(Number(m.quantity))} {m.units} · {m.description}
              </label>
            {/each}
            <label>
              <input type="radio" name="material-choice" value="new"
                checked={materialChoice === 'new'} onchange={() => chooseMaterial('new')}>
              Create a new material for this line
            </label>
          </fieldset>
        {/if}
      {/if}
    {/if}

    <p>
      <button type="submit" disabled={materialChoiceNeeded}>Add</button>
      <button type="button" onclick={onCancel}>Cancel</button>
    </p>
  </form>
</fieldset>

<style>
  .material-choice label { display: block; }
</style>
