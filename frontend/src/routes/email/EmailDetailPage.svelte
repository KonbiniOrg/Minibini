<script>
  import { emailApi } from '../../lib/email.js';
  import EmailContent from '../../components/email/EmailContent.svelte';
  import EmailActionPanel from '../../components/email/EmailActionPanel.svelte';

  const { params = {} } = $props();

  let email = $state(null);
  let loading = $state(true);
  let loadError = $state(null);

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

  $effect(() => {
    void params.id;
    load();
  });
</script>

<h2>Email Details</h2>

<p><a href="#/email">&larr; Back to Inbox</a></p>

{#if loading}
  <p>Loading…</p>
{:else if loadError}
  <p>Error: {loadError}</p>
{:else if email}
  <div class="layout">
    <div class="content">
      <EmailContent
        content={email.content}
        tempEmail={email.temp_email}
        emailRecord={email}
        contactLinks={email.contact_links}
      />
    </div>
    <div class="rail">
      <EmailActionPanel emailRecord={email} onChange={load} />
    </div>
  </div>
{/if}

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
  }
</style>
