<script>
  import { api } from '../../lib/api.js';
  import { link } from 'svelte-spa-router';

  let { params } = $props();
  const jobId = $derived(parseInt(params.jobId, 10));

  let deliverables = $state([]);
  let shipments = $state([]);
  let job = $state(null);
  let loading = $state(true);
  let saving = $state(false);
  let errorMsg = $state('');

  // Pending edits keyed by `${shipmentId}:${deliverableId}` => string qty (or '' to remove).
  let pending = $state({});

  async function load() {
    loading = true;
    errorMsg = '';
    try {
      const [j, d, s] = await Promise.all([
        api.get(`/api/jobs/${jobId}/`),
        api.get(`/api/jobs/${jobId}/deliverables/`),
        api.get(`/api/shipments/?job=${jobId}`),
      ]);
      job = j;
      deliverables = d;
      const list = s.results || s;
      shipments = list.slice().sort((a, b) => a.sequence - b.sequence);
    } catch (e) {
      errorMsg = e.message || 'Load failed.';
    } finally {
      loading = false;
    }
  }

  $effect(() => { if (jobId) load(); });

  function getItem(sh, deliverableId) {
    return (sh.items || []).find(it => it.deliverable === deliverableId);
  }

  function pendingKey(shipmentId, deliverableId) {
    return `${shipmentId}:${deliverableId}`;
  }

  function cellValue(sh, deliverableId) {
    const key = pendingKey(sh.id, deliverableId);
    if (key in pending) return pending[key];
    return getItem(sh, deliverableId)?.qty ?? '';
  }

  function cellIsPending(sh, deliverableId) {
    return pendingKey(sh.id, deliverableId) in pending;
  }

  function onCellInput(sh, deliverableId, value) {
    if (sh.status !== 'prepared') return;
    const key = pendingKey(sh.id, deliverableId);
    pending = { ...pending, [key]: value };
  }

  let hasChanges = $derived(Object.keys(pending).length > 0);

  async function addShipment() {
    try {
      await api.post(`/api/jobs/${jobId}/shipments/`, {});
      await load();
    } catch (e) { errorMsg = e.message || 'Add shipment failed.'; }
  }

  async function pickUp(sh) {
    if (hasChanges) {
      if (!confirm('You have unsaved cell changes. Mark picked up anyway? Unsaved changes will be lost.')) return;
    } else if (!confirm(`Mark Shipment #${sh.sequence} as picked up? This locks the shipment.`)) {
      return;
    }
    try {
      await api.post(`/api/shipments/${sh.id}/pick-up/`, {});
      pending = {};
      await load();
    } catch (e) { errorMsg = e.message || 'Pick-up failed.'; }
  }

  async function discardShipment(sh) {
    if (sh.status !== 'prepared') return;
    const itemCount = (sh.items || []).length;
    const msg = itemCount > 0
      ? `Discard Shipment #${sh.sequence}? This removes ${itemCount} item${itemCount === 1 ? '' : 's'} from the shipment and deletes the shipment itself. The Deliverables list is unchanged.`
      : `Discard Shipment #${sh.sequence}?`;
    if (!confirm(msg)) return;
    try {
      // Backend rejects shipment delete while items exist; remove them first.
      for (const item of (sh.items || [])) {
        await api.delete(`/api/shipments/${sh.id}/items/${item.id}/`);
      }
      await api.delete(`/api/shipments/${sh.id}/`);
      // Drop any pending entries that referenced this shipment.
      const next = {};
      for (const [k, v] of Object.entries(pending)) {
        if (!k.startsWith(`${sh.id}:`)) next[k] = v;
      }
      pending = next;
      await load();
    } catch (e) { errorMsg = e.message || 'Discard failed.'; }
  }

  async function saveChanges() {
    if (!hasChanges || saving) return;
    saving = true;
    errorMsg = '';
    try {
      for (const [key, rawValue] of Object.entries(pending)) {
        const [shipmentIdStr, deliverableIdStr] = key.split(':');
        const shipmentId = Number(shipmentIdStr);
        const deliverableId = Number(deliverableIdStr);
        const sh = shipments.find(s => s.id === shipmentId);
        if (!sh || sh.status !== 'prepared') continue;
        const existing = getItem(sh, deliverableId);
        const trimmed = String(rawValue ?? '').trim();
        if (trimmed === '' || Number(trimmed) === 0) {
          if (existing) await api.delete(`/api/shipments/${shipmentId}/items/${existing.id}/`);
        } else if (existing) {
          await api.patch(`/api/shipments/${shipmentId}/items/${existing.id}/`, { qty: trimmed });
        } else {
          await api.post(`/api/shipments/${shipmentId}/items/`, {
            deliverable: deliverableId,
            qty: trimmed,
          });
        }
      }
      pending = {};
      await load();
    } catch (e) {
      errorMsg = e.message || 'Save failed. Earlier rows may have been saved; later rows were not.';
    } finally {
      saving = false;
    }
  }

  function discardChanges() {
    pending = {};
  }

  function printPackingList(sh) {
    window.open(`#/shipments/${sh.id}/print`, '_blank');
  }

  function shipmentDate(sh) {
    const iso = sh.status === 'picked_up' ? sh.picked_up_date : sh.prepared_date;
    if (!iso) return '';
    return new Date(iso).toLocaleDateString();
  }

  // Column total reflects pending edits, not just saved state.
  function columnTotal(sh) {
    let total = 0;
    for (const d of deliverables) {
      const v = cellValue(sh, d.id);
      const n = Number(v);
      if (!isNaN(n)) total += n;
    }
    return total;
  }
