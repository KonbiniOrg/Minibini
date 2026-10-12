<script>
  // Ordered phone list editor (contacts refine, 2026-10-11). The first row
  // is the primary number; ▲ promotes a row. Rows are pending form state —
  // the host form's Save commits (no blur-saves).
  import FieldError from '../FieldError.svelte';
  let { phones = $bindable([]), errors = {} } = $props();

  function add() { phones = [...phones, { number: '', label: '' }]; }
  function remove(i) { phones = phones.filter((_, idx) => idx !== i); }
  function moveUp(i) {
    if (i === 0) return;
    const next = [...phones];
    [next[i - 1], next[i]] = [next[i], next[i - 1]];
    phones = next;
  }
</script>

<fieldset class="phones">
  <legend><strong>Phone numbers</strong></legend>
  {#if phones.length === 0}
    <p class="muted">No phone numbers</p>
  {/if}
  {#each phones as entry, i (i)}
    <div class="phone-row">
      <input type="text" placeholder="Number" aria-label={`Phone ${i + 1} number`} bind:value={entry.number}>
      <input type="text" placeholder="Label (cell, work, A/P…)" aria-label={`Phone ${i + 1} label`} bind:value={entry.label}>
      {#if i === 0}<span class="primary">primary</span>{:else}
        <button type="button" class="icon" aria-label={`Move phone ${i + 1} up`} onclick={() => moveUp(i)}>▲</button>
      {/if}
      <button type="button" class="icon" aria-label={`Remove phone ${i + 1}`} onclick={() => remove(i)}>✕</button>
    </div>
  {/each}
  <button type="button" onclick={add}>Add phone</button>
  <FieldError {errors} field="phones" />
</fieldset>

<style>
  .phone-row { display: grid; grid-template-columns: 1fr 1fr auto auto; gap: 6px; align-items: center; margin-bottom: 6px; }
  .primary { font-size: 11px; color: #166534; background: #dcfce7; border-radius: 10px; padding: 2px 8px; }
  .icon { padding: 2px 8px; }
  .muted { color: #64748b; font-size: 13px; margin: 4px 0; }
</style>
