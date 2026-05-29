<script>
  // Sender-info display + contact picker / new-contact form + business-mode
  // sub-flow shared by Create Job / Create PO / Create Bill from Email.
  //
  // The parent owns the surrounding <form> and submit button. This component
  // owns its UI block and exposes its state through $bindable props; the
  // parent calls `resolveSenderToContact(state, senderInfo)` from lib/email.js
  // to turn the state into {contactId, businessId} on submit.

  let {
    senderInfo,
    state = $bindable(),
  } = $props();

  // Initialize from senderInfo whenever it arrives.
  $effect(() => {
    if (!senderInfo) return;
    const matches = senderInfo.matching_contacts || [];
    const next = {
      mode: 'existing',
      selectedContactId: '',
      contactForm: {
        first_name: '',
        last_name: '',
        email: '',
        mobile_number: '',
        work_number: '',
        home_number: '',
      },
      businessMode: 'none',
      selectedBusinessId: '',
      newBusinessName: '',
    };

    if (matches.length === 1) {
      next.mode = 'existing';
      next.selectedContactId = String(matches[0].id);
    } else if (matches.length === 0) {
      next.mode = 'new';
      const [firstName, ...rest] = (senderInfo.sender_name || '').split(' ');
      next.contactForm.first_name = firstName || '';
      next.contactForm.last_name = rest.join(' ');
      next.contactForm.email = senderInfo.sender_email || '';
      const bizMatches = senderInfo.matching_businesses || [];
      if (bizMatches.length > 0) {
        next.businessMode = 'existing';
        next.selectedBusinessId = String(bizMatches[0].id);
      } else if (senderInfo.extracted_company) {
        next.businessMode = 'new';
        next.newBusinessName = senderInfo.extracted_company;
      }
    } else {
      next.mode = 'existing';
      next.selectedContactId = String(matches[0].id);
    }
    state = next;
  });
</script>

{#if senderInfo && state}
  <h3>Sender</h3>
  <table class="data-table">
    <tbody>
      <tr><th>Name:</th><td>{senderInfo.sender_name || '(unknown)'}</td></tr>
      <tr><th>Email:</th><td>{senderInfo.sender_email || '(unknown)'}</td></tr>
      {#if senderInfo.extracted_company}
        <tr><th>Company (from signature):</th><td>{senderInfo.extracted_company}</td></tr>
      {/if}
    </tbody>
  </table>

  <h3>Contact</h3>

  {#if senderInfo.matching_contacts.length > 0}
    <p>
      <label>
        <input type="radio" bind:group={state.mode} value="existing">
        <strong>Use existing contact</strong>
      </label>
    </p>
    {#if state.mode === 'existing'}
      {#if senderInfo.matching_contacts.length === 1}
        {@const c = senderInfo.matching_contacts[0]}
        <p>
          {c.name} ({c.email}){c.business ? ` — ${c.business.business_name}` : ''}
        </p>
      {:else}
        <p>
          <select bind:value={state.selectedContactId} required={state.mode === 'existing'}>
            <option value="">-- Select a contact --</option>
            {#each senderInfo.matching_contacts as c}
              <option value={c.id}>
                {c.name} ({c.email}){c.business ? ` — ${c.business.business_name}` : ''}
              </option>
            {/each}
          </select>
        </p>
      {/if}
    {/if}
    <p>
      <label>
        <input type="radio" bind:group={state.mode} value="new">
        <strong>Create a new contact</strong>
      </label>
    </p>
  {/if}

  {#if state.mode === 'new'}
    <fieldset>
      <legend><strong>New Contact</strong></legend>
      <p>
        <label for="first_name"><strong>First Name *</strong></label><br>
        <input type="text" id="first_name" bind:value={state.contactForm.first_name} required>
      </p>
      <p>
        <label for="last_name"><strong>Last Name *</strong></label><br>
        <input type="text" id="last_name" bind:value={state.contactForm.last_name} required>
      </p>
      <p>
        <label for="email"><strong>Email *</strong></label><br>
        <input type="email" id="email" bind:value={state.contactForm.email} required>
      </p>
      <fieldset>
        <legend><strong>Phone (at least one required)</strong></legend>
        <p>
          <label for="work_number"><strong>Work</strong></label><br>
          <input type="text" id="work_number" bind:value={state.contactForm.work_number}>
        </p>
        <p>
          <label for="mobile_number"><strong>Mobile</strong></label><br>
          <input type="text" id="mobile_number" bind:value={state.contactForm.mobile_number}>
        </p>
        <p>
          <label for="home_number"><strong>Home</strong></label><br>
          <input type="text" id="home_number" bind:value={state.contactForm.home_number}>
        </p>
      </fieldset>
    </fieldset>

    <fieldset>
      <legend><strong>Business</strong></legend>
      <p>
        <label>
          <input type="radio" bind:group={state.businessMode} value="none"> No business
        </label>
      </p>
      {#if senderInfo.matching_businesses.length > 0}
        <p>
          <label>
            <input type="radio" bind:group={state.businessMode} value="existing"> Use existing:
          </label>
          {#if state.businessMode === 'existing'}
            <select bind:value={state.selectedBusinessId}>
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
          <input type="radio" bind:group={state.businessMode} value="new"> Create new:
        </label>
        {#if state.businessMode === 'new'}
          <input type="text" bind:value={state.newBusinessName} placeholder="Business name">
        {/if}
      </p>
    </fieldset>
  {/if}
{/if}
