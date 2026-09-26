<script>
  // Deliverables diff editor for the change-order panel: renders the merged
  // rows (lib/changeOrderDiff.buildDeliverableRows) and owns the inline
  // edit/new drafting forms. Extracted from the old ChangeOrderDetailPage
  // route (2026-07-19).
  //
  // Inline-edit surface — deliberately NOT the record-form kit (see LATER:
  // "No shared form-layout vocabulary"): this drafting grid keeps its own
  // compact flex-row idiom.
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';
  import UnitsSelect from '../UnitsSelect.svelte';

  let {
    jobId,            // deliverables are job-nested: /api/jobs/{jobId}/deliverables/
    rows = [],        // buildDeliverableRows output
    canEdit = false,  // canManageJobs && CO is draft
    onReload = () => {},
  } = $props();

  // Inline edit form state: deliverable id currently being edited, or null
  let editId = $state(null);
  let editDescription = $state('');
  let editQty = $state('');
  let editUnits = $state('ea');
  // New deliverable form
  let newOpen = $state(false);
  let newDescription = $state('');
  let newQty = $state('1');
  let newUnits = $state('ea');
  let saving = $state(false);
  // Inline-form error state (triaged: field bag + footer message per form)
  let editError = $state('');
  let editFields = $state({});
  let newError = $state('');
  let newFields = $state({});

  function fmtQty(v) {
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v);
    return Number.isFinite(n) ? n.toString() : String(v);
  }

  function openEdit(liveRow) {
    editId = liveRow.id;
    editDescription = liveRow.description;
    editQty = String(Number(liveRow.qty_ordered));
    editUnits = liveRow.units;
    editError = '';
    editFields = {};
  }

  function cancelEdit() {
    editId = null;
    editError = '';
    editFields = {};
  }

  async function saveEdit(liveId) {
    saving = true;
    editError = '';
    editFields = {};
    try {
      await api.patch(`/api/jobs/${jobId}/deliverables/${liveId}/`, {
        description: editDescription,
        qty_ordered: editQty,
        units: editUnits,
      });
      editId = null;
      await onReload();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else { editError = t.message; editFields = t.fields; }
    } finally {
      saving = false;
    }
  }

  async function deleteDeliverable(liveId) {
    try {
      await api.delete(`/api/jobs/${jobId}/deliverables/${liveId}/`);
      await onReload();
    } catch (e) {
      showError(errorMessage(e, 'Could not delete deliverable.'));
    }
  }

  /** Undo a changed deliverable: PATCH live back to baseline values */
  async function undoChange(liveId, snap) {
    try {
      await api.patch(`/api/jobs/${jobId}/deliverables/${liveId}/`, {
        description: snap.description,
        qty_ordered: snap.qty_ordered,
        units: snap.units,
      });
      await onReload();
    } catch (e) {
      showError(errorMessage(e, 'Could not undo change.'));
    }
  }

  /** Undo a removed deliverable: POST a new live deliverable with baseline values */
  async function undoRemove(snap) {
    try {
      await api.post(`/api/jobs/${jobId}/deliverables/`, {
        description: snap.description,
        qty_ordered: snap.qty_ordered,
        units: snap.units,
      });
      await onReload();
    } catch (e) {
      showError(errorMessage(e, 'Could not restore deliverable.'));
    }
  }

  function openNew() {
    newDescription = '';
    newQty = '1';
    newUnits = 'ea';
    newOpen = true;
    newError = '';
    newFields = {};
  }

  function cancelNew() {
    newOpen = false;
    newError = '';
    newFields = {};
  }

  async function saveNew() {
    newError = '';
    newFields = {};
    if (!newDescription.trim()) {
      newFields = { description: ['Description is required.'] };
      return;
    }
    saving = true;
    try {
      await api.post(`/api/jobs/${jobId}/deliverables/`, {
        description: newDescription,
        qty_ordered: newQty,
        units: newUnits,
      });
      newOpen = false;
      await onReload();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else { newError = t.message; newFields = t.fields; }
    } finally {
      saving = false;
    }
  }

  // Keyboard handler for inline-edit rows (Enter = save, Esc = cancel)
  function editKeydown(event, saveHandler, cancelHandler) {
    if (event.key === 'Enter') {
      event.preventDefault();
      saveHandler();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      cancelHandler();
    }
  }
</script>

