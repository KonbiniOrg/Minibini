<script>
  import { api } from '../../lib/api.js';
  import DeliverablesEditModal from './DeliverablesEditModal.svelte';

  let { jobId } = $props();

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

  function reasonLabel(r) {
    if (r === 'estimate_sent') return 'estimate sent';
    if (r === 'estimate_accepted') return 'estimate accepted';
    return '';
  }
</script>

<div class="panel deliverables-panel">
  <div class="panel-head">
    Deliverables
    {#if !editability.editable && editability.reason}
      <span class="state">({reasonLabel(editability.reason)})</span>
    {/if}
    {#if editability.editable}
      <button type="button" class="edit-link" onclick={openEdit}>Edit</button>
    {/if}
  </div>
  <div class="panel-scroll">
    {#if loading}
      <p class="empty">Loading...</p>
    {:else if deliverables.length === 0}
      <p class="empty">
        No deliverables yet.
        {#if editability.editable}
          <button type="button" class="edit-link" onclick={openEdit}>Add deliverables</button>
        {/if}
      </p>
    {:else}
      <table border="1">
        <thead>
          <tr><th>#</th><th>Description</th><th>Qty</th><th>Units</th><th>Picked up</th><th>Remaining</th></tr>
        </thead>
        <tbody>
          {#each deliverables as d, i}
            <tr>
              <td>{i + 1}</td>
              <td>{d.description}</td>
              <td class="num">{d.qty_ordered}</td>
              <td>{d.units}</td>
              <td class="num">{d.qty_picked_up}</td>
              <td class="num">{d.qty_remaining}</td>
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
  .deliverables-panel .panel-head {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }
  .state {
    font-style: italic;
    text-transform: none;
    color: #555;
    letter-spacing: 0;
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
  .empty {
    color: #777;
    font-size: 13px;
    margin: 0;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
  }
  th, td {
    padding: 4px 6px;
    text-align: left;
  }
  td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
</style>
