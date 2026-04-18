<script>
  import { api } from '../lib/api.js';

  let { value = $bindable(null) } = $props();
  let query = $state('');
  let results = $state([]);
  let showResults = $state(false);

  async function search() {
    if (!query.trim()) { results = []; return; }
    try {
      const data = await api.get(`/api/jobs/?search=${encodeURIComponent(query)}&page_size=10`);
      results = data.results || data;
      showResults = true;
    } catch (e) {
      console.error(e);
    }
  }

  function pick(job) {
    value = { job_id: job.job_id, job_number: job.job_number };
    query = job.job_number;
    showResults = false;
  }

  function clear() {
    value = null;
    query = '';
    results = [];
  }
</script>

{#if value}
  <span>{value.job_number} <button type="button" onclick={clear}>Clear</button></span>
{:else}
  <input type="text" bind:value={query} oninput={search} placeholder="Search jobs…">
  {#if showResults && results.length}
    <ul>
      {#each results as job}
        <li><button type="button" onclick={() => pick(job)}>{job.job_number} — {job.description?.slice(0, 40)}</button></li>
      {/each}
    </ul>
  {/if}
{/if}
