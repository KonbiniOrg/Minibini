<script>
  import PhoneListEditor from './PhoneListEditor.svelte';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';

  const {
    business = null,
    paymentTerms = [],
    onSubmit,
    onCancel,
    errors = {},      // field→messages bag (triageError(e).fields), keys match the API payload
    formError = '',   // form-footer message (operation errors / non_field_errors)
  } = $props();

  const isEdit = $derived(!!business);

  // Intentionally captures initial prop value — form state is then independent
  let form = $state({
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    business_name: business?.business_name || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    business_address: business?.business_address || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    phones: business?.phones ? business.phones.map((p) => ({ ...p })) : [],
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    tax_exemption_number: business?.tax_exemption_number || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    website: business?.website || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    tax_multiplier: business?.tax_multiplier ?? '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    terms: business?.terms || '',
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    default_contact_id: business?.default_contact?.contact_id || '',
  });

  let contactForm = $state({
    first_name: '',
    last_name: '',
    email: '',
    phones: [],
  });

  function handleSubmit(e) {
    e.preventDefault();
    const data = { ...form, phones: form.phones.filter((p) => p.number.trim()) };
    if (data.terms === '') data.terms = null;
    if (data.default_contact_id === '') data.default_contact_id = null;
    if (data.tax_multiplier === '') data.tax_multiplier = null;
    if (!isEdit) {
      data._contact = { ...contactForm, phones: contactForm.phones.filter((p) => p.number.trim()) };
    }
    onSubmit(data);
  }
</script>

<form onsubmit={handleSubmit}>
  <p>
    <label for="business_name"><strong>Business Name *</strong></label><br>
    <input type="text" id="business_name" bind:value={form.business_name} required>
    <FieldError {errors} field="business_name" />
  </p>
  <PhoneListEditor bind:phones={form.phones} {errors} />
  <p>
    <label for="business_address"><strong>Address</strong></label><br>
    <textarea id="business_address" bind:value={form.business_address}></textarea>
    <FieldError {errors} field="business_address" />
  </p>
  <p>
    <label for="website"><strong>Website</strong></label><br>
    <input type="url" id="website" bind:value={form.website}>
    <FieldError {errors} field="website" />
  </p>

  <fieldset>
    <legend><strong>Tax</strong></legend>
    <p>
      <label for="tax_exemption_number"><strong>Tax Exemption Number</strong></label><br>
      <input type="text" id="tax_exemption_number" bind:value={form.tax_exemption_number}>
      <FieldError {errors} field="tax_exemption_number" />
    </p>
    <p>
      <label for="tax_multiplier"><strong>Tax Multiplier</strong></label><br>
      <input type="number" id="tax_multiplier" bind:value={form.tax_multiplier} step="0.01" min="0" max="1">
      <FieldError {errors} field="tax_multiplier" />
    </p>
  </fieldset>

  <p>
    <label for="terms"><strong>Payment Terms</strong></label><br>
    <select id="terms" bind:value={form.terms}>
      <option value="">-- None --</option>
      {#each paymentTerms as term}
        <option value={term.term_id}>{term.name || term.term_id}</option>
      {/each}
    </select>
    <FieldError {errors} field="terms" />
  </p>

  {#if isEdit}
    <p>
      <label for="default_contact_id"><strong>Default Contact</strong></label><br>
      <select id="default_contact_id" bind:value={form.default_contact_id}>
        <option value="">-- None --</option>
        {#each (business.contacts || []).filter((c) => c.is_active !== false || c.contact_id === business.default_contact?.contact_id) as c}
          <option value={c.contact_id}>{c.name}</option>
        {/each}
      </select>
      <FieldError {errors} field="default_contact_id" />
    </p>
  {:else}
    <fieldset>
      <legend><strong>Default Contact</strong></legend>
      <!-- Created via POST /api/contacts/ first, so its field errors carry
           the contact payload keys (first_name, last_name, email, phones). -->
      <p>
        <label for="contact_first_name"><strong>First Name *</strong></label><br>
        <input type="text" id="contact_first_name" bind:value={contactForm.first_name} required>
        <FieldError {errors} field="first_name" />
      </p>
      <p>
        <label for="contact_last_name"><strong>Last Name *</strong></label><br>
        <input type="text" id="contact_last_name" bind:value={contactForm.last_name} required>
        <FieldError {errors} field="last_name" />
      </p>
      <p>
        <label for="contact_email"><strong>Email *</strong></label><br>
        <input type="email" id="contact_email" bind:value={contactForm.email} required>
        <FieldError {errors} field="email" />
      </p>
      <PhoneListEditor bind:phones={contactForm.phones} {errors} />
    </fieldset>
  {/if}

  <p>
    <button type="submit">{business ? 'Save' : 'Create'}</button>
    <button type="button" onclick={onCancel}>Cancel</button>
  </p>
  <FormMessage error={formError} />
</form>
