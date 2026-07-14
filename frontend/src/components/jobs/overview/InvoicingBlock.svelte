<script>
  // InvoicingBlock — thin wrapper: pass the job's invoices + scope total
  // through invoicingBlock() and render the result. See jobOverview.js for
  // the rules; this component owns no logic beyond calling the lib.
  import SummaryBlock from './SummaryBlock.svelte';
  import { invoicingBlock } from '../../../lib/jobOverview.js';

  const { invoices = [], scopeTotal = 0, invoicedTotal = 0, now } = $props();

  let model = $derived(invoicingBlock({ invoices, scopeTotal, invoicedTotal, now }));
</script>

<SummaryBlock title="Invoicing" {model} accent="invoicing" />
