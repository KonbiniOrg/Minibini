<script>
  import { api } from '../../lib/api.js';
  import DeliverablesEditModal from './DeliverablesEditModal.svelte';

  let { jobId, canManage = false } = $props();

  let deliverables = $state([]);
  let editability = $state({ editable: false, reason: null });
  let loading = $state(true);
  let modalOpen = $state(false);

  async function load() {
    loading = true;
    try {
      const [items, ed] = await Promise.all([
        api.get(`/api/jobs/${jobId}/deliverables/`),
        api.get(`/api/jobs/${jobId}/deliverables/editability/`),
      ]);
      deliverables = items;
      editability = ed;
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (jobId) load();
  });

  function openEdit() {
    modalOpen = true;
  }

  function onModalClose(changed) {
    modalOpen = false;
    if (changed) load();
  }

  // API returns DecimalFields as fixed-precision strings ("10.00"). Trim trailing
  // zeros for display so whole quantities show as "10" not "10.00", and "2.50"
  // shows as "2.5". Keeps non-numeric values as-is just in case.
  function fmtQty(value) {
    if (value === null || value === undefined || value === '') return '';
    const n = Number(value);
    return Number.isFinite(n) ? n.toString() : String(value);
  }
</script>

<div class="panel deliverables-panel">
  <div class="panel-head">
    Deliverables
    {#if canManage && editability.editable}
      <button type="button" class="edit-link" onclick={openEdit}>Edit</button>
    {/if}
  </div>
  <div class="panel-scroll">
    {#if loading}
      <p class="empty">Loading...</p>
    {:else if deliverables.length === 0}
      <p class="empty">
        No deliverables yet.
        {#if canManage && editability.editable}
          <button type="button" class="edit-link" onclick={openEdit}>Add deliverables</button>
        {/if}
      </p>
    {:else}
      <table class="simple-list">
        <tbody>
          {#each deliverables as d}
            <tr>
              <td class="num">{fmtQty(d.qty_ordered)}</td>
              <td class="units">{d.units}</td>
              <td class="preserve-breaks">{d.description}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>
</div>

{#if modalOpen}
  <DeliverablesEditModal {jobId} onClose={onModalClose} />
{/if}

<style>
  /* These mirror the .panel / .panel-head / .panel-scroll rules in
     JobDetail.svelte. Svelte scopes component styles, so we can't rely on the
     parent's definitions reaching this component's DOM. */
  .panel {
    background: #fff;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 12px;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .panel-head {
    font-size: 10px;
    text-transform: uppercase;
    color: #888;
    letter-spacing: 0.5px;
    margin-bottom: 6px;
    flex: 0 0 auto;
    display: flex;
    align-items: baseline;
    gap: 8px;
  }
  .panel-scroll {
    overflow-y: auto;
    flex: 1 1 auto;
    min-height: 0;
  }
  .edit-link {
    background: none;
    border: none;
    color: #1a73e8;
    text-decoration: underline;
    cursor: pointer;
    padding: 0;
    font: inherit;
    text-transform: none;
    letter-spacing: 0;
    margin-left: auto;
  }
  /* Match the Description panel typography (line-height 1.6, color #333). */
  .empty {
    margin: 0;
    color: #333;
    font-size: 14px;
    line-height: 1.6;
  }
  table.simple-list {
    width: 100%;
    border: none;
    border-collapse: collapse;
    color: #333;
    font-size: 14px;
    line-height: 1.6;
  }
  table.simple-list td {
    border: none;
    padding: 6px 16px 6px 0;
    vertical-align: baseline;
  }
  table.simple-list td:last-child {
    padding-right: 0;
    width: 100%;
  }
  table.simple-list td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    width: 1%;
  }
  table.simple-list td.units {
    color: #666;
    white-space: nowrap;
    width: 1%;
  }
</style>
