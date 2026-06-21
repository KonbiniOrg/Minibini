<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  let { value = $bindable(null), selectedItem = null, onSelect = () => {},
        params = {}, disabled = false } = $props();
  const label = (i) => `${i.code} — ${i.description ?? ''}`;
  function buildQuery(q) {
    const usp = new URLSearchParams({ search: q, page_size: '10' });
    for (const [k, v] of Object.entries(params)) usp.set(k, String(v));
    return usp.toString();
  }
  const search = (q) =>
    api.get(`/api/inventory/?${buildQuery(q)}`).then((d) => d.results || d);
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/inventory/${id}/`).then(label).catch(() => null);
  function freeform(close) { close(); value = null; onSelect(null); }
</script>

<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(i) => { value = i.inventory_item_id; onSelect(i); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search price list items…">
  {#snippet header(close)}
    <li><button type="button" onmousedown={() => freeform(close)}>None (freeform)</button></li>
  {/snippet}
</SearchPicker>
