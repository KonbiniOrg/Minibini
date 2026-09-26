<script>
  import { api } from '../../lib/api.js';
  import JobShell from '../../components/jobs/JobShell.svelte';
  import InvoicePanel from '../../components/invoices/InvoicePanel.svelte';
  import { getJobWs, rememberSection } from '../../stores/jobWorkspace.js';

  let { params = {} } = $props();
  let job = $state(null);
  let contact = $state(null);
  let invoices = $state([]);
  let error = $state('');

  // Value-keyed: svelte-spa-router hands this still-mounted component a new
  // `params` object on every doc-subnav navigation, even when only :docId
  // changed. Deriving jobId memoizes on the value, so the effect below only
  // reruns when the job actually changes, not on every doc switch. The load
  // functions read this derived (not params.jobId directly) so they don't
  // reintroduce a dependency on the raw params object.
  const jobId = $derived(params.jobId);

  async function loadJob() {
    try {
      job = await api.get(`/api/jobs/${jobId}/`);
      contact = job?.contact ? await api.get(`/api/contacts/${job.contact}/`).catch(() => null) : null;
    } catch (e) { error = e.message || 'Could not load job.'; }
  }

  async function loadInvoices() {
    try {
      const resp = await api.get(`/api/invoices/?job=${jobId}`);
      invoices = (resp?.results || resp || []).slice().sort((a, b) => new Date(a.created_date) - new Date(b.created_date));
    } catch (_) {
      invoices = [];
    }
  }

  $effect(() => {
    if (jobId) {
      loadJob();
      loadInvoices();
    }
  });

  // docId precedence: URL param → remembered → latest invoice.
  const docId = $derived.by(() => {
    if (params.docId) return String(params.docId);
    const remembered = getJobWs(params.jobId).sections.invoice;
    if (remembered && invoices.some((i) => String(i.invoice_id) === remembered)) return remembered;
    return invoices.length ? String(invoices[invoices.length - 1].invoice_id) : null;
  });

  // Whenever a document renders, remember it AND normalize the URL (replace, no reload):
  $effect(() => {
    if (docId && params.jobId) {
      rememberSection(params.jobId, 'invoice', docId);
      const want = `#/jobs/${params.jobId}/invoice/${docId}`;
      if (window.location.hash !== want) window.history.replaceState(null, '', want);
    }
  });
</script>

{#if error}<p class="error">{error}</p>
{:else if job}
  <JobShell {job} {contact} current="invoice" colorway="cw-invoice" onJobChange={loadJob}>
    <InvoicePanel {job} invoiceId={docId} onJobChange={loadJob} />
  </JobShell>
{:else}<p>Loading…</p>{/if}
