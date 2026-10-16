<!-- frontend/src/components/purchaseorders/VendorPicker.svelte -->
<script>
  // Vendor tier of the Order modal (PO order flow §5.2). Two modes:
  //  - recent: a native <select> of the item's vendor-history rows (newest
  //    first, preselected to the first) plus a final "Search all
  //    businesses…" option;
  //  - search: the existing BusinessPicker type-ahead. While nothing is
  //    chosen and history exists, a "back to recent vendors" link returns;
  //    Clear on the picked chip returns to recent mode too.
  // Empty history opens straight in search mode with no back link.
  import BusinessPicker from '../BusinessPicker.svelte';

  let { vendors = [], value = $bindable(null), onSelect = () => {} } = $props();

  const SEARCH = '__search';
  // svelte-ignore state_referenced_locally -- mount-seed by design (history is loaded before this mounts)
  let mode = $state(vendors.length ? 'recent' : 'search');
  // svelte-ignore state_referenced_locally -- mount-seed by design
  let recentChoice = $state(vendors.length ? String(vendors[0].business_id) : '');
  let searchValue = $state(null);

  // svelte-ignore state_referenced_locally -- mount-seed by design
  if (vendors.length && value == null) {
    value = vendors[0].business_id;
    onSelect(vendors[0]);
  }

  function money(n) { return `$${Number(n).toFixed(2)}`; }
  function optionLabel(v) {
    let s = `${v.business_name} — last ${v.last_ordered}`;
    if (v.last_price != null && v.last_price !== '') s += ` at ${money(v.last_price)}`;
    if (v.vendor_sku) s += ` · SKU ${v.vendor_sku}`;
    return s;
  }

  function onRecentChange(e) {
    const picked = e.target.value;
    if (picked === SEARCH) {
      mode = 'search';
      searchValue = null;
      value = null;
      onSelect(null);
      return;
    }
    recentChoice = picked;
    const row = vendors.find((v) => String(v.business_id) === picked);
    value = row.business_id;
    onSelect(row);
  }

  function backToRecent() {
    mode = 'recent';
    recentChoice = String(vendors[0].business_id);
    value = vendors[0].business_id;
    onSelect(vendors[0]);
  }

  function onSearchSelect(b) {
    if (b) { value = b.business_id; onSelect(b); return; }
    value = null;
    if (vendors.length) backToRecent(); else onSelect(null);
  }
</script>

{#if mode === 'recent'}
  <select id="vendor-recent" value={recentChoice} onchange={onRecentChange}>
    {#each vendors as v (v.business_id)}
      <option value={String(v.business_id)}>{optionLabel(v)}</option>
    {/each}
    <option value={SEARCH}>Search all businesses…</option>
  </select>
{:else}
  <BusinessPicker bind:value={searchValue} onSelect={onSearchSelect} />
  {#if searchValue == null && vendors.length}
    <p class="back"><button type="button" class="link-btn" onclick={backToRecent}>back to recent vendors</button></p>
  {/if}
{/if}

<style>
  select { max-width: 100%; }
  .back { margin: 4px 0 0; }
  .link-btn { background: none; border: 0; padding: 0; color: #2563eb; cursor: pointer; font-size: 13px; text-decoration: underline; }
</style>
