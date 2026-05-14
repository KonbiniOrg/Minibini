<script>
  import { api } from '../../lib/api.js';
  import { link } from 'svelte-spa-router';

  let { params } = $props();
  const jobId = $derived(parseInt(params.jobId, 10));

  let deliverables = $state([]);
  let shipments = $state([]);
  let job = $state(null);
  let loading = $state(true);
  let errorMsg = $state('');

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

  async function addShipment() {
    try {
      await api.post(`/api/jobs/${jobId}/shipments/`, {});
      await load();
    } catch (e) { errorMsg = e.message || 'Add shipment failed.'; }
  }

  async function pickUp(sh) {
    if (!confirm(`Mark Shipment #${sh.sequence} as picked up? This locks the shipment.`)) return;
    try {
      await api.post(`/api/shipments/${sh.id}/pick-up/`, {});
      await load();
    } catch (e) { errorMsg = e.message || 'Pick-up failed.'; }
  }

  async function deleteShipment(sh) {
    if (!confirm(`Delete Shipment #${sh.sequence}?`)) return;
    try {
      await api.delete(`/api/shipments/${sh.id}/`);
      await load();
    } catch (e) { errorMsg = e.message || 'Delete failed.'; }
  }

  async function setQty(sh, deliverableId, rawValue) {
    if (sh.status !== 'prepared') return;
    const trimmed = String(rawValue ?? '').trim();
    const existing = getItem(sh, deliverableId);
    try {
      if (trimmed === '' || Number(trimmed) === 0) {
        if (existing) {
          await api.delete(`/api/shipments/${sh.id}/items/${existing.id}/`);
        }
      } else if (existing) {
        await api.patch(`/api/shipments/${sh.id}/items/${existing.id}/`, { qty: trimmed });
      } else {
        await api.post(`/api/shipments/${sh.id}/items/`, {
          deliverable: deliverableId,
          qty: trimmed,
        });
      }
      await load();
    } catch (e) { errorMsg = e.message || 'Save failed.'; }
  }

  function printPackingList(sh) {
    window.open(`#/shipments/${sh.id}/print`, '_blank');
  }

  function shipmentDate(sh) {
    const iso = sh.status === 'picked_up' ? sh.picked_up_date : sh.prepared_date;
    if (!iso) return '';
    return new Date(iso).toLocaleDateString();
  }

  function columnTotal(sh) {
    return (sh.items || []).reduce((sum, it) => sum + Number(it.qty), 0);
  }
</script>

<div class="page">
  {#if loading}
    <p>Loading...</p>
  {:else if job}
    <header>
      <h2>Shipments for {job.job_number}: {job.name}</h2>
      <p><a use:link href={`/jobs/${jobId}`}>← Back to job</a></p>
      <p><button type="button" onclick={addShipment}>+ Add shipment</button></p>
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
                  {#if sh.status === 'prepared' && (sh.items || []).length === 0}
                    <button type="button" onclick={() => deleteShipment(sh)}>Delete</button>
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
                      value={getItem(sh, d.id)?.qty ?? ''}
                      onblur={(e) => setQty(sh, d.id, e.target.value)}
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
  .matrix { width: 100%; border-collapse: collapse; font-size: 13px; }
  .matrix th, .matrix td { padding: 6px 10px; text-align: left; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .ship-head { text-align: center; font-weight: normal; vertical-align: top; }
  .ship-head em { color: #555; font-style: italic; }
  .ship-head em.picked { color: #1a7a3a; }
  .date { color: #777; font-size: 11px; }
  .actions { margin-top: 6px; display: flex; flex-direction: column; gap: 4px; align-items: center; }
  .actions button { font-size: 11px; padding: 2px 6px; }
  .qty-input { width: 5em; text-align: right; }
  .err { color: #c00; }
  .totals td { background: #f5f5f5; }
</style>
