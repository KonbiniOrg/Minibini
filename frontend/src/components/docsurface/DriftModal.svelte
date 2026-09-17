<script>
  // The explanatory Revert dialog behind an AtomChildRow drift badge
  // (per-unit-lines spec §8). A per-unit claim snapshots `per_unit_qty`
  // (and, for a task, optionally `per_unit_worker_time`) when it's stamped;
  // the atom's live value can drift away from that agreement afterwards (a
  // hand edit in the task pane, a CO re-quantifying the line). This modal
  // is the ONLY path to reverting it — the badge itself never mutates.
  //
  // Deliberately not one-click (RM 2026-09-16): drift is an unfamiliar
  // concept and a restamp overwrites the atom's current value, so the
  // modal spells out the agreement expectation (with the actual numbers),
  // the atom's current value, and one sentence on where each comes from,
  // before Revert is offered. No nested confirm() on top of that — the
  // modal itself IS the deliberate step (UI convention: only irreversible/
  // arduous actions get a confirmation prompt on top of their own gesture).
  //
  // Self-contained like BundleModal/AdjustmentModal: owns its own POST to
  // `${apiBase}/restamp-atom/` with {source_id}. `apiBase` is the same
  // estimate/CO-scoped base the caller already threads through to
  // BundleModal (e.g. `/api/estimates/7` or `/api/change-orders/12`).
  import { api } from '../../lib/api.js';
  import { triageError } from '../../lib/errorTriage.js';
  import { formatQtyUnits, formatDuration } from '../../lib/format.js';
  import Modal from '../Modal.svelte';
  import FormMessage from '../FormMessage.svelte';

  let {
    open = false,
    // The drift-bearing atom: {kind, description, qty_display, source_id,
    // per_unit_qty, expected_total, units, drift, expected_worker_time?}
    // — the same shape AtomChildRow's `atom` prop carries, once a caller
    // spreads a per-unit claim's serialized fields onto it.
    atom = null,
    lineQty = null,   // the backing line's current qty (the multiplier)
    apiBase = '',     // e.g. '/api/estimates/7' or '/api/change-orders/12'
    onReverted = () => {}, // called after a successful revert — the caller
                           // refreshes its data and closes the modal.
    onClose = () => {},
  } = $props();

  let busy = $state(false);
  let formError = $state('');

  $effect(() => {
    if (open) formError = '';
  });

  // Never say "atom" in user-facing text (project convention) — name the
  // task/material, falling back to a generic "this task"/"this material"
  // if a description is somehow missing.
  let subjectLabel = $derived(atom?.kind === 'material' ? 'this material' : 'this task');
  let subjectName = $derived(atom?.description || subjectLabel);

  async function revert() {
    if (!atom || busy) return;
    busy = true;
    formError = '';
    try {
      await api.post(`${apiBase}/restamp-atom/`, { source_id: atom.source_id });
      onReverted();
    } catch (e) {
      const t = triageError(e);
      formError = t.overlay || t.message || 'Could not revert to the agreement.';
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open} onSave={revert} onCancel={onClose} {busy} label="Agreement drift" maxWidth="560px">
  {#if atom}
    <h3>{subjectName} does not match the agreement</h3>
    <p>
      Agreement: {formatQtyUnits(atom.per_unit_qty, atom.units)} per unit &times;
      {lineQty} units = {formatQtyUnits(atom.expected_total, atom.units)}.
      This comes from the per-unit quantity recorded when this line was set up,
      multiplied by the line's current quantity.
    </p>
    <p>
      Currently on {subjectName}: {atom.qty_display}.
      This is what's live on {subjectLabel}'s own record — it may have been
      edited directly, or the two diverged after a change order changed the
      line's quantity.
    </p>
    {#if atom.expected_worker_time}
      <p>
        The agreement also expects a scheduled time of
        {formatDuration(atom.expected_worker_time)} for this quantity.
      </p>
    {/if}
    {#if atom.kind === 'material'}
      <p>
        This is a physical material — reverting changes the planned quantity
        but does not undo purchasing or stock decisions.
      </p>
    {/if}
    <div class="buttons">
      <button type="button" onclick={revert} disabled={busy}>Revert to agreement</button>
      <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
    </div>
    <FormMessage error={formError} />
  {/if}
</Modal>

<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
</style>
