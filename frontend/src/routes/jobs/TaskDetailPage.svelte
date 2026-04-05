<script>
  import { link } from 'svelte-spa-router';
  let { params = {} } = $props();
</script>

<h2>Task #{params.taskId}</h2>
<p>Task detail — coming soon.</p>
<p><a href={`/jobs/${params.jobId}`} use:link>&laquo; Back to job</a></p>
