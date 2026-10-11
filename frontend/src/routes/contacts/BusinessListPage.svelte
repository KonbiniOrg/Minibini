<script>
  import { api, errorMessage } from '../../lib/api.js';
  import BusinessList from '../../components/contacts/BusinessList.svelte';
  import BusinessFormModal from '../../components/contacts/BusinessFormModal.svelte';
  import { canManageJobs } from '../../stores/permissions.js';
  import { push } from 'svelte-spa-router';
  import LoadState from '../../components/LoadState.svelte';
  import Pager from '../../components/Pager.svelte';

  let businesses = $state([]);
  let newOpen = $state(false);
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

<p>
  {#if $canManageJobs}
    <button type="button" onclick={() => { newOpen = true; }}>New Business</button>
  {/if}
</p>
<BusinessFormModal open={newOpen} onClose={() => { newOpen = false; }} />

<LoadState {loading} {error}>
  <BusinessList {businesses} onSelect={handleSelect} />

  <Pager {page} {count} onPage={(n) => { page = n; }} />
</LoadState>
</div>
