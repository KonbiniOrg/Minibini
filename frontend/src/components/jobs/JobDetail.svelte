<script>
  // JobDetail — the job overview page. It is the job's *summary*: six lifecycle
  // blocks (Scope → Work → Materials → Spend → Invoicing → Delivery) in fixed
  // order, each with a temperature driven by job state. It lists nothing (the
  // section pages do that) — blocks show aggregates, clocks, and one-line facts.
  //
  // The block rules/copy live in lib/jobOverview.js; the block components are
  // dumb renderers. This component is glue: it mounts JobShell (header + context
  // band + rail, like every other job page), threads the page's fetched data
  // into the blocks, and derives the two inputs the lib can't take raw
  // (materials coverage signal; the estimate arrays/counts).
  import JobShell from './JobShell.svelte';
  import ScopeBlock from './overview/ScopeBlock.svelte';
  import WorkBlock from './overview/WorkBlock.svelte';
  import MaterialsBlock from './overview/MaterialsBlock.svelte';
  import SpendBlock from './overview/SpendBlock.svelte';
  import InvoicingBlock from './overview/InvoicingBlock.svelte';
  import DeliveryBlock from './overview/DeliveryBlock.svelte';
  import { materialStatus } from '../../lib/materialStatus.js';

  const {
    job,
    contact = null,
    estimates = null,
    invoices = null,
    purchaseOrders = null,
    changeOrders = null,
    shipments = null,
    deliverableCount = 0,
    overview = null,
    // The clock. The lib is pure — the page supplies `now` once per load so
    // every block reads the same instant (JobDetailPage creates it).
    now = new Date(),
    onStatusChange = null,
  } = $props();

  // List payloads arrive either paginated ({results}) or as a bare array.
  const asList = (v) => (v ? (v.results ?? v) : []);

  let estimateList = $derived(asList(estimates));
  let changeOrderList = $derived(asList(changeOrders));
  let invoiceList = $derived(asList(invoices));
  let poList = $derived(asList(purchaseOrders));
  let shipmentList = $derived(asList(shipments));

  // Scope total = the job's authoritative estimated amount (financials
  // `_estimated`), already on the job payload. Feeds Spend's "% of scope" and
  // Invoicing's "billed %".
  let scopeTotal = $derived(Number(job?.estimated_amount) || 0);

  // Billed total = the job's authoritative invoiced amount (financials
  // `_invoiced`: draft/cancelled/superseded excluded), same figure as the
  // header's P&L — the block never re-decides which invoices count.
  let invoicedTotal = $derived(Number(job?.invoiced_amount) || 0);

  // Tasks planned ahead of approval (drives the Work-dormant copy). The overview
  // endpoint counts tasks regardless of job status.
  let tasksPlanned = $derived(Number(overview?.work?.tasks_total) || 0);

  // Materials coverage signal for the Materials block. Derived from the SAME
  // per-material source of truth the rest of the app uses (materialStatus.js):
  // a material whose status is 'needed' is short of stock with no incoming
  // supply — the "order action" red state. Any such material short-circuits the
  // job to SHORT; if materials exist and none are short, coverage reads OK; with
  // no materials at all we pass null and the lib omits the Coverage stat.
  let coverage = $derived.by(() => {
    const materials = job?.materials || [];
    if (!materials.length) return null;
    const shortCount = materials.filter((m) => materialStatus(m).key === 'needed').length;
    if (shortCount > 0) {
      return {
        label: 'SHORT',
        tone: 'bad',
        sub: `${shortCount} ${shortCount === 1 ? 'material needs' : 'materials need'} ordering`,
      };
    }
    return { label: 'OK', tone: 'good' };
  });
</script>

<JobShell {job} {contact} current="overview" onJobChange={onStatusChange}>
  <div class="page-body">
    {#if job.status === 'draft' && job.latest_change_request}
      <div class="change-request-banner">
        <strong>Customer requested changes:</strong>
        <span class="cr-text">{job.latest_change_request.text || '(no comment provided)'}</span>
        <span class="cr-hint">Edit the revised estimate, then re-send it.</span>
      </div>
    {/if}

    <div class="summary-blocks">
      <ScopeBlock
        estimates={estimateList}
        changeOrders={changeOrderList}
        {deliverableCount}
        {now}
      />
      <WorkBlock {job} {overview} {tasksPlanned} />
      <MaterialsBlock pos={poList} {coverage} {now} />
      <SpendBlock {job} {overview} {scopeTotal} />
      <InvoicingBlock invoices={invoiceList} {scopeTotal} {invoicedTotal} {now} />
      <DeliveryBlock shipments={shipmentList} {deliverableCount} {job} {now} />
    </div>
  </div>
</JobShell>

<style>
  /* 10px here + .page-body's 10px = 20px — the blocks' left/right edges line
     up with the context band's panels above (.context-band-grid's 20px). */
  .summary-blocks { padding: 18px 10px 40px; }

  .change-request-banner {
    background: #ffedd5;
    border: 1px solid #fdba74;
    color: #9a3412;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    margin: 14px 0 4px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: baseline;
  }
  .change-request-banner .cr-text { font-style: italic; }
  .change-request-banner .cr-hint { color: #c2410c; margin-left: auto; font-size: 12px; }
</style>
