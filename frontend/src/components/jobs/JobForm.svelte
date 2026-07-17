<script>
  // Create-only: editing an existing job goes through JobHeader's Edit
  // button (JobEditModal), which covers the same writable fields plus a
  // status-transition-aware save path. This form only ever creates.
  import ContactPicker from '../ContactPicker.svelte';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';

  const {
    users = [],
    defaultContactId = null,
    onSubmit,
    onCancel,
    errors = {},      // field→messages bag (triageError(e).fields), keys match the API payload
    formError = '',   // form-footer message (operation errors / non_field_errors)
  } = $props();

  let form = $state({
    // svelte-ignore state_referenced_locally -- mount-seed by design (parent remounts via {#if}/{#key}, or a $effect re-syncs)
    contact: defaultContactId,
    name: '',
    description: '',
    customer_po_number: '',
    due_date: '',
    project_manager: '',
  });

  function handleSubmit(e) {
    e.preventDefault();
    const data = {
      contact: form.contact,
      name: form.name,
      description: form.description,
      customer_po_number: form.customer_po_number,
      due_date: form.due_date ? new Date(form.due_date).toISOString() : null,
      project_manager: form.project_manager ? Number(form.project_manager) : null,
    };
    onSubmit(data);
  }
</script>

<form onsubmit={handleSubmit}>
  <p>
    <label><strong>Contact *</strong></label><br>
    <ContactPicker bind:value={form.contact} />
    <FieldError {errors} field="contact" />
  </p>

  <p>
    <label for="job-name"><strong>Name</strong></label><br>
    <input type="text" id="job-name" maxlength="50" bind:value={form.name}>
    <FieldError {errors} field="name" />
  </p>

  <p>
    <label for="job-description"><strong>Description</strong></label><br>
    <textarea id="job-description" rows="6" cols="60" bind:value={form.description}></textarea>
    <FieldError {errors} field="description" />
  </p>

  <p>
    <label for="job-due-date"><strong>Due Date</strong></label><br>
    <input type="datetime-local" id="job-due-date" bind:value={form.due_date}>
    <FieldError {errors} field="due_date" />
  </p>

  <p>
    <label for="job-customer-po"><strong>Customer PO Number</strong></label><br>
    <input type="text" id="job-customer-po" maxlength="50" bind:value={form.customer_po_number}>
    <FieldError {errors} field="customer_po_number" />
  </p>

  <p>
    <label for="job-project-manager"><strong>Project Manager</strong></label><br>
    <select id="job-project-manager" bind:value={form.project_manager}>
      <option value="">-- None --</option>
      {#each users as u}
        <option value={String(u.id)}>{u.name}</option>
      {/each}
    </select>
    <FieldError {errors} field="project_manager" />
  </p>

  <p>
    <button type="submit">Create</button>
    <button type="button" onclick={onCancel}>Cancel</button>
  </p>
  <FormMessage error={formError} />
</form>
