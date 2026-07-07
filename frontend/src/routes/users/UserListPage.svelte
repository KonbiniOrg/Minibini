<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { canManageTime, canManageFinancials } from '../../stores/permissions.js';
  import ShiftRequestQueue from '../../components/users/ShiftRequestQueue.svelte';
  import PayrollReport from '../../components/users/PayrollReport.svelte';
  import WorkSessionsList from '../../components/time/WorkSessionsList.svelte';

  let tab = $state('users');
  const canSeeShifts = $derived($canManageTime || $canManageFinancials);

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

<nav class="home-tabs">
  <button class:active={tab === 'users'} onclick={() => tab = 'users'}>Users</button>
  {#if canSeeShifts}
    <button class:active={tab === 'shifts'} onclick={() => tab = 'shifts'}>Shifts</button>
    <button class:active={tab === 'sessions'} onclick={() => tab = 'sessions'}>Work Sessions</button>
  {/if}
</nav>

{#if tab === 'shifts'}
  <ShiftRequestQueue />
  <PayrollReport />
{:else if tab === 'sessions'}
  <!-- All users' work sessions (bleps), recent-first, paged. -->
  <WorkSessionsList showWorker={true} title="" />
{:else}

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
{/if}

<style>
  .home-tabs {
    display: flex;
    gap: 0;
    border-bottom: 2px solid #ccc;
    margin-bottom: 1em;
  }
  .home-tabs button {
    padding: 0.4em 1.2em;
    border: 2px solid #ccc;
    border-bottom: none;
    background: #f5f5f5;
    cursor: pointer;
    margin-bottom: -2px;
  }
  .home-tabs button.active {
    background: white;
    border-bottom: 2px solid white;
    font-weight: bold;
  }
</style>
