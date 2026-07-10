<script>
  // DeliveryBlock — thin wrapper: pass the job's shipments + deliverable count
  // through deliveryBlock() and render the result. See jobOverview.js for the
  // rules; this component owns no logic beyond calling the lib.
  import SummaryBlock from './SummaryBlock.svelte';
  import { deliveryBlock } from '../../../lib/jobOverview.js';

  const { shipments = [], deliverableCount = 0, job, now } = $props();

  let model = $derived(deliveryBlock({ shipments, deliverableCount, job, now }));
</script>

<SummaryBlock title="Delivery" {model} />