<section class="section">
  <div class="section-head">
    <h3>Deliverables</h3>
    <span class="spacer"></span>
    {#if canEdit && !newOpen}
      <button type="button" onclick={openNew}>+ New deliverable</button>
    {/if}
  </div>

  <table class="diff-table deliv-table">
    <colgroup>
      <col style="width:90px">
      <col>
      <col style="width:160px">
    </colgroup>
    <tbody>
      {#if rows.length === 0 && !newOpen}
        <tr>
          <td colspan="3" class="empty-msg">No deliverables yet.</td>
        </tr>
      {:else}
        {#each rows as row}
          {#if row.kind === 'unchanged'}
            {#if editId === row.live.id}
              <!-- Inline edit form for this row -->
              <tr class="row-editing">
                <td colspan="3">
                  <div class="edit-row-layout">
                    <input class="qty-input" bind:value={editQty}
                      onkeydown={(e) => editKeydown(e, () => saveEdit(row.live.id), cancelEdit)} />
                    <UnitsSelect bind:value={editUnits} />
                    <input class="desc-input-inline" bind:value={editDescription}
                      onkeydown={(e) => editKeydown(e, () => saveEdit(row.live.id), cancelEdit)} />
                    <button type="button" onclick={() => saveEdit(row.live.id)} disabled={saving}>Save</button>
                    <button type="button" onclick={cancelEdit} disabled={saving}>Cancel</button>
                  </div>
                  <FieldError errors={editFields} field="qty_ordered" />
                  <FieldError errors={editFields} field="units" />
                  <FieldError errors={editFields} field="description" />
                  <FormMessage error={editError} />
                </td>
              </tr>
            {:else}
              <tr>
                <td class="num">{fmtQty(row.qty)} {row.units}</td>
                <td>{row.description || '—'}</td>
                <td class="acts">
                  {#if canEdit}
                    {#if row.anchored}
                      <span class="anchored-note">shipped</span>
                    {:else}
                      <button type="button" onclick={() => openEdit(row.live)}>Change</button>
                      <button type="button" onclick={() => deleteDeliverable(row.live.id)}>Delete</button>
                    {/if}
                  {/if}
                </td>
              </tr>
            {/if}
          {:else if row.kind === 'changed'}
            {#if editId === row.live.id}
              <tr class="row-editing">
                <td colspan="3">
                  <div class="edit-row-layout">
                    <input class="qty-input" bind:value={editQty}
                      onkeydown={(e) => editKeydown(e, () => saveEdit(row.live.id), cancelEdit)} />
                    <UnitsSelect bind:value={editUnits} />
                    <input class="desc-input-inline" bind:value={editDescription}
                      onkeydown={(e) => editKeydown(e, () => saveEdit(row.live.id), cancelEdit)} />
                    <button type="button" onclick={() => saveEdit(row.live.id)} disabled={saving}>Save</button>
                    <button type="button" onclick={cancelEdit} disabled={saving}>Cancel</button>
                  </div>
                  <FieldError errors={editFields} field="qty_ordered" />
                  <FieldError errors={editFields} field="units" />
                  <FieldError errors={editFields} field="description" />
                  <FormMessage error={editError} />
                </td>
              </tr>
            {:else}
              <tr class="row-changed">
                <td class="num">{fmtQty(row.qty)} {row.units}</td>
                <td>{row.description || '—'}</td>
                <td class="acts">
                  {#if canEdit}
                    {#if row.anchored}
                      <span class="anchored-note">shipped</span>
                    {:else}
                      <button type="button" onclick={() => openEdit(row.live)}>Edit</button>
                      <button type="button" onclick={() => undoChange(row.live.id, row.baseline)}>Undo</button>
                    {/if}
                  {/if}
                </td>
              </tr>
            {/if}
          {:else if row.kind === 'changed-orig'}
            <tr class="row-gone">
              <td class="num keep">{fmtQty(row.qty)} {row.units}</td>
              <td>{row.description || '—'}</td>
              <td></td>
            </tr>
          {:else if row.kind === 'removed'}
            <tr class="row-gone">
              <td class="num keep">{fmtQty(row.qty)} {row.units}</td>
              <td>{row.description || '—'}</td>
              <td class="acts keep">
                {#if canEdit}
                  <button type="button" onclick={() => undoRemove(row.baseline)}>Undo</button>
                {/if}
              </td>
            </tr>
          {:else if row.kind === 'added'}
            {#if editId === row.live.id}
              <tr class="row-editing">
                <td colspan="3">
                  <div class="edit-row-layout">
                    <input class="qty-input" bind:value={editQty}
                      onkeydown={(e) => editKeydown(e, () => saveEdit(row.live.id), cancelEdit)} />
                    <UnitsSelect bind:value={editUnits} />
                    <input class="desc-input-inline" bind:value={editDescription}
                      onkeydown={(e) => editKeydown(e, () => saveEdit(row.live.id), cancelEdit)} />
                    <button type="button" onclick={() => saveEdit(row.live.id)} disabled={saving}>Save</button>
                    <button type="button" onclick={cancelEdit} disabled={saving}>Cancel</button>
                  </div>
                  <FieldError errors={editFields} field="qty_ordered" />
                  <FieldError errors={editFields} field="units" />
                  <FieldError errors={editFields} field="description" />
                  <FormMessage error={editError} />
                </td>
              </tr>
            {:else}
              <tr class="row-added">
                <td class="num"><span class="added-tag">+</span>{fmtQty(row.qty)} {row.units}</td>
                <td>{row.description || '—'}</td>
                <td class="acts">
                  {#if canEdit}
                    {#if row.anchored}
                      <span class="anchored-note">shipped</span>
                    {:else}
                      <button type="button" onclick={() => openEdit(row.live)}>Edit</button>
                      <button type="button" onclick={() => deleteDeliverable(row.live.id)}>Delete</button>
                    {/if}
                  {/if}
                </td>
              </tr>
            {/if}
          {/if}
        {/each}
      {/if}
      {#if newOpen}
        <tr class="row-editing">
          <td colspan="3">
            <div class="edit-row-layout">
              <input class="qty-input" bind:value={newQty}
                onkeydown={(e) => editKeydown(e, saveNew, cancelNew)} />
              <UnitsSelect bind:value={newUnits} />
              <input class="desc-input-inline" bind:value={newDescription} placeholder="Description"
                onkeydown={(e) => editKeydown(e, saveNew, cancelNew)} />
              <button type="button" onclick={saveNew} disabled={saving}>Add</button>
              <button type="button" onclick={cancelNew} disabled={saving}>Cancel</button>
            </div>
            <FieldError errors={newFields} field="qty_ordered" />
            <FieldError errors={newFields} field="units" />
            <FieldError errors={newFields} field="description" />
            <FormMessage error={newError} />
          </td>
        </tr>
      {/if}
    </tbody>
  </table>
</section>

<style>
  /* Vertical rhythm only — no horizontal inset, so the diff table aligns to
     the .page-body gutter like the estimate panel's tables. */
  .section { padding: 16px 0; }
  .section-head {
    display: flex; align-items: center; gap: 12px; margin-bottom: 8px;
  }
  .section-head h3 { margin: 0; }
  .spacer { flex: 1; }

  /* ---- Merged diff table (this section's own dense idiom — the
     line-item side moved to COEditView's .data-table amended-agreement
     view 2026-08-09, so this is no longer shared with a sibling). ---- */
  .diff-table {
    width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 13px;
  }
  .diff-table td { padding: 6px 8px; vertical-align: middle; }
  .diff-table tbody tr { border-bottom: 1px solid #f3f4f6; }

  .diff-table .num { text-align: right; font-variant-numeric: tabular-nums; }
  .diff-table .acts { text-align: right; white-space: nowrap; }
  .diff-table .acts button { margin-left: 4px; }

  /* Row tints */
  .diff-table tr.row-changed { background: #fff7ed; }
  .diff-table tr.row-added   { background: #dcfce7; }
  .diff-table tr.row-gone td { color: #9ca3af; text-decoration: line-through; }
  .diff-table tr.row-gone td.keep { text-decoration: none; color: #9ca3af; }
  .diff-table tr.row-gone td.acts.keep { text-decoration: none; }

  .empty-msg { color: #888; font-size: 13px; padding: 8px 0; }

  /* Deliverables table — no line-number column; qty+units in first col */
  .deliv-table td.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .deliv-table .added-tag { color: #166534; font-weight: 600; margin-right: 4px; }

  /* Inline editing row — uses a flex layout spanning all columns */
  .diff-table tr.row-editing { background: #f0f9ff; }
  .diff-table tr.row-editing td { padding: 4px 8px; }

  /* Flex row: qty input | units select | description (grows) | action buttons */
  .edit-row-layout {
    display: flex; align-items: center; gap: 6px;
  }
  .qty-input { width: 3.5em; flex-shrink: 0; }
  .desc-input-inline { flex: 1; min-width: 0; box-sizing: border-box; }

  /* Anchored note */
  .anchored-note { font-size: 11px; color: #9ca3af; font-style: italic; }
</style>
