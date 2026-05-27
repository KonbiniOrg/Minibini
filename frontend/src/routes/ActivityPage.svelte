<script>
  import { api } from '../lib/api.js';
  import { blepActivityVersion } from '../stores/blepActivity.js';
  import BlepLogTable from '../components/time/BlepLogTable.svelte';

  // All users' current + recent work — a flat, newest-first log. Open sessions
  // sort to the top and show the green "active" tag. Read-only.
  const WINDOW_DAYS = 2;

  let bleps = $state([]);
  let loading = $state(true);
  let error = $state('');

  async function load() {
    loading = true;
    error = '';
    try {
      const since = new Date(Date.now() - WINDOW_DAYS * 24 * 60 * 60 * 1000).toISOString();
      const resp = await api.get(`/api/bleps/?since=${encodeURIComponent(since)}&page_size=100`);
      bleps = resp.results || resp;
    } catch (e) {
      error = e.message || 'Could not load activity.';
    } finally {
      loading = false;
    }
  }

  $effect(() => { load(); });

  // Reflect this client's own blep changes immediately. (Cross-client live
  // refresh is deferred to a general repolling approach — see future work.)
  let lastBlepVersion = $state(0);
  $effect(() => {
    const v = $blepActivityVersion;
    if (v !== lastBlepVersion) {
      lastBlepVersion = v;
      load();
    }
  });
</script>

<h2>Activity</h2>
<p class="sub">Current and recent work across the shop (last {WINDOW_DAYS} days).</p>

{#if loading}
  <p>Loading…</p>
{:else if error}
  <p class="error">{error}</p>
{:else if bleps.length === 0}
  <p>No recent activity.</p>
{:else}
  <BlepLogTable {bleps} showWorker={true} />
{/if}

<style>
  .sub { color: #666; font-size: 13px; margin-top: -4px; }
  .error { color: #a8071a; }
</style>
