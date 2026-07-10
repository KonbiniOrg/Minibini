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
  import MyShiftsList from '../components/home/MyShiftsList.svelte';
  import MyChangeRequestsList from '../components/home/MyChangeRequestsList.svelte';
  import MyEnvelopeEditor from '../components/home/MyEnvelopeEditor.svelte';
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

<div class="page-body">
<h2>Home</h2>

<SearchBox />

<ClockBand />

<nav class="page-tabs">
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
  <MyShiftsList />
  <RecentTimeList />
  <MyChangeRequestsList />
  <RecentLoginsList />
  <MyEnvelopeEditor />
{:else if tab === 'expenses'}
  <ExpensesList />
{/if}
</div>

<style>
  /* Tab strip is the shared .page-tabs (app.css). */
</style>
