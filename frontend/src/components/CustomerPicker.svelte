<script>
  // Dual-source typeahead for picking a customer OR vendor. Searches both
  // /api/contacts/ and /api/businesses/ in parallel and merges the results,
  // emitting { type: 'business' | 'contact', id }. Reusable wherever a party
  // needs picking. ContactPicker/JobPicker are left untouched.
  import { api } from '../lib/api.js';

  let { value = $bindable(null), onSelect = () => {} } = $props();

  let query = $state('');
  let results = $state([]);
  let showResults = $state(false);
  let selectedLabel = $state('');

  function businessLabel(b) {
    return `${b.business_name} (business)`;
  }
  function contactLabel(c) {
    const base = c.business ? `${c.name} — ${c.business.business_name}` : c.name;
    return `${base} (contact)`;
  }

  async function search() {
    const q = query.trim();
    if (!q) { results = []; showResults = false; return; }
    try {
      const [businesses, contacts] = await Promise.all([
        api.get(`/api/businesses/?search=${encodeURIComponent(q)}&page_size=10`),
        api.get(`/api/contacts/?search=${encodeURIComponent(q)}&page_size=10`),
      ]);
      const bRows = (businesses.results || businesses).map((b) => ({
        type: 'business', id: b.business_id, label: businessLabel(b),
      }));
      const cRows = (contacts.results || contacts).map((c) => ({
        type: 'contact', id: c.contact_id, label: contactLabel(c),
      }));
      results = [...bRows, ...cRows];
      showResults = true;
    } catch (e) {
      console.error(e);
    }
  }

  function pick(row) {
    value = { type: row.type, id: row.id };
    selectedLabel = row.label;
    query = '';
    results = [];
    showResults = false;
    onSelect(value);
  }

  function clear() {
    value = null;
    selectedLabel = '';
    query = '';
    results = [];
    showResults = false;
    onSelect(null);
  }
</script>

{#if value}
  <span>{selectedLabel} <button type="button" onclick={clear}>Clear</button></span>
{:else}
  <input type="text" bind:value={query} oninput={search}
         placeholder="Search customer or vendor…">
  {#if showResults && results.length}
    <ul>
      {#each results as row (row.type + ':' + row.id)}
        <li><button type="button" onmousedown={() => pick(row)}>{row.label}</button></li>
      {/each}
    </ul>
  {/if}
{/if}
