<script>
  const {
    business = null,
    paymentTerms = [],
    contacts = [],
    onSubmit,
    onCancel,
    errors = null,
  } = $props();

  // Intentionally captures initial prop value — form state is then independent
  let form = $state({
    business_name: business?.business_name || '',
    business_address: business?.business_address || '',
    business_phone: business?.business_phone || '',
    tax_exemption_number: business?.tax_exemption_number || '',
    website: business?.website || '',
    tax_multiplier: business?.tax_multiplier ?? '',
    terms: business?.terms || '',
    default_contact: business?.default_contact || '',
  });

  function handleSubmit(e) {
    e.preventDefault();
    const data = { ...form };
    if (data.terms === '') data.terms = null;
    if (data.default_contact === '') data.default_contact = null;
    if (data.tax_multiplier === '') data.tax_multiplier = null;
    onSubmit(data);
  }
</script>

<form onsubmit={handleSubmit}>
  {#if errors}
    <p><strong>Error:</strong> {errors}</p>
  {/if}

  <p>
    <label for="business_name"><strong>Business Name *</strong></label><br>
    <input type="text" id="business_name" bind:value={form.business_name} required>
  </p>
  <p>
    <label for="business_phone"><strong>Phone</strong></label><br>
    <input type="text" id="business_phone" bind:value={form.business_phone}>
  </p>
  <p>
    <label for="business_address"><strong>Address</strong></label><br>
    <textarea id="business_address" bind:value={form.business_address}></textarea>
  </p>
  <p>
    <label for="website"><strong>Website</strong></label><br>
    <input type="url" id="website" bind:value={form.website}>
  </p>

  <fieldset>
    <legend><strong>Tax</strong></legend>
    <p>
      <label for="tax_exemption_number"><strong>Tax Exemption Number</strong></label><br>
      <input type="text" id="tax_exemption_number" bind:value={form.tax_exemption_number}>
    </p>
    <p>
      <label for="tax_multiplier"><strong>Tax Multiplier</strong></label><br>
      <input type="number" id="tax_multiplier" bind:value={form.tax_multiplier} step="0.01" min="0" max="1">
    </p>
  </fieldset>

  <p>
    <label for="terms"><strong>Payment Terms</strong></label><br>
    <select id="terms" bind:value={form.terms}>
      <option value="">-- None --</option>
      {#each paymentTerms as term}
        <option value={term.term_id}>{term.term_id}</option>
      {/each}
    </select>
  </p>

  <p>
    <label for="default_contact"><strong>Default Contact</strong></label><br>
    <select id="default_contact" bind:value={form.default_contact}>
      <option value="">-- None --</option>
      {#each contacts as c}
        <option value={c.contact_id}>{c.name}</option>
      {/each}
    </select>
  </p>

  <p>
    <button type="submit">{business ? 'Save' : 'Create'}</button>
    <button type="button" onclick={onCancel}>Cancel</button>
  </p>
</form>
