<script>
  import SearchPicker from './SearchPicker.svelte';
  import { api } from '../lib/api.js';
  import { PICKER_PAGE_SIZE } from '../lib/pagination.js';
  let { value = $bindable(null), selectedItem = null,
        onSelect = () => {}, disabled = false } = $props();
  const docNo = (b) => b.vendor_invoice_number || b.purchase_order?.po_number || `Bill #${b.bill_id}`;
  const label = (b) => `${docNo(b)}${b.business ? ` — ${b.business.business_name}` : ''}`;
  const search = (q) =>
    api.get(`/api/bills/?search=${encodeURIComponent(q)}&page_size=${PICKER_PAGE_SIZE}`)
       .then((d) => ({ rows: d.results || d, total: d.count ?? (d.results || d).length }));
  const resolveLabel = (id, item) =>
    item ? Promise.resolve(label(item))
    : id == null ? Promise.resolve(null)
    : api.get(`/api/bills/${id}/`).then(label).catch(() => null);
</script>

<SearchPicker bind:value {selectedItem} {search} {resolveLabel} rowLabel={label}
  onPick={(b) => { value = b.bill_id; onSelect(b); }}
  onClear={() => { value = null; onSelect(null); }}
  {disabled} placeholder="Search bill…" />
