<script>
  import { emailApi } from '../../lib/email.js';
  import EmailList from '../../components/email/EmailList.svelte';

  let emails = $state([]);
  let count = $state(0);
  let page = $state(1);
  let loading = $state(true);
  let error = $state(null);
  let refreshing = $state(false);
  let lastRefreshedAt = $state(null);
  let refreshErrors = $state([]);
  let refreshError = $state(null);
  let mailboxAddress = $state('');

  function formatTime(d) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  async function loadEmails() {
    loading = true;
    error = null;
    try {
      const data = await emailApi.list(page);
      emails = data.results;
      count = data.count;
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function runRefresh() {
    refreshing = true;
    refreshError = null;
    try {
      const stats = await emailApi.refresh();
      lastRefreshedAt = new Date();
      refreshErrors = stats.errors || [];
      if (stats.email_address) mailboxAddress = stats.email_address;
      if (stats.new > 0 && page === 1) {
        await loadEmails();
      }
    } catch (e) {
      refreshError = e.message;
    } finally {
      refreshing = false;
    }
  }

  $effect(() => {
    void page;
    loadEmails();
  });

  // Kick off background refresh once on first mount.
  let didAutoRefresh = false;
  $effect(() => {
    if (!didAutoRefresh) {
      didAutoRefresh = true;
      runRefresh();
    }
  });
</script>

<div class="page-body">
<h2>Inbox{mailboxAddress ? ` — ${mailboxAddress}` : ''}</h2>

<p>
  <button onclick={runRefresh} disabled={refreshing}>
    {refreshing ? 'Checking server…' : 'Refresh'}
  </button>
  {#if refreshing}
    <em>Checking server for new mail…</em>
  {:else if lastRefreshedAt}
    <em>Last refreshed at {formatTime(lastRefreshedAt)}</em>
  {/if}
</p>

{#if refreshError}
  <p><strong>Refresh error:</strong> {refreshError}</p>
{/if}

{#if refreshErrors.length}
  <p><strong>Server errors:</strong></p>
  <ul>
    {#each refreshErrors as err}
      <li>{err}</li>
    {/each}
  </ul>
{/if}

{#if loading}
  <p>Loading…</p>
{:else if error}
  <p>Error: {error}</p>
{:else}
  <EmailList {emails} />

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
