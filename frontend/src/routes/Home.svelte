<script>
  import { onMount } from 'svelte';
  import { api } from '../lib/api.js';
  import { user } from '../stores/auth.js';
  import SearchBox from '../components/home/SearchBox.svelte';
  import AssignedTaskList from '../components/home/AssignedTaskList.svelte';
  import RecentJobsList from '../components/home/RecentJobsList.svelte';
  import ExpensesList from '../components/home/ExpensesList.svelte';
  import RecentLoginsList from '../components/home/RecentLoginsList.svelte';
  import TimeManagementList from '../components/home/TimeManagementList.svelte';
  import ExpenseApprovalsList from '../components/home/ExpenseApprovalsList.svelte';
  import RecentTimeList from '../components/home/RecentTimeList.svelte';

  let loading = $state(true);
  let error = $state('');
  let assignedTasks = $state([]);
  let recentJobs = $state([]);

  function hasPerm(perm) {
    return $user?.permissions?.includes(perm) ?? false;
  }

  let canManageTime = $derived(hasPerm('can_manage_time'));
  let canApproveExpenses = $derived(hasPerm('can_approve_expenses'));

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
  <RecentTimeList />
  <ExpensesList />
  {#if canManageTime}
    <TimeManagementList />
  {/if}
  {#if canApproveExpenses}
    <ExpenseApprovalsList />
  {/if}
  <RecentJobsList jobs={recentJobs} />
  <RecentLoginsList />
{/if}
