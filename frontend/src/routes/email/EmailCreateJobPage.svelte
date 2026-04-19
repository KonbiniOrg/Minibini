<script>
  import { api } from '../../lib/api.js';
  import { emailApi } from '../../lib/email.js';
  import { push } from 'svelte-spa-router';

  const { params = {} } = $props();

  let loading = $state(true);
  let loadError = $state(null);
  let senderInfo = $state(null);

  // Decision state. 'mode' is one of: 'existing' | 'new'.
  let mode = $state('existing');
  let selectedContactId = $state('');   // when mode=existing
  let jobName = $state('');

  // New-contact form fields (mode=new)
  let contactForm = $state({
    first_name: '',
    last_name: '',
    email: '',
    mobile_number: '',
    work_number: '',
    home_number: '',
  });
  // Business handling for new contact: 'none' | 'existing' | 'new'
  let businessMode = $state('none');
  let selectedBusinessId = $state('');
  let newBusinessName = $state('');

  let submitting = $state(false);
  let submitError = $state(null);

  async function load() {
    loading = true;
    loadError = null;
    try {
      senderInfo = await emailApi.senderInfo(params.id);

      const matches = senderInfo.matching_contacts || [];
      if (matches.length === 1) {
        mode = 'existing';
        selectedContactId = String(matches[0].id);
      } else if (matches.length === 0) {
        mode = 'new';
        const [firstName, ...rest] = (senderInfo.sender_name || '').split(' ');
        contactForm.first_name = firstName || '';
        contactForm.last_name = rest.join(' ');
        contactForm.email = senderInfo.sender_email || '';

        const bizMatches = senderInfo.matching_businesses || [];
        if (bizMatches.length > 0) {
          businessMode = 'existing';
          selectedBusinessId = String(bizMatches[0].id);
        } else if (senderInfo.extracted_company) {
          businessMode = 'new';
          newBusinessName = senderInfo.extracted_company;
        }
      } else {
        mode = 'existing';
        selectedContactId = String(matches[0].id);
      }

      jobName = senderInfo.suggested_body
        ? senderInfo.suggested_body.split('\n')[0].slice(0, 50)
        : '';
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function ensureContactId() {
    if (mode === 'existing') {
      if (!selectedContactId) throw new Error('Please select a contact.');
      return parseInt(selectedContactId, 10);
    }
    // mode === 'new' — create contact (and business if requested)
    const contactPayload = { ...contactForm };
    if (!contactPayload.work_number && !contactPayload.mobile_number && !contactPayload.home_number) {
      throw new Error('At least one phone number (work, mobile, or home) is required.');
    }

    let businessId = null;
    if (businessMode === 'existing') {
      if (!selectedBusinessId) throw new Error('Please select a business or choose "no business".');
      businessId = parseInt(selectedBusinessId, 10);
      contactPayload.business_id = businessId;
    }

    const contact = await api.post('/api/contacts/', contactPayload);

    if (businessMode === 'new') {
      if (!newBusinessName.trim()) throw new Error('Business name is required.');
      const biz = await api.post('/api/businesses/', {
        business_name: newBusinessName.trim(),
        default_contact_id: contact.contact_id,
      });
      await api.patch(`/api/contacts/${contact.contact_id}/`, { business_id: biz.business_id });
    }

    return contact.contact_id;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    submitError = null;
    submitting = true;
    try {
      const contactId = await ensureContactId();
      const job = await emailApi.createJob(params.id, {
        contact: contactId,
        name: jobName.trim(),
      });
      push(`/jobs/${job.job_id}`);
    } catch (err) {
      submitError = err.message;
      submitting = false;
    }
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

<h2>Create Job from Email</h2>

<p><a href="#/email/{params.id}">&larr; Back to Email</a></p>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else if senderInfo}
  <h3>Sender</h3>
  <table border="1">
    <tbody>
      <tr><th>Name:</th><td>{senderInfo.sender_name || '(unknown)'}</td></tr>
      <tr><th>Email:</th><td>{senderInfo.sender_email || '(unknown)'}</td></tr>
      {#if senderInfo.extracted_company}
        <tr><th>Company (from signature):</th><td>{senderInfo.extracted_company}</td></tr>
      {/if}
    </tbody>
  </table>

  {#if submitError}
    <p><strong>Error:</strong> {submitError}</p>
  {/if}

  <form onsubmit={handleSubmit}>
    <h3>Contact</h3>

    {#if senderInfo.matching_contacts.length > 0}
      <p>
        <label>
          <input type="radio" bind:group={mode} value="existing">
          <strong>Use existing contact</strong>
        </label>
      </p>
      {#if mode === 'existing'}
        <p>
          <select bind:value={selectedContactId} required={mode === 'existing'}>
            <option value="">-- Select a contact --</option>
            {#each senderInfo.matching_contacts as c}
              <option value={c.id}>
                {c.name} ({c.email}){c.business ? ` — ${c.business.business_name}` : ''}
              </option>
            {/each}
          </select>
        </p>
      {/if}
      <p>
        <label>
          <input type="radio" bind:group={mode} value="new">
          <strong>Create a new contact</strong>
        </label>
      </p>
    {/if}

    {#if mode === 'new'}
      <fieldset>
        <legend><strong>New Contact</strong></legend>
        <p>
          <label for="first_name"><strong>First Name *</strong></label><br>
          <input type="text" id="first_name" bind:value={contactForm.first_name} required>
        </p>
        <p>
          <label for="last_name"><strong>Last Name *</strong></label><br>
          <input type="text" id="last_name" bind:value={contactForm.last_name} required>
        </p>
        <p>
          <label for="email"><strong>Email *</strong></label><br>
          <input type="email" id="email" bind:value={contactForm.email} required>
        </p>
        <fieldset>
          <legend><strong>Phone (at least one required)</strong></legend>
          <p>
            <label for="work_number"><strong>Work</strong></label><br>
            <input type="text" id="work_number" bind:value={contactForm.work_number}>
          </p>
          <p>
            <label for="mobile_number"><strong>Mobile</strong></label><br>
            <input type="text" id="mobile_number" bind:value={contactForm.mobile_number}>
          </p>
          <p>
            <label for="home_number"><strong>Home</strong></label><br>
            <input type="text" id="home_number" bind:value={contactForm.home_number}>
          </p>
        </fieldset>
      </fieldset>

      <fieldset>
        <legend><strong>Business</strong></legend>
        <p>
          <label>
            <input type="radio" bind:group={businessMode} value="none"> No business
          </label>
        </p>
        {#if senderInfo.matching_businesses.length > 0}
          <p>
            <label>
              <input type="radio" bind:group={businessMode} value="existing"> Use existing:
            </label>
            {#if businessMode === 'existing'}
              <select bind:value={selectedBusinessId}>
                <option value="">-- Select --</option>
                {#each senderInfo.matching_businesses as b}
                  <option value={b.id}>{b.business_name}</option>
                {/each}
              </select>
            {/if}
          </p>
        {/if}
        <p>
          <label>
            <input type="radio" bind:group={businessMode} value="new"> Create new:
          </label>
          {#if businessMode === 'new'}
            <input type="text" bind:value={newBusinessName} placeholder="Business name">
          {/if}
        </p>
      </fieldset>
    {/if}

    <h3>Job</h3>
    <p>
      <label for="job_name"><strong>Job Name *</strong> (max 50 chars)</label><br>
      <input type="text" id="job_name" bind:value={jobName} maxlength="50" required>
    </p>

    <p>
      <button type="submit" disabled={submitting}>
        {submitting ? 'Creating…' : 'Create Job'}
      </button>
      <a href="#/email/{params.id}">Cancel</a>
    </p>
  </form>
{/if}
