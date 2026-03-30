<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';

  let status = $state(null);
  let loading = $state(true);
  let error = $state(null);
  let disconnecting = $state(false);

  async function loadStatus() {
    loading = true;
    error = null;
    try {
      status = await api.get('/api/qbo/status/');
    } catch (e) {
      // 403 means user doesn't have can_manage_config — hide the card
      if (e.status === 403) {
        status = null;
      } else {
        error = e.message || 'Failed to load QBO status';
      }
    } finally {
      loading = false;
    }
  }

  async function disconnect() {
    if (!confirm('Disconnect from QuickBooks Online?')) return;
    disconnecting = true;
    try {
      await api.post('/api/qbo/disconnect/');
      await loadStatus();
    } catch (e) {
      error = e.message || 'Failed to disconnect';
    } finally {
      disconnecting = false;
    }
  }

  onMount(() => {
    loadStatus();
  });
</script>

{#if loading}
  <p>Loading QuickBooks status...</p>
{:else if status === null}
  <!-- User lacks permission or endpoint unavailable — hide card -->
{:else if error}
  <p><strong>Error:</strong> {error}</p>
{:else}
  <fieldset>
    <legend><strong>QuickBooks Online</strong></legend>

    {#if status.status === 'connected'}
      <p>Status: <strong>Connected</strong></p>
      <p>Company ID: {status.realm_id}</p>
      <p>Connected: {new Date(status.connected_at).toLocaleDateString()}</p>
      {#if status.last_sync_at}
        <p>Last sync: {new Date(status.last_sync_at).toLocaleDateString()}</p>
      {/if}
      {#if status.refresh_token_expiring_soon}
        <p><strong>Warning:</strong> Connection expiring soon. Please reconnect.</p>
      {/if}
      <p>
        <button onclick={disconnect} disabled={disconnecting}>
          {disconnecting ? 'Disconnecting...' : 'Disconnect'}
        </button>
        <a href="/api/qbo/connect/">Reconnect</a>
      </p>
    {:else}
      <p>Status: <strong>Not connected</strong></p>
      <p><a href="/api/qbo/connect/">Connect to QuickBooks</a></p>
    {/if}
  </fieldset>
{/if}
