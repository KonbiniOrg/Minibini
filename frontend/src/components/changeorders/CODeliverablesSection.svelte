<script>
  // Deliverables diff editor for the change-order panel: renders the merged
  // rows (lib/changeOrderDiff.buildDeliverableRows) and owns one drafting
  // modal for edit/new (2026-10-10; the inline editing rows are gone,
  // matching the estimate side, whose DeliverablesEditModal is a modal).
  // Extracted from the old ChangeOrderDetailPage route (2026-07-19).
  import { api, errorMessage } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { showError } from '../../stores/messages.js';
  import FieldError from '../FieldError.svelte';
  import FormMessage from '../FormMessage.svelte';
  import UnitsSelect from '../UnitsSelect.svelte';
  import Modal from '../Modal.svelte';
  import { notifyDeliverablesChanged } from '../../stores/deliverables.js';

  let {
    jobId,            // deliverables are job-nested: /api/jobs/{jobId}/deliverables/
    rows = [],        // buildDeliverableRows output
    canEdit = false,  // canManageJobs && CO is draft
    onReload = () => {},
  } = $props();

  // One drafting modal for both edit and new. draft.id null → new.
  let draft = $state(null);   // { id, description, qty, units } | null
  let draftError = $state('');
  let draftFields = $state({});
  let saving = $state(false);

  function fmtQty(v) {
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v);
    return Number.isFinite(n) ? n.toString() : String(v);
  }

  function openEdit(liveRow) {
    draft = {
      id: liveRow.id,
      description: liveRow.description,
      qty: String(Number(liveRow.qty_ordered)),
      units: liveRow.units,
    };
    draftError = '';
    draftFields = {};
  }

  function openNew() {
    draft = { id: null, description: '', qty: '1', units: 'ea' };
    draftError = '';
    draftFields = {};
  }

  function cancelDraft() {
    draft = null;
    draftError = '';
    draftFields = {};
  }

  async function saveDraft() {
    draftError = '';
    draftFields = {};
    if (!draft.description.trim()) {
      draftFields = { description: ['Description is required.'] };
      return;
    }
    saving = true;
    // qty comes back from the number input as a Number; the API's decimal
    // field is happiest with the string form the old text inputs sent.
    const body = { description: draft.description, qty_ordered: String(draft.qty), units: draft.units };
    try {
      if (draft.id) await api.patch(`/api/jobs/${jobId}/deliverables/${draft.id}/`, body);
      else await api.post(`/api/jobs/${jobId}/deliverables/`, body);
      draft = null;
      notifyDeliverablesChanged();
      await onReload();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) showError(t.overlay);
      else { draftError = t.message; draftFields = t.fields; }
    } finally {
      saving = false;
    }
  }

  async function deleteDeliverable(liveId) {
    try {
      await api.delete(`/api/jobs/${jobId}/deliverables/${liveId}/`);
      notifyDeliverablesChanged();
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
      notifyDeliverablesChanged();
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
      notifyDeliverablesChanged();
      await onReload();
    } catch (e) {
      showError(errorMessage(e, 'Could not restore deliverable.'));
    }
  }

</script>

<section class="section" aria-labelledby="co-deliverables-title">
  <div class="section-head">
    <h3 id="co-deliverables-title">Deliverables</h3>
    <span class="spacer"></span>
    {#if canEdit}
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
      {#if rows.length === 0}
        <tr>
          <td colspan="3" class="empty-msg">No deliverables yet.</td>
        </tr>
      {:else}
        {#each rows as row}
          {#if row.kind === 'unchanged'}
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
          {:else if row.kind === 'changed'}
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
        {/each}
      {/if}
    </tbody>
  </table>
</section>


<!-- The drafting modal: Qty / Units / Description for both new and edit. -->
<Modal open={draft !== null} onCancel={cancelDraft} maxWidth="520px"
  label={draft?.id ? 'Edit deliverable' : 'New deliverable'}>
  {#if draft}
  <form onsubmit={(e) => { e.preventDefault(); if (!saving) saveDraft(); }}>
    <h3 class="modal-title">{draft.id ? 'Edit deliverable' : 'New deliverable'}</h3>
    <p>
      <label for="deliv-qty"><strong>Qty</strong></label><br>
      <input id="deliv-qty" type="number" step="any" min="0" bind:value={draft.qty} style="width:6em">
      <FieldError errors={draftFields} field="qty_ordered" />
    </p>
    <p>
      <label for="deliv-units"><strong>Units</strong></label><br>
      <UnitsSelect id="deliv-units" bind:value={draft.units} />
      <FieldError errors={draftFields} field="units" />
    </p>
    <p>
      <label for="deliv-desc"><strong>Description</strong></label><br>
      <input id="deliv-desc" type="text" bind:value={draft.description} placeholder="Description"
        style="width:100%;box-sizing:border-box">
      <FieldError errors={draftFields} field="description" />
    </p>
    <p>
      <button type="submit" disabled={saving}>{draft.id ? 'Save' : 'Add'}</button>
      <button type="button" onclick={cancelDraft} disabled={saving}>Cancel</button>
    </p>
    <FormMessage error={draftError} />
  </form>
  {/if}
</Modal>

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

  .modal-title { margin: 0 0 12px; font-size: 16px; }

  /* Anchored note */
  .anchored-note { font-size: 11px; color: #9ca3af; font-style: italic; }
</style>
