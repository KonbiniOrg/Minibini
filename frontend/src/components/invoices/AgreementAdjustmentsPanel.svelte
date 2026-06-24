<script>
  import { onMount } from 'svelte';
  import { api } from '../../lib/api.js';

  let { invoiceId } = $props();

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
  }

  onMount(load);
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
