<script>
  import BusinessPicker from '../BusinessPicker.svelte';

  const {
    contact = null,
    businesses = [],
    onSubmit,
    onCancel,
    errors = null,
  } = $props();

  // Intentionally captures initial prop value — form state is then independent
  let form = $state({
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    first_name: contact?.first_name || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    middle_initial: contact?.middle_initial || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    last_name: contact?.last_name || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    email: contact?.email || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    mobile_number: contact?.mobile_number || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    work_number: contact?.work_number || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    home_number: contact?.home_number || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    addr1: contact?.addr1 || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    addr2: contact?.addr2 || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    addr3: contact?.addr3 || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    city: contact?.city || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    municipality: contact?.municipality || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    postal_code: contact?.postal_code || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    country_code: contact?.country_code || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    business: contact?.business?.business_id ?? null,
  });

  function handleSubmit(e) {
    e.preventDefault();
    // The serializer's `business` field is read-only; the writable field is
    // `business_id` (PrimaryKeyRelatedField, source='business'). Send that key
    // or the association is silently dropped.
    const { business, ...rest } = form;
    const data = { ...rest, business_id: (business === '' || business == null) ? null : business };
    onSubmit(data);
  }
</script>

<form onsubmit={handleSubmit}>
  {#if errors}
    <p><strong>Error:</strong> {errors}</p>
  {/if}

  <p>
    <label for="first_name"><strong>First Name *</strong></label><br>
    <input type="text" id="first_name" bind:value={form.first_name} required>
  </p>
  <p>
    <label for="middle_initial"><strong>Middle Initial</strong></label><br>
    <input type="text" id="middle_initial" bind:value={form.middle_initial}>
  </p>
  <p>
    <label for="last_name"><strong>Last Name *</strong></label><br>
    <input type="text" id="last_name" bind:value={form.last_name} required>
  </p>
  <p>
    <label for="email"><strong>Email *</strong></label><br>
    <input type="email" id="email" bind:value={form.email} required>
  </p>

  <fieldset>
    <legend><strong>Phone Numbers (at least one required)</strong></legend>
    <p>
      <label for="work_number"><strong>Work</strong></label><br>
      <input type="text" id="work_number" bind:value={form.work_number}>
    </p>
    <p>
      <label for="mobile_number"><strong>Mobile</strong></label><br>
      <input type="text" id="mobile_number" bind:value={form.mobile_number}>
    </p>
    <p>
      <label for="home_number"><strong>Home</strong></label><br>
      <input type="text" id="home_number" bind:value={form.home_number}>
    </p>
  </fieldset>

  <fieldset>
    <legend><strong>Address</strong></legend>
    <p>
      <label for="addr1"><strong>Address 1</strong></label><br>
      <input type="text" id="addr1" bind:value={form.addr1}>
    </p>
    <p>
      <label for="addr2"><strong>Address 2</strong></label><br>
      <input type="text" id="addr2" bind:value={form.addr2}>
    </p>
    <p>
      <label for="addr3"><strong>Address 3</strong></label><br>
      <input type="text" id="addr3" bind:value={form.addr3}>
    </p>
    <p>
      <label for="city"><strong>City</strong></label><br>
      <input type="text" id="city" bind:value={form.city}>
    </p>
    <p>
      <label for="municipality"><strong>Municipality</strong></label><br>
      <input type="text" id="municipality" bind:value={form.municipality}>
    </p>
    <p>
      <label for="postal_code"><strong>Postal Code</strong></label><br>
      <input type="text" id="postal_code" bind:value={form.postal_code}>
    </p>
    <p>
      <label for="country_code"><strong>Country Code</strong></label><br>
      <input type="text" id="country_code" bind:value={form.country_code} maxlength="3">
    </p>
  </fieldset>

  <p>
    <label><strong>Business</strong></label><br>
    <BusinessPicker bind:value={form.business} selectedItem={contact?.business ?? null} />
  </p>

  <p>
    <button type="submit">{contact ? 'Save' : 'Create'}</button>
    <button type="button" onclick={onCancel}>Cancel</button>
  </p>
</form>
