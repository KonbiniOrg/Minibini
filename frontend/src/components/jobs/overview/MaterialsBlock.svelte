<script>
  // MaterialsBlock — thin wrapper: pass the job's POs + coverage signal through
  // materialsBlock() and render the result. See jobOverview.js for the rules;
  // this component owns no logic beyond calling the lib.
  import SummaryBlock from './SummaryBlock.svelte';
  import { materialsBlock } from '../../../lib/jobOverview.js';

  const { jobId, pos = [], coverage = null, now } = $props();

  let model = $derived(materialsBlock({ jobId, pos, coverage, now }));
</script>

<SummaryBlock title="Materials" {model} accent="materials" />
