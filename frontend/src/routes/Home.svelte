<script>
  import { onMount } from 'svelte';
  import { location } from 'svelte-spa-router';
  import { api } from '../lib/api.js';
  import { blepActivityVersion } from '../stores/blepActivity.js';
  import { user as currentUser } from '../stores/auth.js';
  import PmJobList from '../components/jobs/PmJobList.svelte';
  import CurrentTaskList from '../components/home/CurrentTaskList.svelte';
  import RecentTaskList from '../components/home/RecentTaskList.svelte';
  import ExpensesList from '../components/home/ExpensesList.svelte';
  import RecentLoginsList from '../components/home/RecentLoginsList.svelte';
  import MyTimeslips from '../components/home/MyTimeslips.svelte';
  import MyShiftsList from '../components/home/MyShiftsList.svelte';
  import MyChangeRequestsList from '../components/home/MyChangeRequestsList.svelte';
  import MyEnvelopeEditor from '../components/home/MyEnvelopeEditor.svelte';
  import ProfilePanel from '../components/home/ProfilePanel.svelte';
  import HelpPanel from '../components/home/HelpPanel.svelte';

  let loading = $state(true);
  let error = $state('');
  let currentTasks = $state([]);
  let recentTasks = $state([]);
  let recentLogins = $state([]);
  let recentDays = $state(7);

  // Most tabs are plain local state, but Profile and Help are also
  // route-addressable: #/profile and #/help render Home with that tab
  // active (the sidebar username link and in-app help links target them).
  // Follow route changes without clobbering in-page tab clicks.
  function tabForLocation(loc) {
    if (loc === '/profile') return 'profile';
    if (loc === '/help') return 'help';
    return 'work';
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
      currentTasks = data.current_tasks || [];
      recentTasks = data.recent_tasks || [];
      recentLogins = data.recent_logins || [];
      recentDays = data.recent_days ?? 7;
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
  <button class:active={tab === 'help'} onclick={() => tab = 'help'}>Help</button>
</nav>

{#if tab === 'profile'}
  <ProfilePanel />
{:else if tab === 'help'}
  <HelpPanel />
{:else if loading}
  <p>Loading...</p>
{:else if error}
  <p>{error}</p>
{:else if tab === 'work'}
  <CurrentTaskList tasks={currentTasks} />
  {#if $currentUser}
    <h3>Jobs I manage</h3>
    <PmJobList pmId={$currentUser.id} />
  {/if}
  <RecentTaskList tasks={recentTasks} sinceDays={recentDays} />
{:else if tab === 'shifts'}
  <MyEnvelopeEditor />
  <MyShiftsList sinceDays={recentDays} />
  <MyTimeslips sinceDays={recentDays} />
  <MyChangeRequestsList />
  <RecentLoginsList logins={recentLogins} sinceDays={recentDays} />
{:else if tab === 'expenses'}
  <ExpensesList />
{/if}
</div>

<style>
  /* Tab strip is the shared .page-tabs (app.css). */
</style>
