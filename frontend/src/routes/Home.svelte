<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { blepActivityVersion } from '../stores/blepActivity.js';
  import SearchBox from '../components/home/SearchBox.svelte';
  import AssignedTaskList from '../components/home/AssignedTaskList.svelte';
  import RecentJobsList from '../components/home/RecentJobsList.svelte';
  import ExpensesList from '../components/home/ExpensesList.svelte';
  import RecentLoginsList from '../components/home/RecentLoginsList.svelte';
  import RecentTimeList from '../components/home/RecentTimeList.svelte';
  import ClockBand from '../components/home/ClockBand.svelte';

  let loading = $state(true);
  let error = $state('');
  let assignedTasks = $state([]);
  let recentJobs = $state([]);
  let tab = $state('work');

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

  // Refresh "My Tasks" activity markers when a blep changes anywhere.
  let lastBlepVersion = $state(0);
  $effect(() => {
    const v = $blepActivityVersion;
    if (v !== lastBlepVersion) {
      lastBlepVersion = v;
      loadHome();
    }
  });
</script>

<h2>Home</h2>

<SearchBox />

<ClockBand />

<nav class="home-tabs">
  <button class:active={tab === 'work'} onclick={() => tab = 'work'}>Work</button>
  <button class:active={tab === 'time'} onclick={() => tab = 'time'}>Time</button>
  <button class:active={tab === 'expenses'} onclick={() => tab = 'expenses'}>Expenses</button>
</nav>

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>{error}</p>
{:else if tab === 'work'}
  <AssignedTaskList tasks={assignedTasks} />
  <RecentJobsList jobs={recentJobs} />
{:else if tab === 'time'}
  <RecentTimeList />
  <RecentLoginsList />
{:else if tab === 'expenses'}
  <ExpensesList />
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