</script>

<div class="page">
  {#if loading}
    <p>Loading...</p>
  {:else if job}
    <header>
      <h2>Shipments for {job.job_number}: {job.name}</h2>
      <p><a use:link href={`/jobs/${jobId}`}>← Back to job</a></p>
      <div class="action-row">
        <button type="button" onclick={addShipment}>+ Add shipment</button>
        <button type="button" onclick={saveChanges} disabled={!hasChanges || saving}>
          {saving ? 'Saving...' : 'Save changes'}
        </button>
        <button type="button" onclick={discardChanges} disabled={!hasChanges || saving}>Discard changes</button>
        {#if hasChanges}
          <span class="pending-note">{Object.keys(pending).length} unsaved {Object.keys(pending).length === 1 ? 'change' : 'changes'}</span>
        {/if}
      </div>
      {#if errorMsg}<p class="err">{errorMsg}</p>{/if}
    </header>

    {#if deliverables.length === 0}
      <p>This job has no deliverables yet.</p>
    {:else if shipments.length === 0}
      <p>No shipments yet. Click "+ Add shipment" to create one.</p>
    {:else}
      <table class="matrix" border="1">
        <thead>
          <tr>
            <th>Deliverable</th>
            <th class="num">Ordered</th>
            <th>Units</th>
            {#each shipments as sh}
              <th class="ship-head">
                Shipment #{sh.sequence}<br>
                <em class:picked={sh.status === 'picked_up'}>{sh.status === 'picked_up' ? 'picked up' : 'prepared'}</em><br>
                <span class="date">{shipmentDate(sh)}</span>
                <div class="actions">
                  {#if sh.status === 'prepared'}
                    <button type="button" onclick={() => pickUp(sh)}>Mark picked up</button>
                  {/if}
                  <button type="button" onclick={() => printPackingList(sh)}>Print</button>
                  {#if sh.status === 'prepared'}
                    <button type="button" class="discard" onclick={() => discardShipment(sh)}>Discard</button>
                  {/if}
                </div>
              </th>
            {/each}
            <th class="num">Remaining</th>
          </tr>
        </thead>
        <tbody>
          {#each deliverables as d}
            <tr>
              <td>{d.description}</td>
              <td class="num">{d.qty_ordered}</td>
              <td>{d.units}</td>
              {#each shipments as sh}
                <td class="num">
                  {#if sh.status === 'picked_up'}
                    {getItem(sh, d.id)?.qty ?? ''}
                  {:else}
                    <input
                      class="qty-input"
                      class:pending-cell={cellIsPending(sh, d.id)}
                      value={cellValue(sh, d.id)}
                      oninput={(e) => onCellInput(sh, d.id, e.target.value)}
                    />
                  {/if}
                </td>
              {/each}
              <td class="num">{d.qty_remaining}</td>
            </tr>
          {/each}
          <tr class="totals">
            <td colspan="3"><strong>Shipment total</strong></td>
            {#each shipments as sh}
              <td class="num"><strong>{columnTotal(sh)}</strong></td>
            {/each}
            <td></td>
          </tr>
        </tbody>
      </table>
    {/if}
  {:else}
    <p class="err">Failed to load job.</p>
  {/if}
</div>

<style>
  .page { padding: 20px 24px; }
  .action-row {
    display: flex;
    gap: 8px;
    align-items: center;
    margin: 8px 0;
  }
  .pending-note {
    font-style: italic;
    color: #b45309;
    font-size: 13px;
  }
  .matrix { width: 100%; border-collapse: collapse; font-size: 13px; }
  .matrix th, .matrix td { padding: 6px 10px; text-align: left; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .ship-head { text-align: center; font-weight: normal; vertical-align: top; }
  .ship-head em { color: #555; font-style: italic; }
  .ship-head em.picked { color: #1a7a3a; }
  .date { color: #777; font-size: 11px; }
  .actions { margin-top: 6px; display: flex; flex-direction: column; gap: 4px; align-items: center; }
  .actions button { font-size: 11px; padding: 2px 6px; }
  .actions button.discard { color: #b91c1c; }
  .qty-input { width: 5em; text-align: right; }
  .qty-input.pending-cell {
    background: #fef3c7;
    border-color: #b45309;
  }
  .err { color: #c00; }
  .totals td { background: #f5f5f5; }
</style>
