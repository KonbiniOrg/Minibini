<script>
  import { api } from '../../lib/api.js';
  import { push } from 'svelte-spa-router';

  let allItems = $state([]);
  let count = $state(0);
  let page = $state(1);
  let loading = $state(true);
  let error = $state(null);
  let letterFilter = $state('');
  let searchQuery = $state('');
  let showContacts = $state(true);
  let showBusinesses = $state(true);
  let allTags = $state([]);
  let selectedTagIds = $state([]);

  const FETCH_SIZE = 100;
  const PAGE_SIZE = 25;
  const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

  let filteredItems = $derived(allItems.filter(item =>
    (item._type === 'contact' && showContacts) ||
    (item._type === 'business' && showBusinesses)
  ));
  let pageItems = $derived(filteredItems.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE));
  let totalPages = $derived(Math.ceil(filteredItems.length / PAGE_SIZE));

  $effect(() => {
    api.get('/api/tags/?page_size=200')
      .then(data => { allTags = data.results || []; })
      .catch(() => {});
  });

  async function loadAll() {
    loading = true;
    error = null;
    try {
      const params = new URLSearchParams({ page_size: FETCH_SIZE });
      if (letterFilter) params.set('starts_with', letterFilter);
      if (searchQuery.trim()) params.set('search', searchQuery.trim());
      for (const id of selectedTagIds) params.append('tag', id);

      const [contactData, businessData] = await Promise.all([
        api.get(`/api/contacts/?${params}`),
        api.get(`/api/businesses/?${params}`),
      ]);

      const contacts = (contactData.results || []).map(c => ({
        _type: 'contact',
        _id: c.contact_id,
        _name: c.name,
        name: c.name,
        email: c.email,
        phone: c.work_number || c.mobile_number || c.home_number || '',
        tags: c.tags || [],
        href: `#/contacts/${c.contact_id}`,
      }));

      const businesses = (businessData.results || []).map(b => ({
        _type: 'business',
        _id: b.business_id,
        _name: b.business_name,
        name: b.business_name,
        email: '',
        phone: b.business_phone || '',
        tags: b.tags || [],
        href: `#/businesses/${b.business_id}`,
      }));

      allItems = [...contacts, ...businesses].sort((a, b) =>
        a._name.localeCompare(b._name)
      );
      count = contactData.count + businessData.count;
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function selectLetter(letter) {
    letterFilter = letterFilter === letter ? '' : letter;
    page = 1;
  }

  function toggleTag(id) {
    selectedTagIds = selectedTagIds.includes(id)
      ? selectedTagIds.filter(t => t !== id)
      : [...selectedTagIds, id];
    page = 1;
  }

  function handleSearchInput() {
    page = 1;
  }

  $effect(() => {
    void letterFilter;
    void searchQuery;
    void selectedTagIds;
    loadAll();
  });
</script>

<h2>Contacts &amp; Businesses ({count})</h2>

<p><a href="#/contacts/new">New Contact</a> &nbsp; <a href="#/businesses/new">New Business</a></p>

<div class="index-bar">
  <button class:active={letterFilter === ''} onclick={() => selectLetter('')}>All</button>
  {#each LETTERS as letter}
    <button class:active={letterFilter === letter} onclick={() => selectLetter(letter)}>{letter}</button>
  {/each}
  <button class:active={letterFilter === '0-9'} onclick={() => selectLetter('0-9')}>0–9</button>
</div>

<div class="type-filter">
  <label><input type="checkbox" bind:checked={showContacts}> Contacts</label>
  <label><input type="checkbox" bind:checked={showBusinesses}> Businesses</label>
</div>

{#if allTags.length > 0}
  <div class="tag-filter">
    <span class="tag-filter-label">Tags:</span>
    {#each allTags as tag (tag.tag_id)}
      <button
        class="tag-chip"
        class:active={selectedTagIds.includes(tag.tag_id)}
        onclick={() => toggleTag(tag.tag_id)}
      >{tag.name}</button>
    {/each}
    {#if selectedTagIds.length > 0}
      <button class="tag-clear" onclick={() => { selectedTagIds = []; page = 1; }}>Clear</button>
    {/if}
  </div>
{/if}

<p>
  <input
    class="search-input"
    type="search"
    placeholder={letterFilter ? `Search within "${letterFilter === '0-9' ? '0–9' : letterFilter}"…` : 'Search all contacts & businesses…'}
    bind:value={searchQuery}
    oninput={handleSearchInput}
  />
</p>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else if filteredItems.length === 0}
  <p>No results found.</p>
{:else}
  <table class="data-table">
    <thead>
      <tr>
        <th>Name</th>
        <th>Type</th>
        <th>Email</th>
        <th>Phone</th>
        <th>Tags</th>
      </tr>
    </thead>
    <tbody>
      {#each pageItems as item}
        <tr>
          <td><a href={item.href}>{item.name}</a></td>
          <td>{item._type === 'contact' ? 'Contact' : 'Business'}</td>
          <td>{item.email}</td>
          <td>{item.phone}</td>
          <td>
            {#each item.tags.slice(0, 3) as tag (tag.tag_id)}
              <span class="row-tag">{tag.name}</span>
            {/each}
            {#if item.tags.length > 3}
              <span class="row-tag-more">+{item.tags.length - 3} more</span>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>

  {#if totalPages > 1}
    <p>
      {#if page > 1}
        <button onclick={() => { page--; }}>Previous</button>
      {/if}
      Page {page} of {totalPages}
      {#if page < totalPages}
        <button onclick={() => { page++; }}>Next</button>
      {/if}
    </p>
  {/if}
{/if}

<style>
  .index-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
    margin-bottom: 1rem;
  }

  .index-bar button {
    padding: 3px 7px;
    font-size: 13px;
    cursor: pointer;
    border: 1px solid #ccc;
    background: #f5f5f5;
    border-radius: 3px;
    font-family: inherit;
  }

  .index-bar button:hover { background: #e0e0e0; }

  .index-bar button.active {
    background: #1a3344;
    color: #fff;
    border-color: #1a3344;
  }

  .type-filter {
    display: flex;
    gap: 1rem;
    margin-bottom: 0.75rem;
    font-size: 14px;
  }

  .tag-filter {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
    margin-bottom: 0.75rem;
  }

  .tag-filter-label {
    font-size: 13px;
    color: #555;
    margin-right: 2px;
  }

  .tag-chip {
    padding: 2px 8px;
    font-size: 12px;
    cursor: pointer;
    border: 1px solid #b0c8d8;
    background: #e8f0f5;
    border-radius: 3px;
    font-family: inherit;
  }

  .tag-chip:hover { background: #d0e4f0; }

  .tag-chip.active {
    background: #1a3344;
    color: #fff;
    border-color: #1a3344;
  }

  .tag-clear {
    padding: 2px 8px;
    font-size: 12px;
    cursor: pointer;
    border: 1px solid #ccc;
    background: #f5f5f5;
    border-radius: 3px;
    font-family: inherit;
    color: #555;
  }

  .tag-clear:hover { background: #e0e0e0; }

  .search-input {
    width: 280px;
    padding: 5px 8px;
    font-size: 14px;
    font-family: inherit;
    border: 1px solid #ccc;
    border-radius: 3px;
  }

  .row-tag {
    display: inline-block;
    background: #e8f0f5;
    border: 1px solid #b0c8d8;
    border-radius: 3px;
    padding: 1px 5px;
    font-size: 11px;
    margin-right: 3px;
    white-space: nowrap;
  }

  .row-tag-more {
    font-size: 11px;
    color: #666;
    white-space: nowrap;
  }
</style>
