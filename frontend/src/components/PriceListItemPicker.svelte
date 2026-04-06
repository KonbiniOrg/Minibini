<script>
  import { api } from '../lib/api.js';

  let {
    value = null,
    onSelect = () => {},
    disabled = false,
  } = $props();

  let query = $state('');
  let items = $state([]);
  let showDropdown = $state(false);
  let loading = $state(false);
  let debounceTimer = $state(null);
  let selectedLabel = $state('');

  // When value changes externally (e.g. edit mode), resolve the label
  $effect(() => {
    if (value && items.length > 0) {
      const found = items.find(i => i.price_list_item_id === value);
      if (found) selectedLabel = `${found.code} — ${found.description}`;
    } else if (!value) {
      selectedLabel = '';
    }
  });

  function debounceSearch(q) {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => fetchItems(q), 300);
  }

  async function fetchItems(q) {
    loading = true;
    try {
      const url = q
        ? `/api/price-list-items/?page_size=50&code=${encodeURIComponent(q)}`
        : '/api/price-list-items/?page_size=50';
      const resp = await api.get(url);
      items = resp.results || resp;
      // Client-side filter if API doesn't support search
      if (q) {
        const lower = q.toLowerCase();
        items = items.filter(i =>
          i.code.toLowerCase().includes(lower) ||
          i.description.toLowerCase().includes(lower)
        );
      }
    } catch (e) {
      items = [];
    } finally {
      loading = false;
    }
  }

  function handleInput(e) {
    query = e.target.value;
    showDropdown = true;
    debounceSearch(query);
  }

  function handleFocus() {
    showDropdown = true;
    if (items.length === 0) fetchItems(query);
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
