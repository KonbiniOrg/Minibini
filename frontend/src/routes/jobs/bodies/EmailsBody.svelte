<script>
  // Emails section body. Job owned by JobWorkspace; this body owns the
  // /api/emails/?job= fetch and hands { results } to the dumb EmailPanel.
  // (Was JobEmailsPage.)
  import { api } from '../../../lib/api.js';
  import EmailPanel from '../../../components/EmailPanel.svelte';
  let { job } = $props();
  const jobId = $derived(job?.job_id);
  let emails = $state(null);

  async function loadEmails() {
    try {
      emails = await api.get(`/api/emails/?job=${jobId}`);
    } catch (_) {
      emails = { results: [] };
    }
  }

  $effect(() => { if (jobId) loadEmails(); });
</script>

<div class="page-body">
  <EmailPanel {emails} />
</div>
