<script>
  import { api } from '../../lib/api.js';
  import JobList from '../../components/jobs/JobList.svelte';
  import { push, querystring } from 'svelte-spa-router';

  let jobs = $state([]);
  let count = $state(0);
  let page = $state(1);
  let loading = $state(true);
  let error = $state(null);

  let pmId = $derived(new URLSearchParams($querystring || '').get('pm') || '');
  let pmName = $derived(pmId && jobs.length ? jobs[0].project_manager_name : '');

  async function loadJobs() {
    loading = true;
    error = null;
    try {
      let url = `/api/jobs/?page=${page}`;
      if (pmId) url += `&project_manager=${pmId}`;
      const data = await api.get(url);
      jobs = data.results;
      count = data.count;
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function handleSelect(job) {
    push(`/jobs/${job.job_id}`);
  }

  // Reset to page 1 whenever the PM filter changes, then (re)load.
  $effect(() => {
    void pmId;
    page = 1;
  });

  $effect(() => {
    void page;
    void pmId;
    loadJobs();
  });
</script>

<div class="page-body">
{#if pmId}
  <h2>Jobs managed by {pmName || 'selected manager'} ({count})</h2>
{:else}
  <h2>Jobs ({count})</h2>
{/if}

<p><a href="#/jobs/new">New Job</a></p>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>Error: {error}</p>
{:else}
  <JobList {jobs} onSelect={handleSelect} />

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
{/if}
</div>
