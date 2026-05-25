<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';

  // Short labels for the permission column — keep the table narrow.
  const ATOM_SHORT_LABELS = {
    can_manage_jobs: 'jobs',
    can_manage_financials: 'financials',
    can_manage_time: 'time',
    can_manage_config: 'config',
  };

  function formatPermissions(codenames) {
    if (!codenames || codenames.length === 0) return '';
    return codenames
      .map((c) => ATOM_SHORT_LABELS[c] || c)
      .join(', ');
  }

  let users = $state([]);
  let loading = $state(true);
  let loadError = $state('');

  async function load() {
    loading = true;
    loadError = '';
    try {
      users = await api.get('/api/users/');
    } catch (err) {
      loadError = err.message || 'Could not load users.';
    } finally {
      loading = false;
    }
  }

  load();
</script>

<h2>Users</h2>

<p><a href="/users/new" use:link>New user</a></p>

{#if loading}
  <p>Loading...</p>
{:else if loadError}
  <p>{loadError}</p>
{:else if users.length === 0}
  <p>No users found.</p>
{:else}
  <table class="data-table">
    <thead>
      <tr>
        <th>Username</th>
        <th>Name</th>
        <th>Email</th>
        <th>Permissions</th>
        <th>Status</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
      {#each users as user (user.id)}
        <tr>
          <td>{user.username}</td>
          <td>
            {user.first_name} {user.last_name}
            {#if user.is_superuser} <em>(superuser)</em>{/if}
          </td>
          <td>{user.email}</td>
          <td>{formatPermissions(user.permissions)}</td>
          <td>
            {#if user.is_active}
              Active
            {:else}
              <em>Deactivated</em>
            {/if}
          </td>
          <td><a href="/users/{user.id}" use:link>View</a></td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
