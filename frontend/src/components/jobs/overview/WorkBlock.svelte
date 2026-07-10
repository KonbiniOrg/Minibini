<script>
  // WorkBlock — thin wrapper: pass the job/overview payload through workBlock()
  // and render the result. See jobOverview.js for the rules; this component
  // owns no logic beyond calling the lib.
  import SummaryBlock from './SummaryBlock.svelte';
  import { workBlock } from '../../../lib/jobOverview.js';

  const { job, overview, tasksPlanned = 0 } = $props();

  let model = $derived(workBlock({ job, overview, tasksPlanned }));
</script>

<SummaryBlock title="Work" {model} accent="work" />
