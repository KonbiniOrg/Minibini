<script>
  import WorkSessionsList from '../time/WorkSessionsList.svelte';

  // Home "Work" tab: the current user's own sessions from the last 7 days.
  // Thin wrapper over the shared WorkSessionsList (the Users page and the
  // user detail page reuse it); no pager here.
</script>

<WorkSessionsList
  userId="me"
  title="Ongoing and Completed Tasks"
  sinceDays={7}
  paginate={false}
  emptyText="No recent time entries."
/>
