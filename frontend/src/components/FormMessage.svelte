<script>
  // The form-footer slot: place immediately AFTER the form's button row.
  // Red for operation errors / non_field_errors, green for the rare in-form
  // success acknowledgement. Same location either way, so the user always
  // knows where to look. Optional children render after the text — the
  // affordance slot for conflict responses that carry a next step (e.g. a
  // "Create new version" button beside the referenced-scheme 409).
  let { error = '', success = '', children } = $props();
</script>

{#if error}
  <div class="form-message error" role="alert">
    <span>{error}</span>
    {@render children?.()}
  </div>
{:else if success}
  <div class="form-message success">
    <span>{success}</span>
  </div>
{/if}

<style>
  .form-message {
    margin: 0.5em 0 0;
    display: flex;
    align-items: center;
    gap: 0.75em;
  }
  .form-message.error {
    color: #c00;
  }
  .form-message.success {
    color: #090;
  }
</style>
