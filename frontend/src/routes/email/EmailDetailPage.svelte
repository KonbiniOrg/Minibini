<script>
  import { emailApi } from '../../lib/email.js';
  import EmailContent from '../../components/email/EmailContent.svelte';
  import EmailActionPanel from '../../components/email/EmailActionPanel.svelte';
  import EmailReplyComposer from '../../components/email/EmailReplyComposer.svelte';

  const { params = {} } = $props();

  let email = $state(null);
  let loading = $state(true);
  let loadError = $state(null);

  // null | 'reply' | 'reply-all' — set by the action panel's Reply / Reply All
  // buttons. The composer renders inline above the original email while
  // this is non-null; the right rail stays sticky so the panel and the
  // Job/PO/Bill associations remain visible while composing.
  let replyMode = $state(null);

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

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else if email}
  <div class="layout">
    <div class="content">
      {#if replyMode}
        <EmailReplyComposer
          emailRecordId={email.email_record_id}
          mode={replyMode}
          onClose={() => (replyMode = null)}
          onSent={handleSent}
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
      />
    </div>
  </div>
{/if}
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
