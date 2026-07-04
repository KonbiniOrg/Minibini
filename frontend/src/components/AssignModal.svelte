<script>
  import { api } from '../lib/api.js';
  import { parseDurationToISO } from '../lib/format.js';
  import Modal from './Modal.svelte';

  let {
    open = false,
    task = null,
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  let users = $state([]);
  let selectedUserId = $state('');
  let estWorkerTime = $state('');
  let busy = $state(false);
  let error = $state('');

  // A task with no estimated worker time can't be scheduled, so assigning
  // it requires the duration up front. Unassigning never does.
  const needsWorkerTime = $derived(!task?.est_worker_time);
  const isAssigning = $derived(!!selectedUserId);

  $effect(() => {
    if (open) {
      selectedUserId = task?.assignee ?? '';
      estWorkerTime = '';
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
    error = '';
    const body = { assignee: selectedUserId || null, worker_queue: null };

    if (isAssigning && needsWorkerTime) {
      const iso = parseDurationToISO(estWorkerTime);
      if (iso === null) {
        error = 'Estimated worker time is required to assign this task.';
        return;
      }
      if (iso === false) {
        error = `Could not read "${estWorkerTime}" as a duration. `
          + 'Use HH:MM (e.g. 1:30) or decimal hours (e.g. 1.5).';
        return;
      }
      if (iso === 'PT0H0M') {
        error = 'Estimated worker time must be greater than zero.';
        return;
      }
      body.est_worker_time = iso;
    }

    busy = true;
    try {
      const resp = await api.post(`/api/tasks/${task.task_id}/assign/`, body);
      if (resp && resp.needs_worker_time) {
        error = 'Estimated worker time is required to assign this task.';
        return;
      }
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

<Modal {open} onSave={() => { if (!busy) save(); }} onCancel={onClose} maxWidth="600px">
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

      {#if needsWorkerTime && isAssigning}
        <p>
          <label><strong>Estimated worker time *</strong><br>
            <input type="text" bind:value={estWorkerTime} placeholder="e.g. 1:30 or 1.5">
          </label><br>
          <small>HH:MM or decimal hours.</small>
        </p>
      {/if}

      <div class="buttons">
        <button type="button" onclick={save} disabled={busy}>Save</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
</Modal>

<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
