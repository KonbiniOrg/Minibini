<script>
  import { api } from '../../lib/api.js';
  import { push } from 'svelte-spa-router';
  import JobList from './JobList.svelte';

  // Self-contained "jobs for a PM" list: fetches, paginates, and renders the
  // JobList table. Titling is intentionally left to the host page so this can
  // be embedded anywhere (standalone route, user detail, home). Pass no pmId
  // to list all jobs.
  const { pmId = '', onLoaded = null } = $props();

  let jobs = $state([]);
  let count = $state(0);
  let page = $state(1);
  let loading = $state(true);
  let error = $state(null);

  async function loadJobs() {
    loading = true;
    error = null;
    try {
      let url = `/api/jobs/?page=${page}`;
      if (pmId) url += `&project_manager=${pmId}`;
      const data = await api.get(url);
      jobs = data.results;
      count = data.count;
      if (onLoaded) {
        const pmName = pmId && jobs.length ? jobs[0].project_manager_name : '';
        onLoaded({ count, pmName });
      }
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
