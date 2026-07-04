<script>
  // Dual-source picker (business OR contact). Keeps its own {type,id} output;
  // only the search/emit differ from the single-model pickers — the behavior
  // is shared via SearchPicker.
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  import { PICKER_PAGE_SIZE } from '../lib/pagination.js';
  let { value = $bindable(null), onSelect = () => {}, disabled = false } = $props();

  const rowLabel = (r) => r.label;
  const search = async (q) => {
    const [biz, con] = await Promise.all([
      api.get(`/api/businesses/?search=${encodeURIComponent(q)}&page_size=${PICKER_PAGE_SIZE}`),
      api.get(`/api/contacts/?search=${encodeURIComponent(q)}&page_size=${PICKER_PAGE_SIZE}`),
    ]);
    const bizRows = biz.results || biz;
    const conRows = con.results || con;
    const bRows = bizRows.map((b) => ({
      type: 'business', id: b.business_id, label: `${b.business_name} (business)` }));
    const cRows = conRows.map((c) => ({
      type: 'contact', id: c.contact_id,
      label: `${c.business ? `${c.name} — ${c.business.business_name}` : c.name} (contact)` }));
    return { rows: [...bRows, ...cRows], total: (biz.count ?? bizRows.length) + (con.count ?? conRows.length) };
  };
  const resolveLabel = (v) => {
    if (!v) return Promise.resolve(null);
    const url = v.type === 'business'
      ? `/api/businesses/${v.id}/` : `/api/contacts/${v.id}/`;
    return api.get(url).then((o) => v.type === 'business'
      ? `${o.business_name} (business)`
      : `${o.business ? `${o.name} — ${o.business.business_name}` : o.name} (contact)`)
      .catch(() => null);
  };
</script>

<SearchPicker bind:value {search} {resolveLabel} {rowLabel}
  onPick={(r) => { value = { type: r.type, id: r.id }; onSelect(value); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search customer or vendor…" />
