<script>
  import { link, querystring } from 'svelte-spa-router';
  import { api } from '../lib/api.js';

  let results = $state(null);
  let loading = $state(false);
  let error = $state('');

  let query = $derived.by(() => {
    const params = new URLSearchParams($querystring || '');
    return params.get('q') || '';
  });

  $effect(() => {
    const q = query;
    if (!q) {
      results = null;
      return;
    }
    loading = true;
    error = '';
    api.get(`/api/search/?q=${encodeURIComponent(q)}`)
      .then((data) => { results = data; })
      .catch((e) => { error = e.message || 'Search failed.'; })
      .finally(() => { loading = false; });
  });
</script>

<h2>Search{query ? `: ${query}` : ''}</h2>

{#if !query}
  <p>Enter a search term.</p>
{:else if loading}
  <p>Loading...</p>
{:else if error}
  <p>{error}</p>
{:else if results}
  <pre>{JSON.stringify(results, null, 2)}</pre>
{/if}
