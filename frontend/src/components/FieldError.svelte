<script>
  // The under-input slot for field validation errors (contract shape
  // {'field': ['msg', ...]}). Place directly below the input so the red
  // line lands under the field, its label above undisturbed:
  //
  //   <label>Rate <input bind:value={form.rate} /></label>
  //   <FieldError {errors} field="rate" />
  //
  // `errors` is the whole bag (set from triageError(e).fields); each slot
  // reads its own slice, so one assignment lights every field at once.
  import { fieldErrors } from '../lib/formErrors.js';

  let { errors = {}, field } = $props();

  const msgs = $derived(fieldErrors(errors, field));
</script>

{#each msgs as msg}
  <p class="field-error">{msg}</p>
{/each}

<style>
  .field-error {
    color: #c00;
    margin: 0.15em 0 0;
    font-size: 0.9em;
  }
</style>
