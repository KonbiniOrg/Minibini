<script>
  import { link } from 'svelte-spa-router';
  import { api, errorMessage } from '../../lib/api.js';
  import { showError } from '../../stores/messages.js';
  import { canManageFinancials } from '../../stores/permissions.js';
  import DeliverablesEditModal from './DeliverablesEditModal.svelte';

  // jobOnHold mirrors the "Create work structure" endpoint's own
  // _assert_job_not_on_hold gate — avoids a guaranteed 400 round trip.
  let { jobId, canManage = false, jobOnHold = false } = $props();

  let deliverables = $state([]);
  let editability = $state({ editable: false, reason: null });
  let loading = $state(true);
  let modalOpen = $state(false);
  // Busy-per-row: keyed by deliverable id, guards the create-work-structure
  // action button against a double-click double-post.
  let structureBusy = $state({});

  // Deliverables bridge (spec §9 rule 7, task-owned-money Phase 4 Task 5):
  // "Create work structure" mints a money-LESS Task (rate/AC both null), so
  // the API gates it on (CanManageJobOrPM | CanManageFinancials) — broader
  // than plain `canManage` (the job-scoped CanManageJobOrPM equivalent this
  // panel's Edit link already uses), matching apps/api/deliverables/views.py.
  const canCreateStructure = $derived(canManage || $canManageFinancials);

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

  // Passive mismatch badge (spec §9 rule 7): task est_qty vs THIS
  // deliverable's qty_ordered — deliberately est vs ordered, NOT actuals.
  // Silent (no badge) when unlinked or when the linked task carries no
  // est_qty of its own (nothing to compare).
  function mismatched(d) {
    if (d.source_task_est_qty == null) return false;
    return Number(d.source_task_est_qty) !== Number(d.qty_ordered);
  }

  async function createWorkStructure(d) {
    structureBusy = { ...structureBusy, [d.id]: true };
    try {
      await api.post(`/api/jobs/${jobId}/deliverables/${d.id}/create-work-structure/`, {});
      await load();
    } catch (e) {
      // Plain action button, no form of its own: the global overlay is the venue.
      showError(errorMessage(e, 'Could not create a work structure.'));
    } finally {
      structureBusy = { ...structureBusy, [d.id]: false };
    }
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
    {#if loading}
      <p class="empty">Loading...</p>
    {:else if deliverables.length === 0}
      <p class="empty">
        No deliverables yet.
        {#if canManage && editability.editable}
          <button type="button" class="panel-link" onclick={openEdit}>Add deliverables</button>
        {/if}
      </p>
    {:else}
      <table class="simple-list">
        <tbody>
          {#each deliverables as d}
            <tr>
              <td class="num">{fmtQty(d.qty_ordered)}</td>
              <td class="units">{d.units}</td>
              <td class="preserve-breaks">
                {d.description}
                {#if d.source_task}
                  <span class="provenance">
                    from <a href={`/jobs/${jobId}/tasks/${d.source_task}`} use:link>{d.source_task_name}</a>
                    {#if mismatched(d)}
                      <span class="mismatch-badge"
                        title={`Task estimates ${fmtQty(d.source_task_est_qty)}; this deliverable orders ${fmtQty(d.qty_ordered)}.`}
                      >mismatch</span>
                    {/if}
                  </span>
                {:else if canCreateStructure && !jobOnHold}
                  <button type="button" class="panel-link structure-btn"
                    onclick={() => createWorkStructure(d)} disabled={!!structureBusy[d.id]}>
                    {structureBusy[d.id] ? 'Creating…' : 'Create work structure'}
                  </button>
                {/if}
              </td>
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
  .provenance {
    display: block;
    font-size: 12px;
    color: #666;
  }
  .structure-btn {
    margin-left: 0;
  }
  .mismatch-badge {
    display: inline-block;
    margin-left: 6px;
    padding: 0 6px;
    border-radius: 3px;
    background: #fff1f0;
    color: #a8071a;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.02em;
    cursor: help;
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
