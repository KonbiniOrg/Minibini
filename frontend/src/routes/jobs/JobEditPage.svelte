<script>
  import { push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import FieldError from '../../components/FieldError.svelte';
  import FormMessage from '../../components/FormMessage.svelte';

  const { params = {} } = $props();

  let job = $state(null);
  let loading = $state(true);
  let error = $state('');
  let saving = $state(false);
  let formError = $state('');
  let fieldErrs = $state({});

  let name = $state('');
  let description = $state('');
  let dueDate = $state('');
  let customerPoNumber = $state('');
  let projectManager = $state('');
  let users = $state([]);

  // Job-scoped management: per-object can_manage (atom-holder OR this job's PM),
  // already ANDed server-side. A PM may edit their own job, including reassigning
  // the PM field. Gate on this alone — not the global atom store.
  const canManageJobs = $derived(job?.can_manage ?? false);

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
      // Only the PM picker (shown when the user may manage this job) uses this list.
      if (job.can_manage) {
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
    formError = '';
    fieldErrs = {};
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
      const t = triageError(err);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message;
        fieldErrs = t.fields;
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
      <FieldError errors={fieldErrs} field="name" />
    </p>

    <p>
      <label for="description"><strong>Description</strong></label><br>
      <textarea id="description" rows="6" cols="60" bind:value={description}></textarea>
      <FieldError errors={fieldErrs} field="description" />
    </p>

    <p>
      <label for="due_date"><strong>Due Date</strong></label><br>
      <input id="due_date" type="datetime-local" bind:value={dueDate}>
      <FieldError errors={fieldErrs} field="due_date" />
    </p>

    <p>
      <label for="customer_po"><strong>Customer PO Number</strong></label><br>
      <input id="customer_po" type="text" maxlength="50" bind:value={customerPoNumber}>
      <FieldError errors={fieldErrs} field="customer_po_number" />
    </p>

    <p>
      <label for="project_manager"><strong>Project Manager</strong></label><br>
      <select id="project_manager" bind:value={projectManager}>
        <option value="">-- None --</option>
        {#each users as u}
          <option value={String(u.id)}>{u.name}</option>
        {/each}
      </select>
      <FieldError errors={fieldErrs} field="project_manager" />
    </p>

    <p>
      <button type="submit" disabled={saving}>{saving ? 'Saving...' : 'Save'}</button>
      <button type="button" onclick={handleCancel} disabled={saving}>Cancel</button>
    </p>

    <FormMessage error={formError} />
  </form>
{/if}

<style>
  .error { color: #a8071a; }
</style>
