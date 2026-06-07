<script>
  import { api } from '../lib/api.js';

  const { endpoint, initialTags = [] } = $props();

  let tags = $state([...initialTags]);
  let allTags = $state([]);
  let input = $state('');
  let busy = $state(false);
  let error = $state('');
  let focused = $state(false);
  let blurTimer = null;

  $effect(() => {
    api.get('/api/tags/?page_size=200')
      .then(data => { allTags = data.results || []; })
      .catch(() => {});
  });

  let suggestions = $derived(
    allTags.filter(t =>
      !tags.some(e => e.tag_id === t.tag_id) &&
      (!input.trim() || t.name.toLowerCase().includes(input.trim().toLowerCase()))
    )
  );

  let showDropdown = $derived(focused && suggestions.length > 0);

  async function addTag(name = input.trim()) {
    if (!name || busy) return;
    busy = true;
    error = '';
    try {
      tags = await api.post(`${endpoint}/add-tag/`, { name });
      input = '';
      const data = await api.get('/api/tags/?page_size=200');
      allTags = data.results || [];
    } catch (e) {
      error = e.message || 'Failed to add tag.';
    } finally {
      busy = false;
    }
  }

  async function removeTag(tagId) {
    if (busy) return;
    error = '';
    try {
      tags = await api.post(`${endpoint}/remove-tag/`, { tag_id: tagId });
    } catch (e) {
      error = e.message || 'Failed to remove tag.';
    }
  }

  function handleKeydown(e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      addTag();
    } else if (e.key === 'Escape') {
      focused = false;
    }
  }

  function handleFocus() {
    clearTimeout(blurTimer);
    focused = true;
  }

  function handleBlur() {
    // Delay so a click on a suggestion registers before the dropdown hides.
    blurTimer = setTimeout(() => { focused = false; }, 150);
  }

  function selectSuggestion(tag) {
    clearTimeout(blurTimer);
    addTag(tag.name);
  }
</script>

<div class="tags-section">
  <div class="tag-list">
    {#each tags as tag (tag.tag_id)}
      <span class="tag">
        {tag.name}
        <button type="button" class="tag-remove" onclick={() => removeTag(tag.tag_id)}>×</button>
      </span>
    {/each}
    {#if tags.length === 0}
      <span class="no-tags">No tags</span>
    {/if}
  </div>

  <div class="tag-input-wrap">
    <div class="tag-input-row">
      <input
        type="text"
        placeholder="Add tag…"
        bind:value={input}
        onkeydown={handleKeydown}
        onfocus={handleFocus}
        onblur={handleBlur}
        disabled={busy}
      />
      <button type="button" onclick={() => addTag()} disabled={busy || !input.trim()}>Add</button>
    </div>

    {#if showDropdown}
      <ul class="suggestions">
        {#each suggestions as t (t.tag_id)}
          <li>
            <button type="button" onmousedown={() => selectSuggestion(t)}>{t.name}</button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  {#if error}
    <p class="tag-error">{error}</p>
  {/if}
</div>

<style>
  .tags-section {
    margin: 0.25rem 0 0.75rem;
  }

  .tag-list {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-bottom: 6px;
    min-height: 1.5rem;
  }

  .tag {
    display: inline-flex;
    align-items: center;
    gap: 3px;
    background: #e8f0f5;
    border: 1px solid #b0c8d8;
    border-radius: 3px;
    padding: 2px 7px 2px 8px;
    font-size: 13px;
  }

  .tag-remove {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 15px;
    padding: 0 1px;
    color: #888;
    line-height: 1;
    font-family: inherit;
  }

  .tag-remove:hover {
    color: #c00;
  }

  .no-tags {
    color: #aaa;
    font-size: 13px;
  }

  .tag-input-wrap {
    position: relative;
    display: inline-block;
  }

  .tag-input-row {
    display: flex;
    gap: 4px;
  }

  .tag-input-row input {
    padding: 4px 7px;
    font-size: 13px;
    font-family: inherit;
    border: 1px solid #ccc;
    border-radius: 3px;
    width: 180px;
  }

  .suggestions {
    position: absolute;
    top: 100%;
    left: 0;
    z-index: var(--z-dropdown);
    margin: 2px 0 0;
    padding: 0;
    list-style: none;
    background: #fff;
    border: 1px solid #ccc;
    border-radius: 3px;
    min-width: 180px;
    max-height: 200px;
    overflow-y: auto;
    box-shadow: 0 2px 6px rgba(0,0,0,0.12);
  }

  .suggestions li button {
    display: block;
    width: 100%;
    text-align: left;
    padding: 6px 10px;
    font-size: 13px;
    font-family: inherit;
    background: none;
    border: none;
    cursor: pointer;
  }

  .suggestions li button:hover {
    background: #e8f0f5;
  }

  .tag-error {
    color: #c00;
    font-size: 13px;
    margin: 4px 0 0;
  }
</style>
