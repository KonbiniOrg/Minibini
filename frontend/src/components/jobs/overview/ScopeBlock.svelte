<script>
  // ScopeBlock — thin wrapper: pass the job's estimates/change orders/deliverable
  // count through scopeBlock() and render the result. See jobOverview.js for
  // the rules; this component owns no logic beyond calling the lib.
  import SummaryBlock from './SummaryBlock.svelte';
  import { scopeBlock } from '../../../lib/jobOverview.js';

  const { jobId, estimates = [], changeOrders = [], deliverableCount = 0, now } = $props();

  let model = $derived(scopeBlock({ jobId, estimates, changeOrders, deliverableCount, now }));
</script>

<SummaryBlock title="Scope" {model} accent="scope" />
