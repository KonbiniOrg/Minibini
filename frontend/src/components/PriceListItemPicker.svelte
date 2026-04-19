<script>
  import { api } from '../lib/api.js';

  let {
    value = null,
    selectedItem = null,
    onSelect = () => {},
    disabled = false,
  } = $props();

  let query = $state('');
  let allItems = $state([]);
  let showDropdown = $state(false);
  let loading = $state(false);
  let selectedLabel = $state('');

  // Filtered view — client-side filter on the full list
  let items = $derived.by(() => {
    if (!query) return allItems;
    const lower = query.toLowerCase();
    return allItems.filter(i =>
      i.code.toLowerCase().includes(lower) ||
      i.description.toLowerCase().includes(lower)
    );
  });

  // Resolve the displayed label from one of three sources, in priority order:
  //   1. selectedItem prop (full object provided by parent — used for prefill)
  //   2. value + already-loaded allItems (typical edit-mode case)
  //   3. value with no catalog yet → kick off the fetch
  $effect(() => {
    if (selectedItem) {
      selectedLabel = `${selectedItem.code} — ${selectedItem.description}`;
      return;
    }
    if (value) {
      if (allItems.length > 0) {
        const found = allItems.find(i => i.price_list_item_id === value);
        if (found) selectedLabel = `${found.code} — ${found.description}`;
      } else {
        fetchAllItems();
      }
    } else {
      selectedLabel = '';
    }
  });

  async function fetchAllItems() {
    if (allItems.length > 0) return; // already loaded
    loading = true;
    try {
      // Fetch all PLIs without pagination. The catalog is expected to be
      // small (a couple hundred items at most). If it grows very large,
      // this should switch to server-side search with SearchFilter.
      const resp = await api.get('/api/price-list-items/?page_size=9999');
      allItems = resp.results || resp;
    } catch (e) {
      allItems = [];
    } finally {
      loading = false;
    }
  }

  function handleInput(e) {
    query = e.target.value;
    showDropdown = true;
  }

  function handleFocus() {
    showDropdown = true;
    fetchAllItems();
  }

  function handleBlur() {
    // Delay to allow click on dropdown item
    setTimeout(() => { showDropdown = false; }, 200);
  }

  function selectItem(item) {
    if (item) {
      selectedLabel = `${item.code} — ${item.description}`;
      query = '';
    } else {
      selectedLabel = '';
      query = '';
    }
    showDropdown = false;
    onSelect(item);
  }

  function clear() {
    selectedLabel = '';
    query = '';
    onSelect(null);
  }
</script>

<div class="pli-picker">
  {#if selectedLabel && !disabled}
    <span class="selected-label">{selectedLabel}</span>
    <button type="button" class="clear-btn" onclick={clear}>x</button>
  {:else if selectedLabel && disabled}
    <span class="selected-label">{selectedLabel}</span>
  {:else}
    <input
      type="text"
      placeholder="Search price list items..."
      value={query}
      oninput={handleInput}
      onfocus={handleFocus}
      onblur={handleBlur}
      {disabled}
    >
    {#if showDropdown && !disabled}
      <div class="dropdown" role="listbox">
        <div class="dropdown-item none-option" role="option" onmousedown={() => selectItem(null)}>
          None (freeform)
        </div>
        {#if loading}
          <div class="dropdown-item loading">Searching...</div>
        {:else if items.length === 0}
          <div class="dropdown-item loading">No items found</div>
        {:else}
          {#each items as item}
            <div class="dropdown-item" role="option" onmousedown={() => selectItem(item)}>
              <strong>{item.code}</strong> — {item.description}
            </div>
          {/each}
        {/if}
      </div>
    {/if}
  {/if}
</div>

<style>
  .pli-picker { position: relative; display: inline-block; width: 100%; }
  .pli-picker input { width: 100%; box-sizing: border-box; padding: 4px 8px; }
  .selected-label { font-size: 14px; }
  .clear-btn {
    background: none; border: 1px solid #ccc; cursor: pointer;
    padding: 1px 6px; margin-left: 6px; font-size: 12px; border-radius: 3px;
  }
  .dropdown {
    position: absolute; top: 100%; left: 0; right: 0;
    background: white; border: 1px solid #ccc; max-height: 200px;
    overflow-y: auto; z-index: 300;
  }
  .dropdown-item {
    padding: 6px 8px; cursor: pointer; font-size: 13px;
  }
  .dropdown-item:hover { background: #f0f0f0; }
  .none-option { color: #666; font-style: italic; border-bottom: 1px solid #eee; }
  .loading { color: #888; font-style: italic; cursor: default; }
</style>
