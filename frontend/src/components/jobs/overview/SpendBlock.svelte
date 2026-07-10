<script>
  // SpendBlock — thin wrapper: pass the job/overview payload + scope total
  // through spendBlock() and render the result. See jobOverview.js for the
  // rules; this component owns no logic beyond calling the lib.
  import SummaryBlock from './SummaryBlock.svelte';
  import { spendBlock } from '../../../lib/jobOverview.js';

  const { job, overview, scopeTotal = 0 } = $props();

  let model = $derived(spendBlock({ job, overview, scopeTotal }));
</script>

<SummaryBlock title="Spend" {model} accent="spend" />
