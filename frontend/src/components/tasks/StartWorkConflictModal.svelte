<script>
  import { api } from '../../lib/api.js';
  import { notifyBlepChanged } from '../../stores/blepActivity.js';
  import Modal from '../Modal.svelte';

  let {
    conflict = null,
    taskId,
    onBehalfOf = null,   // user id when resolving a conflict on a worker's behalf
    onResolved = () => {},
    onCancel = () => {},
  } = $props();

  let busy = $state(false);
  let error = $state('');

  async function resolve(action) {
    busy = true;
    error = '';
    try {
      const body = { action };
      if (onBehalfOf) body.on_behalf_of = onBehalfOf;
      await api.post(`/api/tasks/${taskId}/start-work/`, body);
      await notifyBlepChanged();
      onResolved();
    } catch (e) {
      error = e.message || 'Could not resolve conflict.';
    } finally {
      busy = false;
    }
  }
</script>

<!-- Esc-only: Join vs Take over is an ambiguous, irreversible choice — don't bind Enter. -->
<Modal open={conflict} onCancel={onCancel} maxWidth="660px">
      <h3>Someone is already working on this task</h3>
      <p>
        <strong>{conflict.worker?.name}</strong> is currently working on this
        task (started at {new Date(conflict.started_at).toLocaleString()}).
      </p>
      <p>What do you want to do?</p>
      <div class="buttons">
        <button type="button" onclick={() => resolve('join')} disabled={busy}>
          Join (we work together)
        </button>
        <button type="button" onclick={() => resolve('takeover')} disabled={busy}>
          Take over (stop their timer)
        </button>
        <button type="button" onclick={onCancel} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
</Modal>


<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
