<script>
  import { api } from '../../lib/api.js';

  let { job, onJobChange = () => {} } = $props();

  let deliverables = $state([]);
  let shipments = $state([]); // server-persisted only
  let draftShipments = $state([]); // local-only, not yet on the server
  let nextDraftCounter = 1;
  let loading = $state(true);
  let saving = $state(false);
  let errorMsg = $state('');

  // Pending edits keyed by `${shipmentKey}:${deliverableId}`. shipmentKey is
  // the server id for persisted shipments and the local _draftId for drafts.
  let pending = $state({});

  async function load() {
    loading = true;
    errorMsg = '';
    try {
      const [d, s] = await Promise.all([
        api.get(`/api/jobs/${job.job_id}/deliverables/`),
        api.get(`/api/shipments/?job=${job.job_id}`),
      ]);
      deliverables = d;
      const list = s.results || s;
      shipments = list.slice().sort((a, b) => a.sequence - b.sequence);
    } catch (e) {
      errorMsg = e.message || 'Load failed.';
    } finally {
      loading = false;
    }
  }

  $effect(() => { if (job?.job_id) load(); });

  function shipmentKey(sh) {
    return sh._draftId ?? sh.id;
  }

  function isDraft(sh) {
    return Boolean(sh._draftId);
  }

  function getItem(sh, deliverableId) {
    if (isDraft(sh)) return undefined; // drafts have no server items yet
    return (sh.items || []).find(it => it.deliverable === deliverableId);
  }

  function pendingKey(key, deliverableId) {
    return `${key}:${deliverableId}`;
  }

  function cellValue(sh, deliverableId) {
    const key = pendingKey(shipmentKey(sh), deliverableId);
    if (key in pending) return pending[key];
    if (isDraft(sh)) return '';
    return getItem(sh, deliverableId)?.qty ?? '';
  }

  function cellIsPending(sh, deliverableId) {
    return pendingKey(shipmentKey(sh), deliverableId) in pending;
  }

  function onCellInput(sh, deliverableId, value) {
    if (sh.status !== 'prepared') return;
    const key = pendingKey(shipmentKey(sh), deliverableId);
    pending = { ...pending, [key]: value };
  }

  let hasChanges = $derived(Object.keys(pending).length > 0 || draftShipments.length > 0);

  let displayedShipments = $derived([...shipments, ...draftShipments]);

  function addShipment() {
    // Local-only draft. Not persisted until Save runs and finds at least one
    // non-zero qty in this draft's cells.
    const draftId = `draft-${nextDraftCounter}`;
    nextDraftCounter += 1;
    const newDraft = {
      id: null,
      _draftId: draftId,
      sequence: null,
      status: 'prepared',
      prepared_date: new Date().toISOString(),
      picked_up_date: null,
      notes: '',
      items: [],
    };
    draftShipments = [...draftShipments, newDraft];
    // Prefill with each deliverable's current remaining qty.
    const next = { ...pending };
    for (const d of deliverables) {
      const rem = Number(d.qty_remaining);
      if (Number.isFinite(rem) && rem > 0) {
        next[pendingKey(draftId, d.id)] = rem.toString();
      }
    }
    pending = next;
  }

  async function pickUp(sh) {
    if (isDraft(sh)) return; // drafts can't be picked up
    if (hasChanges) {
      if (!confirm('You have unsaved cell changes. Mark picked up anyway? Unsaved changes will be lost.')) return;
    } else if (!confirm(`Mark Shipment #${sh.sequence} as picked up? This locks the shipment.`)) {
      return;
    }
    try {
      await api.post(`/api/shipments/${sh.id}/pick-up/`, {});
      pending = {};
      draftShipments = [];
      await load();
      onJobChange();
    } catch (e) { errorMsg = e.message || 'Pick-up failed.'; }
  }

  async function discardShipment(sh) {
    if (sh.status !== 'prepared') return;

    if (isDraft(sh)) {
      // Local-only — no server call needed.
      draftShipments = draftShipments.filter(d => d._draftId !== sh._draftId);
      const prefix = `${sh._draftId}:`;
      const next = {};
      for (const [k, v] of Object.entries(pending)) {
        if (!k.startsWith(prefix)) next[k] = v;
      }
      pending = next;
      return;
    }

    const itemCount = (sh.items || []).length;
    const msg = itemCount > 0
      ? `Discard Shipment #${sh.sequence}? This removes ${itemCount} item${itemCount === 1 ? '' : 's'} from the shipment and deletes the shipment itself. The Deliverables list is unchanged.`
      : `Discard Shipment #${sh.sequence}?`;
    if (!confirm(msg)) return;
    try {
      for (const item of (sh.items || [])) {
        await api.delete(`/api/shipments/${sh.id}/items/${item.id}/`);
      }
      await api.delete(`/api/shipments/${sh.id}/`);
      const prefix = `${sh.id}:`;
      const next = {};
      for (const [k, v] of Object.entries(pending)) {
        if (!k.startsWith(prefix)) next[k] = v;
      }
      pending = next;
      await load();
      onJobChange();
    } catch (e) { errorMsg = e.message || 'Discard failed.'; }
  }

  // Pending cells for a given shipment, normalized {deliverableId, qty:string}.
  function pendingCellsFor(shipmentKeyStr) {
    const prefix = `${shipmentKeyStr}:`;
    const out = [];
    for (const [k, v] of Object.entries(pending)) {
      if (!k.startsWith(prefix)) continue;
      const deliverableId = Number(k.slice(prefix.length));
      out.push({ deliverableId, raw: v });
    }
    return out;
  }

  function hasAnyQty(cells) {
    return cells.some(({ raw }) => {
      const trimmed = String(raw ?? '').trim();
      return trimmed !== '' && Number(trimmed) > 0;
    });
  }

  async function saveChanges() {
    if (!hasChanges || saving) return;
    saving = true;
    errorMsg = '';
    try {
      // 1. Drafts: create the shipment server-side only if it has at least
      //    one non-zero qty. Otherwise drop the draft silently.
      for (const draft of draftShipments) {
        const cells = pendingCellsFor(draft._draftId);
        if (!hasAnyQty(cells)) continue;
        const created = await api.post(`/api/jobs/${job.job_id}/shipments/`, {});
        for (const { deliverableId, raw } of cells) {
          const trimmed = String(raw ?? '').trim();
          if (trimmed === '' || Number(trimmed) === 0) continue;
          await api.post(`/api/shipments/${created.id}/items/`, {
            deliverable: deliverableId,
            qty: trimmed,
          });
        }
      }

      // 2. Existing prepared shipments: apply pending edits. If the final
      //    state of items is empty, delete the shipment too — a shipment with
      //    no lines doesn't make sense.
      for (const sh of shipments) {
        if (sh.status !== 'prepared') continue;
        const cells = pendingCellsFor(String(sh.id));
        if (cells.length === 0) continue;

        for (const { deliverableId, raw } of cells) {
          const existing = getItem(sh, deliverableId);
          const trimmed = String(raw ?? '').trim();
          if (trimmed === '' || Number(trimmed) === 0) {
            if (existing) await api.delete(`/api/shipments/${sh.id}/items/${existing.id}/`);
          } else if (existing) {
            await api.patch(`/api/shipments/${sh.id}/items/${existing.id}/`, { qty: trimmed });
          } else {
            await api.post(`/api/shipments/${sh.id}/items/`, {
              deliverable: deliverableId,
              qty: trimmed,
            });
          }
        }

        // Recompute item count by walking the current item list and applying
        // the pending edits. (We didn't refetch yet.)
        const existingByDeliv = new Map((sh.items || []).map(it => [it.deliverable, it.qty]));
        for (const { deliverableId, raw } of cells) {
          const trimmed = String(raw ?? '').trim();
          if (trimmed === '' || Number(trimmed) === 0) {
            existingByDeliv.delete(deliverableId);
          } else {
            existingByDeliv.set(deliverableId, trimmed);
          }
        }
        if (existingByDeliv.size === 0) {
          await api.delete(`/api/shipments/${sh.id}/`);
        }
      }

      pending = {};
      draftShipments = [];
      await load();
      onJobChange();
    } catch (e) {
      errorMsg = e.message || 'Save failed. Earlier rows may have been saved; later rows were not.';
    } finally {
      saving = false;
    }
  }

  function discardChanges() {
    // Drops both cell edits and any local drafts.
    pending = {};
    draftShipments = [];
  }

  function printPackingList(sh) {
    if (isDraft(sh)) return;
    window.open(`#/shipments/${sh.id}/print`, '_blank');
  }

  function shipmentDate(sh) {
    const iso = sh.status === 'picked_up' ? sh.picked_up_date : sh.prepared_date;
    if (!iso) return '';
    return new Date(iso).toLocaleDateString();
  }

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
  {:else}
    <div class="page-body">
    <header class="page-header">
      <h2>Shipments</h2>
      <div class="action-row">
        <button type="button" onclick={addShipment}>+ Add shipment</button>
        <button type="button" onclick={saveChanges} disabled={!hasChanges || saving}>
          {saving ? 'Saving...' : 'Save changes'}
        </button>
        <button type="button" onclick={discardChanges} disabled={!hasChanges || saving}>Discard changes</button>
        {#if hasChanges}
          <span class="pending-note">unsaved changes</span>
        {/if}
      </div>
      {#if errorMsg}<p class="err">{errorMsg}</p>{/if}
    </header>

    {#if deliverables.length === 0}
      <p>This job has no deliverables yet.</p>
    {:else if displayedShipments.length === 0}
      <p>No shipments yet. Click "+ Add shipment" to create one.</p>
    {:else}
      <table class="matrix">
        <thead>
          <tr>
            <th>Deliverable</th>
            <th class="num">Ordered</th>
            <th>Units</th>
            {#each displayedShipments as sh (shipmentKey(sh))}
              <th class="ship-head" class:draft={isDraft(sh)}>
                {#if isDraft(sh)}
                  New shipment<br>
                  <em>unsaved</em>
                {:else}
                  Shipment #{sh.sequence}<br>
                  <em class:picked={sh.status === 'picked_up'}>{sh.status === 'picked_up' ? 'picked up' : 'prepared'}</em><br>
                  <span class="date">{shipmentDate(sh)}</span>
                {/if}
                <div class="actions row-actions">
                  {#if sh.status === 'prepared' && !isDraft(sh)}
                    <button type="button" onclick={() => pickUp(sh)}>Mark picked up</button>
                  {/if}
                  {#if !isDraft(sh)}
                    <button type="button" onclick={() => printPackingList(sh)}>Print</button>
                  {/if}
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
              {#each displayedShipments as sh (shipmentKey(sh))}
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
            {#each displayedShipments as sh (shipmentKey(sh))}
              <td class="num"><strong>{columnTotal(sh)}</strong></td>
            {/each}
            <td></td>
          </tr>
        </tbody>
      </table>
    {/if}
  </div>
  {/if}
</div>

<style>
  .page { padding: 0 0 20px 0; }
  .page-header { padding: 0; }
  .page-header h2 { margin-top: 16px; }
  .matrix { margin: 0 24px; width: calc(100% - 48px); }
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
  .matrix { border-collapse: collapse; font-size: 13px; }
  .matrix th, .matrix td { padding: 6px 10px; text-align: left; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .ship-head { text-align: center; font-weight: normal; vertical-align: top; }
  .ship-head em { color: #555; font-style: italic; }
  .ship-head em.picked { color: #1a7a3a; }
  .ship-head.draft { background: #fef3c7; }
  .ship-head.draft em { color: #92400e; font-weight: 500; }
  .date { color: #777; font-size: 11px; }
  .actions { margin-top: 6px; display: flex; flex-direction: column; gap: 4px; align-items: center; }
  /* Buttons pick up the shared .row-actions look (app.css). */
  .actions button.discard { color: #b91c1c; }
  .qty-input { width: 5em; text-align: right; }
  .qty-input.pending-cell {
    background: #fef3c7;
    border-color: #b45309;
  }
  .err { color: #c00; }
  .totals td { background: #f5f5f5; }
</style>
