<script>
  import WorkSessionsList from '../time/WorkSessionsList.svelte';

  // Home "Shifts" tab: the current user's own timeslips (work sessions /
  // bleps) from the last `sinceDays` days, with the Edit / Request-Edit
  // affordances — this is the editing surface for recent time entries.
  // Thin wrapper over the shared WorkSessionsList (the Users page and the
  // user detail page reuse it); no pager here.
  let { sinceDays = 7 } = $props();
</script>

<WorkSessionsList
  userId="me"
  title="My Timeslips"
  {sinceDays}
  paginate={false}
  emptyText="No recent timeslips."
/>
