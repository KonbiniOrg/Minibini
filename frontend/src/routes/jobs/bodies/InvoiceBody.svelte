<script>
  // Invoice section body. Job owned by JobWorkspace. Ported from
  // JobInvoicePage: owns the invoices list + docId precedence (URL param →
  // remembered → latest invoice) and URL normalization. (Was JobInvoicePage.)
  import { api } from '../../../lib/api.js';
  import InvoicePanel from '../../../components/invoices/InvoicePanel.svelte';
  import { getJobWs, rememberSection } from '../../../stores/jobWorkspace.js';

  let { job, params = {}, onJobChange = () => {} } = $props();

  const jobId = $derived(String(params.jobId ?? job?.job_id));
  let invoices = $state([]);

  async function loadInvoices() {
    try {
      const resp = await api.get(`/api/invoices/?job=${jobId}`);
      invoices = (resp?.results || resp || []).slice().sort((a, b) => new Date(a.created_date) - new Date(b.created_date));
    } catch (_) {
      invoices = [];
    }
  }

  // Follows the viewed document too (Start Invoice creates-then-navigates).
  $effect(() => { void params.docId; if (jobId) loadInvoices(); });

  // docId precedence: URL param → remembered → latest invoice.
  const docId = $derived.by(() => {
    if (params.docId) return String(params.docId);
    const remembered = getJobWs(jobId).sections.invoice;
    if (remembered && invoices.some((i) => String(i.invoice_id) === remembered)) return remembered;
    return invoices.length ? String(invoices[invoices.length - 1].invoice_id) : null;
  });

  // Whenever a document renders, remember it AND normalize the URL (replace, no reload):
  $effect(() => {
    if (docId && jobId) {
      rememberSection(jobId, 'invoice', docId);
      const want = `#/jobs/${jobId}/invoice/${docId}`;
      if (window.location.hash !== want) window.history.replaceState(null, '', want);
    }
  });
</script>

<InvoicePanel {job} invoiceId={docId} {onJobChange} />
