<script>
  import { push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { canManageJobs as canManageJobsStore } from '../../stores/permissions.js';

  const { params = {} } = $props();

  let job = $state(null);
  let loading = $state(true);
  let error = $state('');
  let saving = $state(false);

  let name = $state('');
  let description = $state('');
  let dueDate = $state('');
  let customerPoNumber = $state('');
  let projectManager = $state('');
  let users = $state([]);

  const canManageJobs = $derived($canManageJobsStore);

  async function load() {
    loading = true;
    error = '';
    try {
      job = await api.get(`/api/jobs/${params.id}/`);
      name = job.name || '';
      description = job.description || '';
      customerPoNumber = job.customer_po_number || '';
      dueDate = job.due_date ? toDatetimeLocal(job.due_date) : '';
      projectManager = job.project_manager != null ? String(job.project_manager) : '';
      // Only the PM picker (gated behind can_manage_jobs) uses this list.
      if (canManageJobs) {
        try {
          users = await api.get('/api/auth/users/');
        } catch {
          users = [];
        }
      }
    } catch (e) {
      error = e.message || 'Could not load job.';
    } finally {
      loading = false;
    }
  }

  function toDatetimeLocal(iso) {
    const d = new Date(iso);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    saving = true;
    error = '';
    const payload = {
      name,
      description,
      customer_po_number: customerPoNumber,
      due_date: dueDate ? new Date(dueDate).toISOString() : null,
      project_manager: projectManager ? Number(projectManager) : null,
    };
    try {
      await api.patch(`/api/jobs/${params.id}/`, payload);
      push(`/jobs/${params.id}`);
    } catch (err) {
      if (err.data && typeof err.data === 'object' && !err.data.detail) {
        error = Object.entries(err.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = err.message || 'Could not save job.';
      }
    } finally {
      saving = false;
    }
  }

  function handleCancel() {
    push(`/jobs/${params.id}`);
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if error && !job}
  <p class="error">{error}</p>
{:else if !canManageJobs}
  <p>You do not have permission to edit jobs.</p>
{:else if job}
  <h2>Edit Job: {job.job_number}</h2>

  <form onsubmit={handleSubmit}>
    <p>
      <label for="name"><strong>Name</strong></label><br>
      <input id="name" type="text" maxlength="50" bind:value={name}>
    </p>

    <p>
      <label for="description"><strong>Description</strong></label><br>
      <textarea id="description" rows="6" cols="60" bind:value={description}></textarea>
    </p>

    <p>
      <label for="due_date"><strong>Due Date</strong></label><br>
      <input id="due_date" type="datetime-local" bind:value={dueDate}>
    </p>

    <p>
      <label for="customer_po"><strong>Customer PO Number</strong></label><br>
      <input id="customer_po" type="text" maxlength="50" bind:value={customerPoNumber}>
    </p>

    <p>
      <label for="project_manager"><strong>Project Manager</strong></label><br>
      <select id="project_manager" bind:value={projectManager}>
        <option value="">-- None --</option>
        {#each users as u}
          <option value={String(u.id)}>{u.name}</option>
        {/each}
      </select>
    </p>

    <p>
      <button type="submit" disabled={saving}>{saving ? 'Saving...' : 'Save'}</button>
      <button type="button" onclick={handleCancel} disabled={saving}>Cancel</button>
    </p>

    {#if error}<p class="error">{error}</p>{/if}
  </form>
{/if}

<style>
  .error { color: #a8071a; }
</style>
