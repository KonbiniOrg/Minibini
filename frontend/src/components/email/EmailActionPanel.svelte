<script>
  import { canManageJobs as canManageJobsStore, canManageFinancials as canManageFinancialsStore } from '../../stores/permissions.js';
  import { emailApi } from '../../lib/email.js';

  let { emailRecord, onChange = null, onReply = null } = $props();

  let canManageJobs = $derived($canManageJobsStore);
  let canManageFinancials = $derived($canManageFinancialsStore);

  let actionError = $state(null);

  async function disassociate(target) {
    // No confirm: re-linking is one action away in the same panel.
    actionError = null;
    try {
      const id = emailRecord.email_record_id;
      if (target === 'job') await emailApi.unlinkFromJob(id);
      else if (target === 'purchase_order') await emailApi.unlinkFromPo(id);
      if (onChange) await onChange();
    } catch (e) {
      actionError = e.message;
    }
  }
</script>

<aside class="action-panel">
  <h3>Actions</h3>

  {#if actionError}
    <p class="error"><strong>Error:</strong> {actionError}</p>
  {/if}

  <section>
    <h4>Reply</h4>
    <p>
      <button type="button" class="action-button" onclick={() => onReply && onReply('reply')}>Reply</button>
    </p>
    <p>
      <button type="button" class="action-button" onclick={() => onReply && onReply('reply-all')}>Reply All</button>
    </p>
  </section>

  {#if canManageJobs}
    <section>
      <h4>Job</h4>
      {#if emailRecord.job}
        <p>
          Linked: <a href="#/jobs/{emailRecord.job}">{emailRecord.job_number || `Job #${emailRecord.job}`}</a>
        </p>
        <p>
          <button type="button" class="action-button" onclick={() => disassociate('job')}>Disassociate</button>
        </p>
      {:else}
        <p>
          <a class="action-button" href="#/email/{emailRecord.email_record_id}/create-job">Create new</a>
        </p>
        <p>
          <a class="action-button" href="#/email/{emailRecord.email_record_id}/associate">Link existing</a>
        </p>
      {/if}
    </section>
  {/if}

  {#if canManageFinancials}
    <section>
      <h4>Purchase Order</h4>
      {#if emailRecord.purchase_order}
        <p>
          Linked: <a href="#/purchase-orders/{emailRecord.purchase_order}">{emailRecord.po_number || `PO #${emailRecord.purchase_order}`}</a>
        </p>
        <p>
          <button type="button" class="action-button" onclick={() => disassociate('purchase_order')}>Disassociate</button>
        </p>
      {:else}
        <p>
          <a class="action-button" href="#/email/{emailRecord.email_record_id}/create-po">Create new</a>
        </p>
        <p>
          <a class="action-button" href="#/email/{emailRecord.email_record_id}/associate-po">Link existing</a>
        </p>
      {/if}
    </section>

  {/if}
</aside>

<style>
  .action-panel {
    border: 1px solid #e5e7eb;
    padding: 12px;
    border-radius: 4px;
    background: #fafafa;
    min-width: 200px;
  }
  .action-panel h3 {
    margin: 0 0 8px;
    font-size: 14px;
  }
  .action-panel h4 {
    margin: 12px 0 4px;
    font-size: 13px;
    color: #555;
  }
  .action-panel section:first-of-type h4 {
    margin-top: 0;
  }
  .action-panel p {
    margin: 4px 0;
    font-size: 13px;
  }
  .action-button {
    display: inline-block;
    padding: 4px 10px;
    border: 1px solid #d1d5db;
    border-radius: 3px;
    background: #fff;
    color: #2563eb;
    text-decoration: none;
    font-size: 13px;
    cursor: pointer;
    font-family: inherit;
  }
  .action-button:hover {
    background: #f3f4f6;
  }
  .error {
    color: #b91c1c;
  }
</style>
