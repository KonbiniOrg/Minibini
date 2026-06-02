<script>
  import { api } from '../../lib/api.js';
  import { push } from 'svelte-spa-router';
  import { user as userStore } from '../../stores/auth.js';

  const { params = {} } = $props();

  const canManageJobs = $derived(
    $userStore?.permissions?.includes('can_manage_jobs') ?? false
  );

  let sourceJob = $state(null);
  let contacts = $state([]);
  let selectedContactId = $state('');
  let path = $state('approved');
  let loading = $state(true);
  let loadError = $state(null);
  let submitting = $state(false);
  let contactPrefilled = $state(false);

  async function load() {
    loading = true;
    loadError = null;
    contactPrefilled = false;
    try {
      sourceJob = await api.get(`/api/jobs/${params.id}/`);
      const page = await api.get('/api/contacts/?page_size=100');
      contacts = page.results || [];
    } catch (e) {
      loadError = e.message || 'Failed to load job';
    } finally {
      loading = false;
    }
  }

  async function submit() {
    submitting = true;
    try {
      const result = await api.post(`/api/jobs/${params.id}/duplicate/`, {
        contact_id: selectedContactId,
        path,
      });
      push(`/jobs/${result.job_id}`);
    } catch (e) {
      // api.js renders the error overlay; just re-enable the button.
      submitting = false;
    }
  }

  $effect(() => {
    void params.id;
    load();
  });

  // Apply the source job's contact as the initial dropdown selection once the
  // form (and its <option>s) have actually rendered. Doing this in an effect —
  // rather than inside load() before `loading` flips — guarantees the options
  // exist in the DOM, avoiding the <select bind:value> mount race that left the
  // dropdown unselected. The one-shot guard preserves a later manual change.
  $effect(() => {
    if (!loading && !loadError && canManageJobs && sourceJob
        && contacts.length && !contactPrefilled) {
      selectedContactId = sourceJob.contact ? String(sourceJob.contact) : '';
      contactPrefilled = true;
    }
  });
</script>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p><strong>Error:</strong> {loadError}</p>
{:else if !canManageJobs}
  <p>You do not have permission to duplicate jobs.</p>
{:else}
  <h2>Duplicate {sourceJob.job_number}</h2>

  <p><label for="contact"><strong>Customer *</strong></label><br>
    <select id="contact" bind:value={selectedContactId} required>
      <option value="">-- Select contact --</option>
      {#each contacts as c}
        <option value={String(c.contact_id)}>
          {c.business ? `${c.name} from ${c.business.business_name}` : c.name}
        </option>
      {/each}
    </select>
  </p>

  <fieldset>
    <legend><strong>What kind of copy?</strong></legend>
    <p><label>
      <input type="radio" name="path" value="approved" bind:group={path}>
      Immediately approved — ready to work, reuses the original's pricing as-is.
    </label></p>
    <p><label>
      <input type="radio" name="path" value="estimate" bind:group={path}>
      Requires a new estimate — re-quote before work starts.
    </label></p>
    <p><em>If rates or material prices may have moved since the original, choose
      "Requires a new estimate" to re-quote.</em></p>
  </fieldset>

  <p>
    <button type="button" onclick={submit}
            disabled={submitting || !selectedContactId}>
      {submitting ? 'Duplicating…' : 'Duplicate'}
    </button>
    <a href="#/jobs/{params.id}">Cancel</a>
  </p>
{/if}
