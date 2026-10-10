<script>
  import { api, errorMessage } from '../../lib/api.js';
  import BusinessList from '../../components/contacts/BusinessList.svelte';
  import { push } from 'svelte-spa-router';
  import LoadState from '../../components/LoadState.svelte';

  let businesses = $state([]);
  let count = $state(0);
  let page = $state(1);
  let loading = $state(true);
  let error = $state(null);

  async function loadBusinesses() {
    loading = true;
    error = null;
    try {
      const data = await api.get(`/api/businesses/?page=${page}`);
      businesses = data.results;
      count = data.count;
    } catch (e) {
      error = errorMessage(e, 'Could not load businesses.');
    } finally {
      loading = false;
    }
  }

  function handleSelect(business) {
    push(`/businesses/${business.business_id}`);
  }

  $effect(() => {
    void page;
    loadBusinesses();
  });
</script>

<div class="page-body">
<h2>Businesses ({count})</h2>

<p><a href="#/businesses/new">New Business</a></p>

<LoadState {loading} {error}>
  <BusinessList {businesses} onSelect={handleSelect} />

  {#if count > 25}
    <p>
      {#if page > 1}
        <button onclick={() => { page--; }}>Previous</button>
      {/if}
      Page {page}
      {#if page * 25 < count}
        <button onclick={() => { page++; }}>Next</button>
      {/if}
    </p>
  {/if}
</LoadState>
</div>
