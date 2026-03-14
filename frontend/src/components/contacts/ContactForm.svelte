<script>
  const {
    contact = null,
    businesses = [],
    onSubmit,
    onCancel,
    errors = null,
  } = $props();

  // Intentionally captures initial prop value — form state is then independent
  let form = $state({
    first_name: contact?.first_name || '',
    middle_initial: contact?.middle_initial || '',
    last_name: contact?.last_name || '',
    email: contact?.email || '',
    mobile_number: contact?.mobile_number || '',
    work_number: contact?.work_number || '',
    home_number: contact?.home_number || '',
    addr1: contact?.addr1 || '',
    addr2: contact?.addr2 || '',
    addr3: contact?.addr3 || '',
    city: contact?.city || '',
    municipality: contact?.municipality || '',
    postal_code: contact?.postal_code || '',
    country_code: contact?.country_code || '',
    business: contact?.business || '',
  });

  function handleSubmit(e) {
    e.preventDefault();
    const data = { ...form };
    if (data.business === '') {
      data.business = null;
    }
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
    <label for="business"><strong>Business</strong></label><br>
    <select id="business" bind:value={form.business}>
      <option value="">-- None --</option>
      {#each businesses as biz}
        <option value={biz.business_id}>{biz.business_name}</option>
      {/each}
    </select>
  </p>

  <p>
    <button type="submit">{contact ? 'Save' : 'Create'}</button>
    <button type="button" onclick={onCancel}>Cancel</button>
  </p>
</form>
