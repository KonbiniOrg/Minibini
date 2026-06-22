<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  import { PICKER_PAGE_SIZE } from '../lib/pagination.js';
  let { value = $bindable(null), selectedItem = null,
        onSelect = () => {}, disabled = false } = $props();
  const label = (j) => `${j.job_number} — ${j.name ?? j.description ?? ''}`;
  const search = (q) =>
    api.get(`/api/jobs/?search=${encodeURIComponent(q)}&page_size=${PICKER_PAGE_SIZE}`)
       .then((d) => ({ rows: d.results || d, total: d.count ?? (d.results || d).length }));
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/jobs/${id}/`).then(label).catch(() => null);
</script>

<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(j) => { value = j.job_id; onSelect(j); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search jobs…" />
