<script>
  import { onMount } from 'svelte';
  import { location } from 'svelte-spa-router';
  import { api } from '../lib/api.js';
  import { blepActivityVersion } from '../stores/blepActivity.js';
  import AssignedTaskList from '../components/home/AssignedTaskList.svelte';
  import RecentJobsList from '../components/home/RecentJobsList.svelte';
  import ExpensesList from '../components/home/ExpensesList.svelte';
  import RecentLoginsList from '../components/home/RecentLoginsList.svelte';
  import RecentTimeList from '../components/home/RecentTimeList.svelte';
  import MyShiftsList from '../components/home/MyShiftsList.svelte';
  import MyChangeRequestsList from '../components/home/MyChangeRequestsList.svelte';
  import MyEnvelopeEditor from '../components/home/MyEnvelopeEditor.svelte';
  import ProfilePanel from '../components/home/ProfilePanel.svelte';

  let loading = $state(true);
  let error = $state('');
  let assignedTasks = $state([]);
  let recentJobs = $state([]);

  // Most tabs are plain local state, but Profile is also route-addressable:
  // #/profile renders Home with this tab active (the sidebar username link
  // targets it). Follow route changes without clobbering in-page tab clicks.
  function tabForLocation(loc) {
    return loc === '/profile' ? 'profile' : 'work';
  }
  let tab = $state(tabForLocation($location));
  let lastLocation = $state($location);
  $effect(() => {
    if ($location !== lastLocation) {
      lastLocation = $location;
      tab = tabForLocation($location);
    }
  });

  async function loadHome() {
    try {
      const data = await api.get('/api/home/');
      assignedTasks = data.assigned_tasks || [];
      recentJobs = data.recent_jobs || [];
    } catch (e) {
      error = e.message || 'Could not load home page.';
    } finally {
      loading = false;
    }
  }

  onMount(loadHome);

  // Refresh "Assigned Tasks" activity markers when a blep changes anywhere.
  let lastBlepVersion = $state(0);
  $effect(() => {
    const v = $blepActivityVersion;
    if (v !== lastBlepVersion) {
      lastBlepVersion = v;
      loadHome();
    }
  });
</script>

<div class="page-body">
<h2>Home</h2>

<nav class="page-tabs">
  <button class:active={tab === 'work'} onclick={() => tab = 'work'}>Work</button>
  <button class:active={tab === 'shifts'} onclick={() => tab = 'shifts'}>Shifts</button>
  <button class:active={tab === 'expenses'} onclick={() => tab = 'expenses'}>Expenses</button>
  <button class:active={tab === 'profile'} onclick={() => tab = 'profile'}>Profile</button>
</nav>

{#if tab === 'profile'}
  <ProfilePanel />
{:else if loading}
  <p>Loading...</p>
{:else if error}
  <p>{error}</p>
{:else if tab === 'work'}
  <AssignedTaskList tasks={assignedTasks} />
  <RecentTimeList />
  <RecentJobsList jobs={recentJobs} />
{:else if tab === 'shifts'}
  <MyEnvelopeEditor />
  <MyShiftsList />
  <MyChangeRequestsList />
  <RecentLoginsList />
{:else if tab === 'expenses'}
  <ExpensesList />
{/if}
</div>

<style>
  /* Tab strip is the shared .page-tabs (app.css). */
</style>
