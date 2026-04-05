<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import SearchBox from '../components/home/SearchBox.svelte';
  import AssignedTaskList from '../components/home/AssignedTaskList.svelte';
  import RecentJobsList from '../components/home/RecentJobsList.svelte';
  import ExpensesList from '../components/home/ExpensesList.svelte';
  import RecentLoginsList from '../components/home/RecentLoginsList.svelte';

  let loading = $state(true);
  let error = $state('');
  let assignedTasks = $state([]);
  let recentJobs = $state([]);

  onMount(async () => {
    try {
      const data = await api.get('/api/home/');
      assignedTasks = data.assigned_tasks || [];
      recentJobs = data.recent_jobs || [];
    } catch (e) {
      error = e.message || 'Could not load home page.';
    } finally {
      loading = false;
    }
  });
</script>

<h2>Home</h2>

<SearchBox />

{#if loading}
  <p>Loading...</p>
{:else if error}
  <p>{error}</p>
{:else}
  <AssignedTaskList tasks={assignedTasks} />
  <ExpensesList />
  <RecentJobsList jobs={recentJobs} />
  <RecentLoginsList />
{/if}
