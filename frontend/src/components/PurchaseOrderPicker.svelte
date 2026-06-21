<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  let { value = $bindable(null), selectedItem = null,
        onSelect = () => {}, disabled = false } = $props();
  const label = (p) => `${p.po_number}${p.business ? ` — ${p.business.business_name}` : ''}`;
  const search = (q) =>
    api.get(`/api/purchase-orders/?search=${encodeURIComponent(q)}&page_size=10`)
       .then((d) => d.results || d);
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/purchase-orders/${id}/`).then(label).catch(() => null);
</script>

<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(p) => { value = p.po_id; onSelect(p); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search purchase order…" />
