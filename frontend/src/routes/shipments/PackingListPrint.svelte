<script>
  import { api } from '../../lib/api.js';

  let { params } = $props();
  const shipmentId = $derived(parseInt(params.sid, 10));

  let payload = $state(null);
  let loading = $state(true);
  let errorMsg = $state('');

  async function load() {
    loading = true;
    errorMsg = '';
    try {
      payload = await api.get(`/api/shipments/${shipmentId}/packing-list/`);
    } catch (e) {
      errorMsg = e.message || 'Load failed.';
    } finally {
      loading = false;
    }
  }

  $effect(() => { if (shipmentId) load(); });

  function fmtDateTime(iso) {
    if (!iso) return '';
    return new Date(iso).toLocaleString();
  }
</script>

{#if loading}
  <p>Loading packing list...</p>
{:else if errorMsg}
  <p class="err">{errorMsg}</p>
{:else if payload}
  <article class="packing-list">
    <h1>Packing list</h1>

    <section class="parties">
      <div class="party">
        <div class="party-label">From</div>
        <!-- TODO: source this from a Configuration row (company_name, etc.) -->
        <div class="party-name">[Your Company Name]</div>
        <div class="party-line">[Street address]</div>
        <div class="party-line">[City, Province  Postal code]</div>
        <div class="party-line">[Phone]</div>
      </div>
      <div class="party">
        <div class="party-label">To</div>
        {#if payload.customer.business_name}
          <div class="party-name">{payload.customer.business_name}</div>
          {#if payload.customer.contact_name}
            <div class="party-line">c/o {payload.customer.contact_name}</div>
          {/if}
        {:else if payload.customer.contact_name}
          <div class="party-name">{payload.customer.contact_name}</div>
        {:else}
          <div class="party-name">[Customer]</div>
        {/if}
        {#if payload.customer.business_address}
          {#each payload.customer.business_address.split(/\r?\n/).filter(Boolean) as addr}
            <div class="party-line">{addr}</div>
          {/each}
        {:else if payload.customer.contact_address_lines?.length}
          {#each payload.customer.contact_address_lines as addr}
            <div class="party-line">{addr}</div>
          {/each}
        {/if}
      </div>
    </section>

    <p><strong>Job:</strong> {payload.job.job_number} — {payload.job.name}</p>
    <p><strong>Shipment #:</strong> {payload.shipment.sequence}</p>
    <p><strong>Status:</strong> {payload.shipment.status === 'picked_up' ? 'Picked up' : 'Prepared'}</p>
    <p><strong>Prepared:</strong> {fmtDateTime(payload.shipment.prepared_date)}</p>
    {#if payload.shipment.picked_up_date}
      <p><strong>Picked up:</strong> {fmtDateTime(payload.shipment.picked_up_date)}</p>
    {/if}

    <table border="1">
      <thead>
        <tr>
          <th>Description</th>
          <th>Units</th>
          <th>Qty ordered</th>
          <th>Previously delivered</th>
          <th>This shipment</th>
          <th>Remaining after this shipment</th>
        </tr>
      </thead>
      <tbody>
        {#each payload.rows as r}
          <tr>
            <td>{r.description}</td>
            <td>{r.units}</td>
            <td class="num">{r.qty_ordered}</td>
            <td class="num">{r.qty_previously_picked_up}</td>
            <td class="num">{r.qty_this_shipment}</td>
            <td class="num">{r.qty_remaining_after_this_shipment}</td>
          </tr>
        {/each}
      </tbody>
    </table>

    {#if payload.shipment.notes}
      <p><strong>Notes:</strong> {payload.shipment.notes}</p>
    {/if}

    <section class="signatures">
      <div class="sig-row">
        <span class="sig-label">Pickup by</span>
        <span class="sig-line sig-line-long"></span>
        <span class="sig-label">Pickup date</span>
        <span class="sig-line sig-line-short"></span>
      </div>
    </section>
  </article>
{/if}

<style>
  .packing-list {
    max-width: 8.5in;
    margin: 0 auto;
    padding: 0.5in;
    font-size: 14px;
  }
  .packing-list h1 { font-size: 20px; margin-bottom: 12px; }
  .parties {
    display: flex;
    gap: 24px;
    margin: 16px 0 24px;
  }
  .party {
    flex: 1 1 0;
    border: 1px solid #ccc;
    padding: 8px 12px;
  }
  .party-label {
    font-size: 11px;
    text-transform: uppercase;
    color: #666;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
  }
  .party-name { font-weight: bold; }
  .party-line { line-height: 1.4; }
  .packing-list table { width: 100%; border-collapse: collapse; margin-top: 16px; }
  .packing-list th, .packing-list td { padding: 6px 10px; text-align: left; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .signatures {
    margin-top: 48px;
  }
  .sig-row {
    display: flex;
    align-items: flex-end;
    gap: 12px;
  }
  .sig-label {
    flex: 0 0 auto;
    font-weight: bold;
    white-space: nowrap;
  }
  .sig-line {
    border-bottom: 1px solid #333;
    height: 1.6em;
  }
  .sig-line-long  { flex: 2 1 0; }
  .sig-line-short { flex: 1 1 0; }
  .err { color: #c00; padding: 16px; }
  @media print {
    :global(.sidebar), :global(.current-blep-band) { display: none !important; }
    :global(.page-content) { margin-left: 0 !important; }
  }
</style>
