<script>
  import { push } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';

  const { params = {} } = $props();

  let job = $state(null);
  let loading = $state(true);
  let error = $state('');
  let saving = $state(false);

  let name = $state('');
  let description = $state('');
  let dueDate = $state('');
  let customerPoNumber = $state('');

  // Deliverables. Each row carries an _orig snapshot used to detect dirty
  // state and a _new flag for rows that haven't been saved yet.
  let deliverables = $state([]);
  let deliverablesEditable = $state(false);
  let deliverablesReason = $state(null);
  let rowError = $state(''); // per-row save/delete error surface

  const canManageJobs = $derived(
    $userStore?.permissions?.includes('can_manage_jobs') ?? false
  );

  async function load() {
    loading = true;
    error = '';
    try {
      job = await api.get(`/api/jobs/${params.id}/`);
      name = job.name || '';
      description = job.description || '';
      customerPoNumber = job.customer_po_number || '';
      dueDate = job.due_date ? toDatetimeLocal(job.due_date) : '';
      await loadDeliverables();
    } catch (e) {
      error = e.message || 'Could not load job.';
    } finally {
      loading = false;
    }
  }

  async function loadDeliverables() {
    const [items, ed] = await Promise.all([
      api.get(`/api/jobs/${params.id}/deliverables/`),
      api.get(`/api/jobs/${params.id}/deliverables/editability/`),
    ]);
    deliverables = items.map(d => ({
      id: d.id,
      description: d.description,
      qty_ordered: d.qty_ordered,
      units: d.units,
      _orig: {
        description: d.description,
        qty_ordered: d.qty_ordered,
        units: d.units,
      },
      _new: false,
      _saving: false,
    }));
    deliverablesEditable = ed.editable;
    deliverablesReason = ed.reason;
  }

  function rowIsDirty(r) {
    if (r._new) return true;
    return (
      r.description !== r._orig.description
      || String(r.qty_ordered) !== String(r._orig.qty_ordered)
      || r.units !== r._orig.units
    );
  }

  function reasonLabel(r) {
    if (r === 'estimate_sent') return 'estimate sent — revise the estimate to edit deliverables';
    if (r === 'estimate_accepted') return 'estimate accepted — deliverables are locked';
    return '';
  }

  function addNewDeliverable() {
    deliverables = [...deliverables, {
      id: null,
      description: '',
      qty_ordered: '1',
      units: 'ea',
      _orig: { description: '', qty_ordered: '', units: '' },
      _new: true,
      _saving: false,
    }];
  }

  async function saveDeliverable(row, idx) {
    rowError = '';
    deliverables[idx]._saving = true;
    deliverables = [...deliverables];
    try {
      const payload = {
        description: row.description,
        qty_ordered: row.qty_ordered,
        units: row.units,
      };
      let saved;
      if (row._new) {
        saved = await api.post(`/api/jobs/${params.id}/deliverables/`, payload);
      } else {
        saved = await api.patch(`/api/jobs/${params.id}/deliverables/${row.id}/`, payload);
      }
      deliverables[idx] = {
        id: saved.id,
        description: saved.description,
        qty_ordered: saved.qty_ordered,
        units: saved.units,
        _orig: {
          description: saved.description,
          qty_ordered: saved.qty_ordered,
          units: saved.units,
        },
        _new: false,
        _saving: false,
      };
      deliverables = [...deliverables];
    } catch (e) {
      rowError = e.message || 'Save failed.';
      deliverables[idx]._saving = false;
      deliverables = [...deliverables];
    }
  }

  async function deleteDeliverable(row, idx) {
    if (row._new) {
      // Just drop the unsaved row.
      deliverables = deliverables.filter((_, i) => i !== idx);
      return;
    }
    if (!confirm(`Delete deliverable "${row.description || 'unnamed'}"?`)) return;
    rowError = '';
    try {
      await api.delete(`/api/jobs/${params.id}/deliverables/${row.id}/`);
      deliverables = deliverables.filter((_, i) => i !== idx);
    } catch (e) {
      rowError = e.message || 'Delete failed.';
    }
  }

  function toDatetimeLocal(iso) {
    const d = new Date(iso);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    saving = true;
    error = '';
    const payload = {
      name,
      description,
      customer_po_number: customerPoNumber,
      due_date: dueDate ? new Date(dueDate).toISOString() : null,
    };
    try {
      await api.patch(`/api/jobs/${params.id}/`, payload);
      push(`/jobs/${params.id}`);
    } catch (err) {
      if (err.data && typeof err.data === 'object' && !err.data.detail) {
        error = Object.entries(err.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = err.message || 'Could not save job.';
      }
    } finally {
      saving = false;
    }
  }

  function handleCancel() {
    push(`/jobs/${params.id}`);
  }

  $effect(() => {
    void params.id;
    load();
  });
</script>

{#if loading}
  <p>Loading...</p>
{:else if error && !job}
  <p class="error">{error}</p>
{:else if !canManageJobs}
  <p>You do not have permission to edit jobs.</p>
{:else if job}
  <h2>Edit Job: {job.job_number}</h2>

  <form onsubmit={handleSubmit}>
    <p>
      <label for="name"><strong>Name</strong></label><br>
      <input id="name" type="text" maxlength="50" bind:value={name}>
    </p>

    <p>
      <label for="description"><strong>Description</strong></label><br>
      <textarea id="description" rows="6" cols="60" bind:value={description}></textarea>
    </p>

    <fieldset class="deliverables">
      <legend><strong>Deliverables</strong>
        {#if !deliverablesEditable && deliverablesReason}
          <span class="reason">({reasonLabel(deliverablesReason)})</span>
        {/if}
      </legend>
      {#if deliverables.length === 0}
        <p class="muted">No deliverables.</p>
      {:else}
        <table class="deliverables-table">
          <thead>
            <tr>
              <th>Qty</th>
              <th>Units</th>
              <th>Description</th>
              {#if deliverablesEditable}<th></th>{/if}
            </tr>
          </thead>
          <tbody>
            {#each deliverables as row, i (row.id ?? `new-${i}`)}
              <tr>
                {#if deliverablesEditable}
                  <td><input type="text" bind:value={row.qty_ordered} class="qty"></td>
                  <td><input type="text" bind:value={row.units} class="units"></td>
                  <td><input type="text" bind:value={row.description} class="desc"></td>
                  <td class="row-actions">
                    <button type="button"
                            onclick={() => saveDeliverable(row, i)}
                            disabled={row._saving || !rowIsDirty(row)}>
                      {row._saving ? 'Saving...' : 'Save'}
                    </button>
                    <button type="button" onclick={() => deleteDeliverable(row, i)} disabled={row._saving}>
                      Delete
                    </button>
                  </td>
                {:else}
                  <td>{row.qty_ordered}</td>
                  <td>{row.units}</td>
                  <td>{row.description}</td>
                {/if}
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
      {#if deliverablesEditable}
        <p>
          <button type="button" onclick={addNewDeliverable}>+ Add deliverable</button>
        </p>
      {/if}
      {#if rowError}<p class="error">{rowError}</p>{/if}
    </fieldset>

    <p>
      <label for="due_date"><strong>Due Date</strong></label><br>
      <input id="due_date" type="datetime-local" bind:value={dueDate}>
    </p>

    <p>
      <label for="customer_po"><strong>Customer PO Number</strong></label><br>
      <input id="customer_po" type="text" maxlength="50" bind:value={customerPoNumber}>
    </p>

    <p>
      <button type="submit" disabled={saving}>{saving ? 'Saving...' : 'Save'}</button>
      <button type="button" onclick={handleCancel} disabled={saving}>Cancel</button>
    </p>

    {#if error}<p class="error">{error}</p>{/if}
  </form>
{/if}

<style>
  .error { color: #a8071a; }
  .muted { color: #777; font-style: italic; margin: 4px 0; }
  .reason { font-style: italic; font-weight: normal; color: #555; margin-left: 6px; }
  .deliverables { margin: 12px 0; padding: 8px 12px 12px; }
  .deliverables-table { border-collapse: collapse; }
  .deliverables-table th { text-align: left; padding: 4px 8px; font-size: 12px; color: #666; font-weight: normal; }
  .deliverables-table td { padding: 4px 6px 4px 0; vertical-align: middle; }
  .deliverables-table input.qty { width: 5em; text-align: right; }
  .deliverables-table input.units { width: 6em; }
  .deliverables-table input.desc { width: 30em; }
  .row-actions { white-space: nowrap; }
  .row-actions button { margin-right: 4px; }
</style>
