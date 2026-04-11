<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';

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
  <table border="1">
    <thead>
      <tr>
        <th>Username</th>
        <th>Name</th>
        <th>Email</th>
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
