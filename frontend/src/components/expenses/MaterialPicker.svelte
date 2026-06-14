<script>
  import { api } from '../../lib/api.js';

  let {
    // The chosen job's id (owned by the parent form — the cost anchor).
    jobId = null,
    // Bound to parent — the selected existing material id, or null.
    materialId = $bindable(null),
    // Bound to parent — if the user inline-creates, describes the new material.
    newMaterial = $bindable(null),
    defaultDescription = '',
    defaultAmount = '',
  } = $props();

  let materials = $state([]);
  let loading = $state(false);
  let loadError = $state('');
  let loadedJobId = $state(null);

  // Load the chosen job's materials. Switching to a *different* job invalidates
  // any prior material selection; the initial load (edit mode) does not clear.
  $effect(() => {
    const jid = jobId;
    if (jid && jid !== loadedJobId) {
      const wasLoaded = loadedJobId;
      loadedJobId = jid;
      if (wasLoaded !== null) {
        materialId = null;
        newMaterial = null;
      }
      loadMaterials(jid);
    } else if (!jid) {
      materials = [];
      loadedJobId = null;
    }
  });

  async function loadMaterials(id) {
    loading = true;
    loadError = '';
    try {
      // job.materials is the complete list (task-attached and job-level).
      const job = await api.get(`/api/jobs/${id}/`);
      materials = (job.materials || []).map((m) => ({
        id: m.material_id || m.id,
        description: m.description,
        quantity: m.quantity,
        unit: m.units,
      }));
    } catch (err) {
      loadError = err.message || 'Could not load materials.';
    } finally {
      loading = false;
    }
  }

  function pickMaterial(m) {
    materialId = m.id;
    newMaterial = null;
  }

  function clearMaterial() {
    materialId = null;
  }

  function addNewMaterial() {
    materialId = null;
    newMaterial = {
      job_id: jobId,
      description: defaultDescription || '',
      quantity: 1,
      price: defaultAmount || '',
    };
  }

  function clearNewMaterial() {
    newMaterial = null;
  }
</script>

<fieldset>
  <legend><strong>Link a material (optional)</strong></legend>

  {#if !jobId}
    <p><em>Choose a job above to link a material. The expense is recorded
      against the job either way.</em></p>
  {:else if loading}
    <p><em>Loading materials…</em></p>
  {:else if loadError}
    <p><em>{loadError}</em></p>
  {:else}
    <div style="border: 1px solid #999; padding: 6px; max-height: 180px; overflow-y: auto">
      {#each materials as m (m.id)}
        <button
          type="button"
          aria-pressed={materialId === m.id}
          style="display: block; width: 100%; text-align: left; border: none; border-bottom: 1px solid #ddd; padding: 4px; font: inherit; cursor: pointer; background: {materialId === m.id ? '#e8f0fe' : 'transparent'}"
          onclick={() => pickMaterial(m)}
        >
          <strong>{m.description || '(no description)'}</strong>
          {#if m.quantity} — qty {m.quantity}{/if}
        </button>
      {/each}
      {#if !newMaterial}
        <button
          type="button"
          style="display: block; width: 100%; text-align: left; border: none; background: transparent; padding: 4px; font: inherit; color: #1a66ff; cursor: pointer"
          onclick={addNewMaterial}
        >
          + Add new material
        </button>
      {/if}
    </div>

    {#if materialId}
      <p><em>Linked to an existing material.</em>
        <button type="button" onclick={clearMaterial} style="font-size: 12px">unlink</button></p>
    {/if}
    {#if newMaterial}
      <p><em>New material: {newMaterial.description || '(no description)'}</em>
        — <button type="button" onclick={clearNewMaterial} style="font-size: 12px">remove</button></p>
    {/if}
  {/if}
</fieldset>
