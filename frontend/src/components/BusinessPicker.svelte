<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  let { value = $bindable(null), selectedItem = null,
        onSelect = () => {}, disabled = false } = $props();
  const label = (b) => b.business_name;
  const search = (q) =>
    api.get(`/api/businesses/?search=${encodeURIComponent(q)}&page_size=10`)
       .then((d) => d.results || d);
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/businesses/${id}/`).then(label).catch(() => null);
</script>

<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(b) => { value = b.business_id; onSelect(b); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search business…" />
