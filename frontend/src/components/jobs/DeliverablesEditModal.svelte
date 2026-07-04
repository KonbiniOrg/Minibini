<script>
  import { api } from '../../lib/api.js';
  import Modal from '../Modal.svelte';
  import UnitsSelect from '../UnitsSelect.svelte';

  let { jobId, onClose } = $props();

  let rows = $state([]);
  let loading = $state(true);
  let saving = $state(false);
  let dirty = $state(false);
  let errorMsg = $state('');

  async function load() {
    loading = true;
    try {
      const items = await api.get(`/api/jobs/${jobId}/deliverables/`);
      rows = items.map(r => ({ ...r, _new: false, _deleted: false }));
    } finally {
      loading = false;
    }
  }

  function addRow() {
    rows = [...rows, {
      id: null,
      description: '',
      qty_ordered: '1',
      units: 'ea',
      sort_order: (rows.length + 1) * 10,
      _new: true,
      _deleted: false,
    }];
    dirty = true;
  }

  function deleteRow(target) {
    const idx = rows.indexOf(target);
    if (idx < 0) return;
    const r = rows[idx];
    if (r._new) {
      rows = rows.filter((_, i) => i !== idx);
    } else {
      rows[idx]._deleted = true;
      rows = [...rows];
    }
    dirty = true;
  }

  function moveUp(visibleIdx, visibleRows) {
    if (visibleIdx === 0) return;
    const target = visibleRows[visibleIdx];
    const above = visibleRows[visibleIdx - 1];
    const arr = [...rows];
    const i = arr.indexOf(target);
    const j = arr.indexOf(above);
    [arr[i], arr[j]] = [arr[j], arr[i]];
    rows = arr;
    dirty = true;
  }

  function moveDown(visibleIdx, visibleRows) {
    if (visibleIdx === visibleRows.length - 1) return;
    const target = visibleRows[visibleIdx];
    const below = visibleRows[visibleIdx + 1];
    const arr = [...rows];
    const i = arr.indexOf(target);
    const j = arr.indexOf(below);
    [arr[i], arr[j]] = [arr[j], arr[i]];
    rows = arr;
    dirty = true;
  }

  async function save() {
    saving = true;
    errorMsg = '';
    try {
      for (const r of rows.filter(x => x._deleted && x.id)) {
        await api.delete(`/api/jobs/${jobId}/deliverables/${r.id}/`);
      }
      const surviving = rows.filter(r => !r._deleted);
      for (const r of surviving.filter(x => x._new)) {
        const created = await api.post(`/api/jobs/${jobId}/deliverables/`, {
          description: r.description,
          qty_ordered: r.qty_ordered,
          units: r.units,
        });
        r.id = created.id;
        r._new = false;
      }
      for (const r of surviving.filter(x => !x._new)) {
        await api.patch(`/api/jobs/${jobId}/deliverables/${r.id}/`, {
          description: r.description,
          qty_ordered: r.qty_ordered,
          units: r.units,
        });
      }
      const ordered_ids = surviving.map(r => r.id).filter(Boolean);
      if (ordered_ids.length > 0) {
        await api.post(`/api/jobs/${jobId}/deliverables/reorder/`, { ordered_ids });
      }
      onClose(true);
    } catch (err) {
      errorMsg = err.message || 'Save failed.';
    } finally {
      saving = false;
    }
  }

  function cancel() {
    onClose(false);
  }

  $effect(() => { if (jobId) load(); });

  let visibleRows = $derived(rows.filter(r => !r._deleted));
</script>

<Modal open={true} onSave={() => { if (!saving && dirty) save(); }}
  onCancel={cancel} maxWidth="80vw" label="Edit deliverables">
  <h3>Edit deliverables</h3>
    {#if loading}
      <p>Loading...</p>
    {:else}
      <table class="data-table">
        <thead>
          <tr><th>Order</th><th>Description</th><th>Qty</th><th>Units</th><th></th></tr>
        </thead>
        <tbody>
          {#each visibleRows as r, i (r.id || `new-${rows.indexOf(r)}`)}
            <tr>
              <td>
                <button type="button" onclick={() => moveUp(i, visibleRows)} disabled={i === 0}>↑</button>
                <button type="button" onclick={() => moveDown(i, visibleRows)} disabled={i === visibleRows.length - 1}>↓</button>
              </td>
              <td><input bind:value={r.description} oninput={() => dirty = true} /></td>
              <td><input bind:value={r.qty_ordered} oninput={() => dirty = true} style="width: 5em" /></td>
              <td><UnitsSelect bind:value={r.units} onchange={() => dirty = true} /></td>
              <td><button type="button" onclick={() => deleteRow(r)}>Delete</button></td>
            </tr>
          {/each}
        </tbody>
      </table>
      <p><button type="button" onclick={addRow}>+ Add row</button></p>
      {#if errorMsg}<p class="err">{errorMsg}</p>{/if}
      <p>
        <button type="button" onclick={save} disabled={saving || !dirty}>Save</button>
        <button type="button" onclick={cancel} disabled={saving}>Cancel</button>
      </p>
    {/if}
</Modal>

<style>
  .err { color: #c00; }
  table { width: 100%; border-collapse: collapse; }
</style>
