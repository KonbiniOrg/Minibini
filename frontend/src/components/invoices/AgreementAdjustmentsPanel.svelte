<script>
  import { api } from '../../lib/api.js';

  // `refreshKey`: an optional caller-supplied value (e.g. a join of the
  // parent's current line_item_ids) that this panel re-loads on whenever
  // it changes — not just on mount. Under the silent-refresh no-remount
  // idiom (InvoicePanel.loadInvoice({silent:true}) never tears this
  // component down), an onMount-only load would go stale the moment an
  // adjustment line is removed elsewhere: `already_added` would keep
  // reporting the removed adjustment as added, hiding its own Add button
  // forever. Reacting to `invoiceId` too covers a caller that swaps
  // documents without unmounting.
  let { invoiceId, refreshKey = null, onLineItemAdded = () => {} } = $props();

  let adjustments = $state([]);
  let loaded = $state(false);

  async function load() {
    try {
      const data = await api.get(`/api/invoices/${invoiceId}/agreement-adjustments/`);
      adjustments = data.adjustments ?? [];
    } catch (_) {
      adjustments = [];
    } finally {
      loaded = true;
    }
  }

  async function addAdjustment(entry) {
    await api.post(`/api/invoices/${invoiceId}/adjustment-lines/`, {
      adjustment_service: entry.adjustment_service_id,
      target_category_ids: entry.target_category_ids,
    });
    await load();
    // The new adjustment line lives in the wizard's line-item column —
    // tell the parent so it appears without a manual reload.
    onLineItemAdded();
  }

  $effect(() => {
    void invoiceId;
    void refreshKey;
    load();
  });
</script>

{#if loaded && adjustments.length > 0}
  <section class="agreement-adjustments">
    <h4>Agreement Adjustments</h4>
    <ul>
      {#each adjustments as entry (entry.adjustment_service_id)}
        <li class="adj-entry" class:added={entry.already_added}>
          <span class="desc">{entry.description}</span>
          <span class="pct">{entry.percent}%</span>
          <button
            type="button"
            disabled={entry.already_added}
            onclick={() => addAdjustment(entry)}
          >{entry.already_added ? 'Added' : 'Add'}</button>
        </li>
      {/each}
    </ul>
  </section>
{/if}

<style>
  .agreement-adjustments {
    margin-top: 16px;
    padding: 10px 12px;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    background: #fafafa;
  }
  h4 {
    margin: 0 0 8px;
    font-size: 14px;
    font-weight: 600;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .adj-entry {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0;
    border-bottom: 1px solid #eee;
  }
  .adj-entry:last-child {
    border-bottom: none;
  }
  .desc {
    flex: 1;
    font-size: 13px;
  }
  .pct {
    font-size: 13px;
    color: #555;
    min-width: 52px;
    text-align: right;
  }
  .added .desc,
  .added .pct {
    color: #999;
  }
</style>
