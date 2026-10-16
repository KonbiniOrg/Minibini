<script>
  import { parseDurationToISO, formatQtyUnits } from '../../lib/format.js';
  import Modal from '../Modal.svelte';

  // Interrupting prompt shown when a task with no estimated worker time is
  // dragged onto a worker. Assigned work has to be schedulable, which needs
  // a duration. onSubmit receives an ISO 8601 duration string ("PT1H30M").
  // `task` is the board task dict (name, est_qty, unit_label), shown for
  // reference so the user can size the duration against the estimated qty.
  let {
    open = false,
    task = null,
    onSubmit = () => {},
    onCancel = () => {},
  } = $props();

  let value = $state('');
  let error = $state('');

  $effect(() => {
    if (open) { value = ''; error = ''; }
  });

  function submit() {
    const iso = parseDurationToISO(value);
    if (iso === null) {
      error = 'Enter an estimated duration to assign this task.';
      return;
    }
    if (iso === false) {
      error = 'Use HH:MM (e.g. 1:30) or decimal hours (e.g. 1.5).';
      return;
    }
    if (iso === 'PT0H0M') {
      error = 'Duration must be greater than zero.';
      return;
    }
    onSubmit(iso);
  }
</script>

<Modal {open} onCancel={onCancel} maxWidth="600px">
<form onsubmit={(e) => { e.preventDefault(); submit(); }}>
      <h3>Assign Task</h3>
      <p class="reference">
        <strong>Task</strong><br>
        <span>{task?.name ?? ''}</span>
      </p>
      <p class="reference">
        <strong>Estimated quantity</strong><br>
        <span>{formatQtyUnits(task?.est_qty, task?.unit_label)}</span>
      </p>
      <p>
        <label><strong>Estimated worker time *</strong><br>
          <input
            type="text" bind:value
            placeholder="e.g. 1:30 or 1.5">
        </label><br>
        <small>HH:MM or decimal hours.</small>
      </p>
      <div class="buttons">
        <button type="submit">Assign</button>
        <button type="button" onclick={onCancel}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
</form>
</Modal>


<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
  .reference { color: #555; }
</style>
