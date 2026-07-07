<script>
  import Modal from '../Modal.svelte';

  // Quantity entry for ENTERED_QTY tasks. Every write is an ADD — no
  // surface ever asks the user to compute a total. Two modes:
  //
  // - 'complete': settle-up at task completion. Shows the running total,
  //   asks "any more to add?" (empty = 0, negative = last-moment
  //   correction); the final total must be positive. Submits the
  //   increment with completesTask: true.
  // - 'session': "how many did this session produce?" after a stop, or
  //   for the prior open session when switching tasks / clocking out
  //   (priorTaskName names the old task; empty submit = explicit skip).
  //   With allowComplete, a "This completes the task" checkbox turns the
  //   submit into a single add-and-complete gesture (empty allowed).
  //
  // Pure input collector — the caller owns the API calls via
  // onSubmit(qty, {completesTask}); qty is null for an empty input.
  let {
    mode = 'complete',
    unitLabel = '',
    currentQty = null,
    priorTaskName = '',
    allowComplete = false,
    serverError = '',
    onSubmit,
    onClose,
  } = $props();

  let value = $state('');
  let completes = $state(false);
  let error = $state('');

  const unit = $derived(unitLabel || 'units');
  const current = $derived(currentQty == null ? 0 : parseFloat(currentQty));
  const entered = $derived(value === '' ? null : parseFloat(value));
  const finalTotal = $derived(current + (entered ?? 0));
  const settling = $derived(mode === 'complete' || completes);
  const submitLabel = $derived(
    mode === 'complete' ? 'Complete task'
    : completes ? 'Add & complete' : 'Add'
  );

  function fmt(n) {
    return Number.isFinite(n) ? String(parseFloat(n.toFixed(2))) : '?';
  }

  function submit() {
    error = '';
    if (entered !== null && !Number.isFinite(entered)) {
      error = 'Enter a number.';
      return;
    }
    if (settling) {
      // The resulting total is what gets billed — it must be positive.
      if (!(finalTotal > 0)) {
        error = 'Final quantity must be greater than 0.';
        return;
      }
    } else if (priorTaskName) {
      // Switch/clock-out context: empty is an explicit skip; a typed
      // session count must be positive.
      if (entered !== null && !(entered > 0)) {
        error = 'Enter a quantity greater than 0 (or leave empty to skip).';
        return;
      }
    } else {
      // Plain stop-session add: a session's production is positive.
      if (!(entered > 0)) {
        error = 'Enter a quantity greater than 0.';
        return;
      }
    }
    // Complete mode has no "skip" concept — an empty input IS a zero
    // increment. Session mode keeps null so callers can tell "no entry"
    // (skip the add / complete with 0) from a typed count.
    onSubmit(mode === 'complete' && entered === null ? 0 : entered,
             { completesTask: settling });
  }
</script>

<Modal open={true} onCancel={onClose} maxWidth="570px">
<form onsubmit={(e) => { e.preventDefault(); submit(); }}>
  {#if mode === 'complete'}
    <h3>Settle up quantity</h3>
    <p>
      Entered so far: <strong>{currentQty == null ? 0 : currentQty} {unit}</strong>.
      Any more to add?
    </p>
  {:else}
    <h3>Quantity this session</h3>
    {#if priorTaskName}
      <p>
        Your open session on <strong>{priorTaskName}</strong> — how many
        <strong>{unit}</strong> did it produce? (Leave empty to skip — you
        can settle the total when the task is completed.)
      </p>
    {:else}
      <p>
        How many <strong>{unit}</strong> did this session produce?
        (Cancel to skip — you can settle the total when the task is
        completed.)
      </p>
    {/if}
  {/if}
  <p>
    <label>
      <strong>Quantity ({unit})</strong><br>
      <input type="number" step="any" bind:value>
    </label>
  </p>
  {#if mode === 'session' && allowComplete}
    <p>
      <label>
        <input type="checkbox" bind:checked={completes}>
        This completes the task
      </label>
    </p>
  {/if}
  {#if settling}
    <p class="final-total">Final quantity: {fmt(finalTotal)} {unit}</p>
  {/if}
  {#if error || serverError}<p class="error">{error || serverError}</p>{/if}
  <div class="buttons">
    <button type="submit">{submitLabel}</button>
    <button type="button" onclick={onClose}>Cancel</button>
  </div>
</form>
</Modal>

<style>
  .buttons { display: flex; gap: 8px; margin-top: 12px; }
  .error { color: #a8071a; }
  .final-total { font-weight: 600; }
</style>
