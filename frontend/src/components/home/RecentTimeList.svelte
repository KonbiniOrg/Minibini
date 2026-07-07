<script>
  import WorkSessionsList from '../time/WorkSessionsList.svelte';

  // Home "Time" tab: the current user's own sessions from the last 7 days.
  // Thin wrapper over the shared WorkSessionsList (the Users page and the
  // user detail page reuse it); home keeps its historical heading and no
  // pager until the home-page naming pass.
</script>

<WorkSessionsList
  userId="me"
  title="Recent Time"
  sinceDays={7}
  paginate={false}
  emptyText="No recent time entries."
/>
