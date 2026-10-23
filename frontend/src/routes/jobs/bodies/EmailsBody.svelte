<script>
  // Emails section body. Job owned by JobWorkspace; this body owns the
  // /api/emails/?job= fetch and hands { results } to the dumb EmailPanel
  // (the tab's h2 replaces the panel's own <h3>Email</h3>).
  // (Was JobEmailsPage.)
  import { api } from '../../../lib/api.js';
  import EmailPanel from '../../../components/EmailPanel.svelte';
  import TabHeader from '../../../components/TabHeader.svelte';
  import EmptyState from '../../../components/EmptyState.svelte';
  import LoadState from '../../../components/LoadState.svelte';
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

<section class="page-body" aria-labelledby="tab-emails">
  <TabHeader id="tab-emails" title="Emails" titleHidden />
  <LoadState loading={emails === null}>
    {#if emails.results?.length}
      <EmailPanel {emails} showHeading={false} />
    {:else}
      <EmptyState text="No email linked to this job yet. Link one from its message in Email." />
    {/if}
  </LoadState>
</section>
