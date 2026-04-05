<script>
  import { api } from '../../lib/api.js';

  let {
    conflict = null,
    taskId,
    onResolved = () => {},
    onCancel = () => {},
  } = $props();

  let busy = $state(false);
  let error = $state('');

  async function resolve(action) {
    busy = true;
    error = '';
    try {
      await api.post(`/api/tasks/${taskId}/start-work/`, { action });
      onResolved();
    } catch (e) {
      error = e.message || 'Could not resolve conflict.';
    } finally {
      busy = false;
    }
  }
</script>

{#if conflict}
  <div class="overlay">
    <div class="modal">
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
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center; z-index: 200;
  }
  .modal {
    background: white; padding: 16px; max-width: 440px;
    border: 1px solid #ccc;
  }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
