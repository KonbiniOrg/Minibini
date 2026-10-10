<script>
  import { untrack } from 'svelte';
  import { api, errorMessage } from '../../lib/api.js';
  import { deliverablesVersion } from '../../stores/deliverables.js';
  import DeliverablesEditModal from './DeliverablesEditModal.svelte';
  import LoadState from '../LoadState.svelte';
  import DataTable from '../DataTable.svelte';

  // `job`: the host page's job object. Purely a refresh signal — every
  // onJobChange up the chain re-fetches the job, and the new object identity
  // re-runs our load effect (the standard props-down/callback-up partial
  // refresh; e.g. Make Deliverable on the estimate below this band).
  let { jobId, canManage = false, job = null } = $props();

  let deliverables = $state([]);
  let editability = $state({ editable: false, reason: null });
  let loading = $state(true);
  let error = $state(null);
  let modalOpen = $state(false);

  async function load() {
    loading = true;
    error = null;
    try {
      const [items, ed] = await Promise.all([
        api.get(`/api/jobs/${jobId}/deliverables/`),
        api.get(`/api/jobs/${jobId}/deliverables/editability/`),
      ]);
      deliverables = items;
      editability = ed;
    } catch (e) {
      error = errorMessage(e, 'Could not load deliverables.');
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    job; // dependency: reload when the host refreshes the job
    if (jobId) load();
  });

  // Sibling components (the CO deliverables section, Make Deliverable on an
  // estimate line, the send gates' modal) mutate the same list without
  // going through the host's job refresh — refetch when the store bumps.
  let lastDeliverablesVersion = $state(0);
  $effect(() => {
    const v = $deliverablesVersion;
    if (v !== lastDeliverablesVersion) {
      lastDeliverablesVersion = v;
      if (jobId) untrack(() => load());
    }
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
      <button type="button" class="panel-link" onclick={openEdit}>Edit</button>
    {/if}
  </div>
  <div class="panel-scroll">
    <LoadState {loading} {error}>
    {#if deliverables.length === 0}
      <p class="empty">
        No deliverables yet.
        {#if canManage && editability.editable}
          <button type="button" class="panel-link" onclick={openEdit}>Add deliverables</button>
        {/if}
      </p>
    {:else}
      <DataTable
        rows={deliverables}
        key={(d) => d.id}
        columns={[
          { id: 'qty',         label: 'Qty',         cell: qtyCell, align: 'right' },
          { id: 'units',       label: 'Units',       field: 'units' },
          { id: 'description', label: 'Description', cell: descriptionCell },
        ]}
      />
    {/if}
    </LoadState>
  </div>
</div>

{#if modalOpen}
  <DeliverablesEditModal {jobId} onClose={onModalClose} />
{/if}

{#snippet qtyCell(d)}<span class="qty">{fmtQty(d.qty_ordered)}</span>{/snippet}
{#snippet descriptionCell(d)}<span class="preserve-breaks">{d.description}</span>{/snippet}

<style>
  /* .panel chrome comes from app.css; locally the head becomes a flex row
     so the Edit affordance can sit at its right edge. */
  .panel-head {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }
  .panel-link {
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
  .qty { font-variant-numeric: tabular-nums; white-space: nowrap; }
</style>
