<script>
  import { api } from '../../lib/api.js';
  import JobList from '../../components/jobs/JobList.svelte';
  import { push } from 'svelte-spa-router';

  let jobs = $state([]);
  let count = $state(0);
  let page = $state(1);
  let loading = $state(true);
  let error = $state(null);

  async function loadJobs() {
    loading = true;
    error = null;
    try {
      const data = await api.get(`/api/jobs/?page=${page}`);
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

  $effect(() => {
    void page;
    loadJobs();
  });
</script>

<h2>Jobs ({count})</h2>

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
