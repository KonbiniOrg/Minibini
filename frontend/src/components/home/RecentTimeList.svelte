<script>
  import WorkSessionsList from '../time/WorkSessionsList.svelte';

  // Home "Work" tab: the current user's own sessions from the last
  // `sinceDays` days (activity_recent_days via the home payload).
  // Thin wrapper over the shared WorkSessionsList (the Users page and the
  // user detail page reuse it); no pager here.
  let { sinceDays = 7 } = $props();
</script>

<WorkSessionsList
  userId="me"
  title="Ongoing and Completed Tasks"
  {sinceDays}
  paginate={false}
  emptyText="No recent time entries."
/>
