<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  let { value = $bindable(null), selectedItem = null,
        onSelect = () => {}, disabled = false } = $props();
  const label = (c) => c.business ? `${c.name} — ${c.business.business_name}` : c.name;
  const search = (q) =>
    api.get(`/api/contacts/?search=${encodeURIComponent(q)}&page_size=10`)
       .then((d) => d.results || d);
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/contacts/${id}/`).then(label).catch(() => null);
</script>

<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(c) => { value = c.contact_id; onSelect(c); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search contacts…" />
