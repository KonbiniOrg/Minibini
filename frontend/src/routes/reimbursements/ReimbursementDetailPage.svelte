<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { link } from 'svelte-spa-router';
  import UserReimbursementPanel from '../../components/expenses/UserReimbursementPanel.svelte';
  import LoadState from '../../components/LoadState.svelte';

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
      loadError = errorMessage(err, 'Could not load user.');
    }
  }

  $effect(() => { void params.id; load(); });
</script>

<div class="page-body">
<LoadState loading={!user && !loadError} error={loadError}>
{#if user}
  <h2>Reimbursements — {user.first_name || ''} {user.last_name || ''} ({user.username})</h2>
  <p><a href="/expenses" use:link>← Back to expenses</a></p>
  <UserReimbursementPanel {user} />
{/if}
</LoadState>
{#if loadError}<p><a href="/expenses" use:link>← Back to expenses</a></p>{/if}
</div>
