<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  import { PICKER_PAGE_SIZE } from '../lib/pagination.js';
  let { value = $bindable(null), selectedItem = null,
        onSelect = () => {}, disabled = false, businessId = null, inputId = undefined } = $props();
  const label = (c) => c.business ? `${c.name} — ${c.business.business_name}` : c.name;
  const search = (q) =>
    api.get(`/api/contacts/?search=${encodeURIComponent(q)}&page_size=${PICKER_PAGE_SIZE}${businessId != null ? `&business=${businessId}` : ''}`)
       .then((d) => ({ rows: d.results || d, total: d.count ?? (d.results || d).length }));
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/contacts/${id}/`).then(label).catch(() => null);
</script>

<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(c) => { value = c.contact_id; onSelect(c); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} {inputId} placeholder="Search contacts…" />
