<script>
  import { api } from '../../lib/api.js';
  import BusinessPicker from '../BusinessPicker.svelte';

  const {
    po = null,
    businesses = [],
    onSubmit,
    onCancel,
    errors = null,
    contextJob = null,
  } = $props();

  let form = $state({
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    business: po?.business ?? null,
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    contact: po?.contact || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    requested_date: po?.requested_date || '',
  });

  let contactsForBusiness = $state([]);
  let loadingContacts = $state(false);
  let lastFetchedBusiness = form.business;
  let pickedBusiness = $state(null);

  function getDefaultContactId(businessId) {
    if (pickedBusiness && String(pickedBusiness.business_id) === String(businessId)) {
      return pickedBusiness.default_contact || null;
    }
    const biz = businesses.find(b => String(b.business_id) === String(businessId));
    return biz?.default_contact || null;
  }

  async function fetchContactsAndAutoSelect(businessId, autoSelect) {
    if (!businessId) {
      contactsForBusiness = [];
      return;
    }
    loadingContacts = true;
    try {
      const data = await api.get(`/api/contacts/?business=${businessId}&page_size=100`);
      contactsForBusiness = data.results || [];
      if (autoSelect) {
        const defaultId = getDefaultContactId(businessId);
        if (defaultId && contactsForBusiness.some(c => c.contact_id === defaultId)) {
          form.contact = defaultId;
        } else if (contactsForBusiness.length > 0) {
          form.contact = contactsForBusiness[0].contact_id;
        }
      }
    } catch (e) {
      console.error('Failed to fetch contacts for business', businessId, e);
      contactsForBusiness = [];
    } finally {
      loadingContacts = false;
    }
  }

  $effect(() => {
    const biz = form.business;
    if (biz === lastFetchedBusiness) return;
    lastFetchedBusiness = biz;
    fetchContactsAndAutoSelect(biz, true);
  });

  // Initial load for edit mode
  if (form.business) {
    fetchContactsAndAutoSelect(form.business, false);
  }

  function handleSubmit(e) {
    e.preventDefault();
    const data = { ...form };
    if (data.business === '' || data.business == null) {
      data.business = null;
    } else {
      data.business = Number(data.business);
    }
    if (data.contact === '') {
      data.contact = null;
    } else {
      data.contact = Number(data.contact);
    }
    if (data.requested_date === '') {
      data.requested_date = null;
    }
    onSubmit(data);
  }
</script>

<form onsubmit={handleSubmit}>
  {#if errors}
    <p><strong>Error:</strong> {errors}</p>
  {/if}

  {#if contextJob}
    <p><strong>For job: <a href="#/jobs/{contextJob.job_id}">{contextJob.job_number}</a></strong></p>
  {/if}

  <p>
    <label><strong>Vendor (Business) *</strong></label><br>
    <!-- business is a numeric id on the PO; label resolves via id fetch (no nested object to pass) -->
    <BusinessPicker bind:value={form.business}
      selectedItem={null}
      onSelect={(b) => { pickedBusiness = b; }} />
  </p>

  <p>
    <label for="contact"><strong>Contact *</strong></label><br>
    <select id="contact" bind:value={form.contact} disabled={loadingContacts} required>
      {#if loadingContacts}
        <option value="">-- Loading... --</option>
      {:else if contactsForBusiness.length === 0}
        <option value="">-- Select a business first --</option>
      {:else}
        {#each contactsForBusiness as c}
          <option value={c.contact_id}>{c.first_name} {c.last_name}</option>
        {/each}
      {/if}
    </select>
  </p>

  <p>
    <label for="requested_date"><strong>Requested Date</strong></label><br>
    <input type="date" id="requested_date" bind:value={form.requested_date}>
  </p>

  <p>
    <button type="submit">{po ? 'Save' : 'Create'}</button>
    <button type="button" onclick={onCancel}>Cancel</button>
  </p>
</form>
