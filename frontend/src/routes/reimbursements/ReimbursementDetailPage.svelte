<script>
  import { api } from '../../lib/api.js';
  import { link } from 'svelte-spa-router';
  import UserReimbursementPanel from '../../components/expenses/UserReimbursementPanel.svelte';

  let { params = {} } = $props();
  let user = $state(null);
  let loadError = $state('');

  async function load() {
    try {
      // Try /api/users/ (requires can_manage_config or can_manage_financials)
      const users = await api.get('/api/users/');
      user = (users.results || users).find(u => String(u.id) === String(params.id));
      if (!user) {
        loadError = 'User not found.';
      }
    } catch (err) {
      loadError = err.message || 'Could not load user.';
    }
  }

  $effect(() => { void params.id; load(); });
</script>

<div class="page-body">
{#if loadError}
  <p><em>{loadError}</em></p>
  <p><a href="/expenses" use:link>← Back to expenses</a></p>
{:else if user}
  <h2>Reimbursements — {user.first_name || ''} {user.last_name || ''} ({user.username})</h2>
  <p><a href="/expenses" use:link>← Back to expenses</a></p>
  <UserReimbursementPanel {user} />
{:else}
  <p><em>Loading...</em></p>
{/if}
</div>
