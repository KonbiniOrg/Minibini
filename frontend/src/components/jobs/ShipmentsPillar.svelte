<script>
  import { api } from '../../lib/api.js';

  let { jobId } = $props();

  let deliverables = $state([]);
  let shipments = $state([]);
  let loading = $state(true);

  async function load() {
    loading = true;
    try {
      const [d, s] = await Promise.all([
        api.get(`/api/jobs/${jobId}/deliverables/`),
        api.get(`/api/shipments/?job=${jobId}`),
      ]);
      deliverables = d;
      const list = s.results || s;
      shipments = list.slice().sort((a, b) => a.sequence - b.sequence);
    } finally {
      loading = false;
    }
  }

  $effect(() => { if (jobId) load(); });

  function qtyAt(deliverableId, shipment) {
    const item = (shipment.items || []).find(it => it.deliverable === deliverableId);
    return item ? item.qty : '';
  }

  function shipmentDate(sh) {
    const iso = sh.status === 'picked_up' ? sh.picked_up_date : sh.prepared_date;
    if (!iso) return '';
    return new Date(iso).toLocaleDateString();
  }
</script>

<div class="shipments-readonly">
  {#if loading}
    <p class="empty-msg">Loading...</p>
  {:else if deliverables.length === 0}
    <p class="empty-msg">No deliverables yet; cannot ship.</p>
  {:else if shipments.length === 0}
    <p class="empty-msg">No shipments yet.</p>
  {:else}
    <table class="matrix">
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
            </th>
          {/each}
          <th class="num">Remaining</th>
        </tr>
      </thead>
      <tbody>
        {#each deliverables as d}
          <tr>
            <td class="preserve-breaks">{d.description}</td>
            <td class="num">{d.qty_ordered}</td>
            <td>{d.units}</td>
            {#each shipments as sh}
              <td class="num">{qtyAt(d.id, sh)}</td>
            {/each}
            <td class="num">{d.qty_remaining}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>

<style>
  .shipments-readonly { padding: 8px 0; }
  .matrix {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .matrix th, .matrix td {
    border: 1px solid #e5e7eb;
    padding: 6px 8px;
    text-align: left;
  }
  .matrix th.num, .matrix td.num {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .ship-head { text-align: center; font-weight: normal; }
  .ship-head em { color: #555; font-style: italic; }
  .ship-head em.picked { color: #1a7a3a; }
  .date { color: #777; font-size: 11px; }
  .empty-msg { color: #777; padding: 12px; }
</style>
