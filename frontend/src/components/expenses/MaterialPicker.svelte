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
  let materials = $state([]);        // flattened across tasks of selected job
  let loadingMaterials = $state(false);
  let materialsError = $state('');

  let newMatJobId = $state(null); // the selected job id

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
    await loadMaterials(job.job_id || job.id);
  }

  async function loadMaterials(jobId) {
    loadingMaterials = true;
    materialsError = '';
    try {
      // Fetch the job with its nested tasks
      const job = await api.get(`/api/jobs/${jobId}/`);
      newMatJobId = job.job_id || jobId;

      // Flatten materials across the job's tasks. Task materials aren't embedded
      // in the job serializer, so fetch them per-task via /api/tasks/{id}/materials/.
      const flat = [];
      for (const t of (job.tasks || [])) {
        const taskId = t.task_id || t.id;
        const taskName = t.name || t.description || `Task #${taskId}`;
        try {
          const mats = await api.get(`/api/tasks/${taskId}/materials/`);
          const matList = mats.results || mats;
          for (const m of matList) {
            flat.push({
              id: m.material_id || m.id,
              description: m.description,
              task_name: taskName,
              quantity: m.quantity,
              unit: m.units,
              job_id: newMatJobId,
            });
          }
        } catch (e) {
          console.warn(`Could not fetch materials for task ${taskId}:`, e.message);
        }
      }
      materials = flat;
    } catch (err) {
      materialsError = err.message || 'Could not load materials.';
    } finally {
      loadingMaterials = false;
    }
  }

  function pickMaterial(m) {
    materialId = m.id;
    newMaterial = null;
  }

  function addNewMaterial() {
    materialId = null;
    newMaterial = {
      job_id: newMatJobId,
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
    <p><strong>Material on this job</strong></p>

    {#if loadingMaterials}
      <p><em>Loading materials...</em></p>
    {:else if materialsError}
      <p><em>{materialsError}</em></p>
    {:else}
      <div style="border: 1px solid #999; padding: 6px; max-height: 180px; overflow-y: auto">
        {#each materials as m (m.id)}
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
