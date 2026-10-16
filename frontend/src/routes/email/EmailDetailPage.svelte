<script>
  import { emailApi } from '../../lib/email.js';
  import EmailContent from '../../components/email/EmailContent.svelte';
  import EmailActionPanel from '../../components/email/EmailActionPanel.svelte';
  import EmailReplyComposer from '../../components/email/EmailReplyComposer.svelte';
  import EmailCreateJobModal from '../../components/email/EmailCreateJobModal.svelte';
  import EmailLinkModal from '../../components/email/EmailLinkModal.svelte';
  import OrderModal from '../../components/purchaseorders/OrderModal.svelte';
  import LoadState from '../../components/LoadState.svelte';
  import { errorMessage } from '../../lib/api.js';

  const { params = {} } = $props();

  let email = $state(null);
  let loading = $state(true);
  let loadError = $state(null);

  // null | 'reply' | 'reply-all' — set by the action panel's Reply / Reply All
  // buttons. The composer opens as a modal over the email while this is
  // non-null (2026-10-10; it used to render inline above the message).
  let replyMode = $state(null);

  // null | 'create-job' | 'link-job' | 'link-po' — which action-panel modal
  // is open (the old per-action pages, 2026-10-10).
  let actionModal = $state(null);

  async function load() {
    loading = true;
    loadError = null;
    try {
      email = await emailApi.get(params.id);
    } catch (e) {
      loadError = errorMessage(e, 'Could not load email.');
    } finally {
      loading = false;
    }
  }

  function handleSent() {
    replyMode = null;
    // Refresh so the new outbound shows in any linked panels and the
    // action panel reflects whatever associations the reply inherited.
    load();
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

<div class="page-body">
<h2>Email Details</h2>

<p><a href="#/email">&larr; Back to Inbox</a></p>

<LoadState {loading} error={loadError}>
{#if email}
  <div class="layout">
    <div class="content">
      {#if replyMode}
        <EmailReplyComposer
          emailRecordId={email.email_record_id}
          mode={replyMode}
          onClose={() => (replyMode = null)}
          onSent={handleSent}
          onModeChange={(mode) => (replyMode = mode)}
        />
      {/if}
      <EmailContent
        content={email.content}
        tempEmail={email.temp_email}
        emailRecord={email}
        contactLinks={email.contact_links}
      />
    </div>
    <div class="rail">
      <EmailActionPanel
        emailRecord={email}
        onChange={load}
        onReply={(mode) => (replyMode = mode)}
        onAction={(name) => (actionModal = name)}
      />
    </div>
  </div>
  <EmailCreateJobModal emailRecordId={email.email_record_id} open={actionModal === 'create-job'}
    onClose={() => (actionModal = null)} />
  <EmailLinkModal emailRecordId={email.email_record_id} kind="job" open={actionModal === 'link-job'}
    onLinked={() => { actionModal = null; load(); }} onClose={() => (actionModal = null)} />
  <EmailLinkModal emailRecordId={email.email_record_id} kind="po" open={actionModal === 'link-po'}
    onLinked={() => { actionModal = null; load(); }} onClose={() => (actionModal = null)} />
  {#if actionModal === 'create-po'}
    <OrderModal source="email" emailRecordId={email.email_record_id}
      onDone={() => { actionModal = null; }} onCancel={() => (actionModal = null)} />
  {/if}
{/if}
</LoadState>
</div>

<style>
  .layout {
    display: flex;
    gap: 16px;
    align-items: flex-start;
  }
  .content {
    flex: 1 1 auto;
    min-width: 0;
  }
  .rail {
    flex: 0 0 220px;
    position: sticky;
    top: 16px;
    align-self: flex-start;
  }
</style>
