<script>
  import { api } from '@/lib/api.js';
  let { businessId = null, value = $bindable(null), onSelect = () => {} } = $props();
  let term = $state('');
  let results = $state([]);

  async function search() {
    if (!businessId) { results = []; return; }
    const params = new URLSearchParams({ business: String(businessId) });
    const data = await api.get(`/api/purchase-orders/?${params}`);
    const list = data.results || data;
    results = list.filter(po =>
      po.status !== 'draft' && po.status !== 'cancelled' &&
      po.po_number.toLowerCase().includes(term.toLowerCase()));
  }

  function pick(po) { value = po; results = []; term = po.po_number; onSelect(po); }
</script>

<input placeholder="Purchase order…" bind:value={term} oninput={search} />
{#if results.length}
  <ul>
    {#each results as po}
      <li><button type="button" onclick={() => pick(po)}>{po.po_number} ({po.status})</button></li>
    {/each}
  </ul>
{/if}

<style>
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    border: 1px solid #ccc;
    background: #fff;
    max-height: 200px;
    overflow-y: auto;
  }
  li button {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0.3em 0.5em;
    background: none;
    border: none;
    cursor: pointer;
  }
  li button:hover {
    background: #f0f0f0;
  }
</style>
