<script>
  import { emailApi } from '../../lib/email.js';
  import EmailContent from '../../components/email/EmailContent.svelte';

  const { params = {} } = $props();

  let email = $state(null);
  let loading = $state(true);
  let loadError = $state(null);
  let actionError = $state(null);

  async function load() {
    loading = true;
    loadError = null;
    try {
      email = await emailApi.get(params.id);
    } catch (e) {
      loadError = e.message;
    } finally {
      loading = false;
    }
  }

  async function handleDisassociate() {
    if (!confirm('Are you sure you want to disassociate this email from the job?')) return;
    actionError = null;
    try {
      email = await emailApi.unlinkFromJob(params.id);
      // unlink returns the updated EmailRecord but without `content`; refetch to keep the body.
      await load();
    } catch (e) {
      actionError = e.message;
    }
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

<h2>Email Details</h2>

<p>
  <a href="#/email">&larr; Back to Inbox</a>
  {#if email && !email.job}
    | <strong><a href="#/email/{params.id}/create-job">Create Job from this Email</a></strong>
    | <a href="#/email/{params.id}/associate">Associate with Existing Job</a>
  {/if}
</p>

{#if actionError}
  <p><strong>Error:</strong> {actionError}</p>
{/if}

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else if email}
  {#if email.job}
    <p>
      <strong>Linked to job:</strong>
      <a href="#/jobs/{email.job}">{email.job_number || `Job #${email.job}`}</a>
      <button onclick={handleDisassociate}>Disassociate</button>
    </p>
  {/if}

  <EmailContent
    content={email.content}
    tempEmail={email.temp_email}
    emailRecord={email}
    contactLinks={email.contact_links}
  />
{/if}
