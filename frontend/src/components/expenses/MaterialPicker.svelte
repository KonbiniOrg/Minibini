<script>
  import { api } from '../../lib/api.js';

  let {
    // Bound to parent — the selected material id, or null
    materialId = $bindable(null),
    // Bound to parent — if the user inline-creates, these describe the new material
    newMaterial = $bindable(null),
    // Auto-populated from the expense form — used when creating a new material
    defaultDescription = '',
    defaultAmount = '',
  } = $props();

  let jobQuery = $state('');
  let jobResults = $state([]);
  let selectedJob = $state(null);
  let materials = $state([]);        // flattened across all WOs of selected job
  let materialFilter = $state('');
  let loadingMaterials = $state(false);
  let materialsError = $state('');

  let newMatWorkOrderId = $state(null); // the WO on selected job; auto-picked or chosen

  function jobDisplayLabel(j) {
    let label = j.job_number || '';
    if (j.name) label += ` — ${j.name}`;
    if (j.contact_name) label += ` (${j.contact_name})`;
    return label.trim();
  }

  async function searchJobs(e) {
    jobQuery = e.target.value;
    if (jobQuery.length < 2) {
      jobResults = [];
      return;
    }
    const data = await api.get('/api/jobs/?search=' + encodeURIComponent(jobQuery));
    jobResults = (data.results || data).filter(j =>
      !['completed', 'rejected', 'cancelled'].includes(j.status)
    );
  }

  async function pickJob(job) {
    selectedJob = job;
    jobQuery = jobDisplayLabel(job);
    jobResults = [];
    materialId = null;
    newMaterial = null;
    showAddNew = false;
    await loadMaterials(job.job_id || job.id);
  }

  async function loadMaterials(jobId) {
    loadingMaterials = true;
    materialsError = '';
    try {
      // Pull work orders on the job
      const wos = await api.get(`/api/work-orders/?job=${jobId}`);
      const list = wos.results || wos;

      // Flatten materials across all WOs. Each WO has tasks, each task has materials.
      const flat = [];
      for (const wo of list) {
        const detail = await api.get(`/api/work-orders/${wo.work_order_id || wo.id}/`);
        for (const t of (detail.tasks || [])) {
          for (const m of (t.materials || [])) {
            flat.push({
              id: m.material_id || m.id,
              description: m.description,
              task_name: t.description || `Task #${t.task_id || t.id}`,
              quantity: m.quantity,
              unit: m.units,
              work_order_id: wo.work_order_id || wo.id,
            });
          }
        }
      }
      materials = flat;
      // Default new-material parent WO to the first WO on the job
      if (list.length > 0) {
        newMatWorkOrderId = list[0].work_order_id || list[0].id;
      }
    } catch (err) {
      materialsError = err.message || 'Could not load materials.';
    } finally {
      loadingMaterials = false;
    }
  }

  function pickMaterial(m) {
    materialId = m.id;
    newMaterial = null;
    showAddNew = false;
  }

  function addNewMaterial() {
    materialId = null;
    newMaterial = {
      work_order_id: newMatWorkOrderId,
      description: defaultDescription || '',
      quantity: 1,
      price: defaultAmount || '',
    };
  }

  function clearNewMaterial() {
    newMaterial = null;
  }

  let filteredMaterials = $derived(
    materialFilter
      ? materials.filter(m =>
          (m.description || '').toLowerCase().includes(materialFilter.toLowerCase())
          || (m.task_name || '').toLowerCase().includes(materialFilter.toLowerCase())
        )
      : materials
  );
</script>

<fieldset>
  <legend><strong>Link to job (optional)</strong></legend>

  <p>
    <label for="mp-job">Job</label><br>
    <input
      id="mp-job"
      type="text"
      bind:value={jobQuery}
      oninput={searchJobs}
      placeholder="Type job number or customer name"
    >
  </p>

  {#if jobResults.length > 0}
    <ul>
      {#each jobResults as j (j.job_id || j.id)}
        <li><button type="button" onclick={() => pickJob(j)}>
          {jobDisplayLabel(j)}
        </button></li>
      {/each}
    </ul>
  {/if}

  {#if selectedJob}
    <p>
      <label for="mp-filter">Material on this job</label><br>
      <input
        id="mp-filter"
        type="text"
        bind:value={materialFilter}
        placeholder="Filter materials..."
      >
    </p>

    {#if loadingMaterials}
      <p><em>Loading materials...</em></p>
    {:else if materialsError}
      <p><em>{materialsError}</em></p>
    {:else}
      <div style="border: 1px solid #999; padding: 6px; max-height: 180px; overflow-y: auto">
        {#each filteredMaterials as m (m.id)}
          <div
            style="padding: 4px; border-bottom: 1px solid #ddd; cursor: pointer; background: {materialId === m.id ? '#e8f0fe' : 'transparent'}"
            onclick={() => pickMaterial(m)}
          >
            <strong>{m.description}</strong> — Task: <em>{m.task_name}</em>
            {#if m.quantity} — qty {m.quantity}{/if}
          </div>
        {/each}
        {#if !newMaterial}
          <div
            style="padding: 4px; color: #1a66ff; cursor: pointer"
            onclick={addNewMaterial}
          >
            + Add new material
          </div>
        {/if}
      </div>
    {/if}

    {#if newMaterial}
      <p>
        <em>New material: {newMaterial.description || '(no description)'}</em>
        — <button type="button" onclick={clearNewMaterial} style="font-size: 12px">remove</button>
      </p>
    {/if}
  {/if}
</fieldset>
