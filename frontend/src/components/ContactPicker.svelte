<script>
  // Server-side typeahead for picking a Contact. The contacts table is large
  // (thousands of rows), so a plain <select> can't list them — search instead.
  // `value` is the selected contact id (number) or null; it's bindable, and an
  // externally-set id (e.g. a prefill) is resolved to a display label on the fly.
  import { api } from '../lib/api.js';

  let { value = $bindable(null) } = $props();

  let query = $state('');
  let results = $state([]);
  let showResults = $state(false);
  let selectedLabel = $state('');
  let labelForId = $state(null); // which id `selectedLabel` describes
  let prevValue = $state(null);  // selection stashed when "Change" is clicked
  let prevLabel = $state('');

  function labelOf(c) {
    return c.business ? `${c.name} from ${c.business.business_name}` : c.name;
  }

  async function search() {
    const q = query.trim();
    if (!q) { results = []; showResults = false; return; }
    try {
      const data = await api.get(
        `/api/contacts/?search=${encodeURIComponent(q)}&page_size=10`);
      results = data.results || data;
      showResults = true;
    } catch (e) {
      console.error(e);
    }
  }

  function pick(c) {
    selectedLabel = labelOf(c);
    labelForId = c.contact_id;
    value = c.contact_id;
    prevValue = null; // committed a new choice — nothing to cancel back to
    prevLabel = '';
    query = '';
    results = [];
    showResults = false;
  }

  function change() {
    prevValue = value; // remember the current pick so Cancel can restore it
    prevLabel = selectedLabel;
    value = null;
    query = '';
    results = [];
    showResults = false;
  }

  function cancelChange() {
    value = prevValue;
    selectedLabel = prevLabel;
    labelForId = prevValue;
    prevValue = null;
    prevLabel = '';
    query = '';
    results = [];
    showResults = false;
  }

  // Resolve a label for an externally-provided value (prefill by id).
  $effect(() => {
    const id = value;
    if (id != null && id !== labelForId) {
      api.get(`/api/contacts/${id}/`)
        .then((c) => { if (value === id) { selectedLabel = labelOf(c); labelForId = id; } })
        .catch(() => {});
    }
  });
</script>

{#if value != null && labelForId === value}
  <span>{selectedLabel} <button type="button" onclick={change}>Change</button></span>
{:else}
  <input type="text" bind:value={query} oninput={search}
         placeholder="Search contacts by name, business, email, or phone…">
  {#if prevValue != null}
    <button type="button" onclick={cancelChange}>Cancel</button>
  {/if}
  {#if showResults}
    {#if results.length}
      <ul>
        {#each results as c}
          <li><button type="button" onclick={() => pick(c)}>{labelOf(c)}</button></li>
        {/each}
      </ul>
    {:else}
      <p>No matches.</p>
    {/if}
  {/if}
{/if}
