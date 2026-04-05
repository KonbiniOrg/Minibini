<script>
  import { push } from 'svelte-spa-router';

  let query = $state('');

  function handleSubmit(e) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    push(`/search?q=${encodeURIComponent(q)}`);
  }
</script>

<form onsubmit={handleSubmit}>
  <p>
    <input
      type="text"
      placeholder="Search..."
      bind:value={query}
      aria-label="Search"
    />
    <button type="submit">Search</button>
  </p>
</form>
