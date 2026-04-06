<script>
  import { api } from '../lib/api.js';

  let {
    open = false,
    task = null,
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let users = $state([]);
  let selectedUserId = $state('');
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    if (open) {
      selectedUserId = task?.assignee ?? '';
      error = '';
      loadUsers();
    }
  });

  async function loadUsers() {
    try {
      users = await api.get('/api/auth/users/');
    } catch (e) {
      users = [];
    }
  }

  async function save() {
    busy = true;
    error = '';
    try {
      await api.post(`/api/tasks/${task.task_id}/assign/`, {
        assignee: selectedUserId || null,
        worker_queue: null,
      });
      onSaved();
    } catch (e) {
      if (e.data && typeof e.data === 'object' && !e.data.detail) {
        error = Object.entries(e.data)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
          .join('; ');
      } else {
        error = e.message || 'Could not assign task.';
      }
    } finally {
      busy = false;
    }
  }
</script>

{#if open}
  <div class="overlay">
    <div class="modal">
      <h3>Assign Task: {task?.name}</h3>

      <p>
        <label><strong>Assignee</strong><br>
          <select bind:value={selectedUserId}>
            <option value="">-- Unassigned --</option>
            {#each users as u}
              <option value={u.id}>{u.name} ({u.username})</option>
            {/each}
          </select>
        </label>
      </p>

      <div class="buttons">
        <button type="button" onclick={save} disabled={busy}>Save</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
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
  .modal { background: white; padding: 16px; max-width: 400px; width: 90%; border: 1px solid #ccc; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
