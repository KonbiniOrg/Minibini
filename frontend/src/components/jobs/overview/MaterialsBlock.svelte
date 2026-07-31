<script>
  // MaterialsBlock — thin wrapper: pass the job's POs + materials through
  // materialsBlock() and render the result. See jobOverview.js for the rules
  // (including the three-tone coverage signal, which the lib derives from the
  // materials); this component owns no logic beyond calling the lib.
  import SummaryBlock from './SummaryBlock.svelte';
  import { materialsBlock } from '../../../lib/jobOverview.js';

  const { jobId, pos = [], materials = [], now } = $props();

  let model = $derived(materialsBlock({ jobId, pos, materials, now }));
</script>

<SummaryBlock title="Materials" {model} accent="materials" />
