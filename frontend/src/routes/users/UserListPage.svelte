<script>
  import { link } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { canManageTime, canManageFinancials } from '../../stores/permissions.js';
  import ShiftRequestQueue from '../../components/users/ShiftRequestQueue.svelte';
  import PayrollReport from '../../components/users/PayrollReport.svelte';
  import WorkSessionsList from '../../components/time/WorkSessionsList.svelte';
  import LoadState from '../../components/LoadState.svelte';
  import DataTable from '../../components/DataTable.svelte';

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
      loadError = errorMessage(err, 'Could not load users.');
    } finally {
      loading = false;
    }
  }

  load();
</script>

<div class="page-body">
<h2>Users</h2>

<nav class="page-tabs">
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

<LoadState {loading} error={loadError}>
<DataTable
  rows={users}
  key={(user) => user.id}
  emptyText="No users found."
  columns={[
    { id: 'username',    label: 'Username',    field: 'username' },
    { id: 'name',        label: 'Name',        cell: nameCell },
    { id: 'email',       label: 'Email',       field: 'email' },
    { id: 'permissions', label: 'Permissions', cell: permissionsCell },
    { id: 'status',      label: 'Status',      cell: statusCell },
    { id: 'actions',     label: 'Actions',     cell: actionsCell },
  ]}
/>
</LoadState>
{/if}
</div>


{#snippet nameCell(user)}{user.first_name} {user.last_name}{/snippet}
{#snippet permissionsCell(user)}{formatPermissions(user.permissions)}{/snippet}
{#snippet statusCell(user)}{#if user.is_active}Active{:else}<em>Deactivated</em>{/if}{/snippet}
{#snippet actionsCell(user)}<a href="/users/{user.id}" use:link>View</a>{/snippet}

<style>
  /* Tab strip is the shared .page-tabs (app.css). */
</style>
