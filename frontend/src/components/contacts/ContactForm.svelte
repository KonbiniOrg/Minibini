<script>
  import BusinessPicker from '../BusinessPicker.svelte';
  import PhoneListEditor from './PhoneListEditor.svelte';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';

  const {
    contact = null,
    defaultBusinessId = null,
    onSubmit,
    onCancel,
    errors = {},      // field→messages bag (triageError(e).fields), keys match the API payload
    formError = '',   // form-footer message (operation errors / non_field_errors)
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
    phones: contact?.phones ? contact.phones.map((p) => ({ ...p })) : [],
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
    business: contact?.business?.business_id ?? defaultBusinessId ?? null,
  });

  function handleSubmit(e) {
    e.preventDefault();
    // The serializer's `business` field is read-only; the writable field is
    // `business_id` (PrimaryKeyRelatedField, source='business'). Send that key
    // or the association is silently dropped.
    const { business, ...rest } = form;
    const data = { ...rest, phones: rest.phones.filter((p) => p.number.trim()), business_id: (business === '' || business == null) ? null : business };
    onSubmit(data);
  }
</script>

<form onsubmit={handleSubmit}>
  <p>
    <label for="first_name"><strong>First Name *</strong></label><br>
    <input type="text" id="first_name" bind:value={form.first_name} required>
    <FieldError {errors} field="first_name" />
  </p>
  <p>
    <label for="middle_initial"><strong>Middle Initial</strong></label><br>
    <input type="text" id="middle_initial" bind:value={form.middle_initial}>
    <FieldError {errors} field="middle_initial" />
  </p>
  <p>
    <label for="last_name"><strong>Last Name *</strong></label><br>
    <input type="text" id="last_name" bind:value={form.last_name} required>
    <FieldError {errors} field="last_name" />
  </p>
  <p>
    <label for="email"><strong>Email *</strong></label><br>
    <input type="email" id="email" bind:value={form.email} required>
    <FieldError {errors} field="email" />
  </p>

  <PhoneListEditor bind:phones={form.phones} {errors} />

  <fieldset>
    <legend><strong>Address</strong></legend>
    <p>
      <label for="addr1"><strong>Address 1</strong></label><br>
      <input type="text" id="addr1" bind:value={form.addr1}>
      <FieldError {errors} field="addr1" />
    </p>
    <p>
      <label for="addr2"><strong>Address 2</strong></label><br>
      <input type="text" id="addr2" bind:value={form.addr2}>
      <FieldError {errors} field="addr2" />
    </p>
    <p>
      <label for="addr3"><strong>Address 3</strong></label><br>
      <input type="text" id="addr3" bind:value={form.addr3}>
      <FieldError {errors} field="addr3" />
    </p>
    <p>
      <label for="city"><strong>City</strong></label><br>
      <input type="text" id="city" bind:value={form.city}>
      <FieldError {errors} field="city" />
    </p>
    <p>
      <label for="municipality"><strong>Municipality</strong></label><br>
      <input type="text" id="municipality" bind:value={form.municipality}>
      <FieldError {errors} field="municipality" />
    </p>
    <p>
      <label for="postal_code"><strong>Postal Code</strong></label><br>
      <input type="text" id="postal_code" bind:value={form.postal_code}>
      <FieldError {errors} field="postal_code" />
    </p>
    <p>
      <label for="country_code"><strong>Country Code</strong></label><br>
      <input type="text" id="country_code" bind:value={form.country_code} maxlength="3">
      <FieldError {errors} field="country_code" />
    </p>
  </fieldset>

  <p>
    <label><strong>Business</strong></label><br>
    <BusinessPicker bind:value={form.business} selectedItem={contact?.business ?? null} />
    <FieldError {errors} field="business_id" />
  </p>

  <p>
    <button type="submit">{contact ? 'Save' : 'Create'}</button>
    <button type="button" onclick={onCancel}>Cancel</button>
  </p>
  <FormMessage error={formError} />
</form>
