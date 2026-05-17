<script>
  import { parseDurationToISO } from '../../lib/format.js';

  // Interrupting prompt shown when a task with no estimated worker time is
  // dragged onto a worker. Assigned work has to be schedulable, which needs
  // a duration. onSubmit receives an ISO 8601 duration string ("PT1H30M").
  let {
    open = false,
    taskName = '',
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

{#if open}
  <div class="overlay">
    <div class="modal">
      <h3>Estimated worker time</h3>
      <p>
        "{taskName}" has no time estimate. Assigned work has to be scheduled,
        so enter how long you expect it to take.
      </p>
      <p>
        <label><strong>Estimated worker time *</strong><br>
          <input
            type="text" bind:value
            placeholder="e.g. 1:30 or 1.5"
            onkeydown={(e) => { if (e.key === 'Enter') submit(); }}>
        </label><br>
        <small>HH:MM or decimal hours.</small>
      </p>
      <div class="buttons">
        <button type="button" onclick={submit}>Assign</button>
        <button type="button" onclick={onCancel}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center; z-index: 300;
  }
  .modal { background: white; padding: 16px; max-width: 400px; width: 90%; border: 1px solid #ccc; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
