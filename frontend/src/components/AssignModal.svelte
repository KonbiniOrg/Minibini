<script>
  import { api } from '../lib/api.js';
  import { triageError } from '../lib/errorTriage.js';
  import { showError } from '../stores/messages.js';
  import { parseDurationToISO } from '../lib/format.js';
  import Modal from './Modal.svelte';
  import FieldError from './FieldError.svelte';
  import FormMessage from './FormMessage.svelte';

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
  let formError = $state('');
  let fieldErrs = $state({});

  // A task with no estimated worker time can't be scheduled, so assigning
  // it requires the duration up front. Unassigning never does.
  const needsWorkerTime = $derived(!task?.est_worker_time);
  const isAssigning = $derived(!!selectedUserId);

  $effect(() => {
    if (open) {
      selectedUserId = task?.assignee ?? '';
      estWorkerTime = '';
      formError = '';
      fieldErrs = {};
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
    formError = '';
    fieldErrs = {};
    const body = { assignee: selectedUserId || null, worker_queue: null };

    if (isAssigning && needsWorkerTime) {
      const iso = parseDurationToISO(estWorkerTime);
      if (iso === null) {
        fieldErrs = { est_worker_time: ['Estimated worker time is required to assign this task.'] };
        return;
      }
      if (iso === false) {
        fieldErrs = { est_worker_time: [`Could not read "${estWorkerTime}" as a duration. `
          + 'Use HH:MM (e.g. 1:30) or decimal hours (e.g. 1.5).'] };
        return;
      }
      if (iso === 'PT0H0M') {
        fieldErrs = { est_worker_time: ['Estimated worker time must be greater than zero.'] };
        return;
      }
      body.est_worker_time = iso;
    }

    busy = true;
    try {
      const resp = await api.post(`/api/tasks/${task.task_id}/assign/`, body);
      if (resp && resp.needs_worker_time) {
        // The duration field may not even be rendered in this state, so the
        // form footer is the safe venue.
        formError = 'Estimated worker time is required to assign this task.';
        return;
      }
      onSaved();
    } catch (e) {
      const t = triageError(e);
      if (t.overlay) {
        showError(t.overlay);
      } else {
        formError = t.message;
        fieldErrs = t.fields;
      }
    } finally {
      busy = false;
    }
  }
</script>

<Modal {open} onCancel={onClose} maxWidth="600px">
<form onsubmit={(e) => { e.preventDefault(); if (!busy) save(); }}>
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
        <FieldError errors={fieldErrs} field="assignee" />
      </p>

      {#if needsWorkerTime && isAssigning}
        <p>
          <label><strong>Estimated worker time *</strong><br>
            <input type="text" bind:value={estWorkerTime} placeholder="e.g. 1:30 or 1.5">
          </label>
          <FieldError errors={fieldErrs} field="est_worker_time" /><br>
          <small>HH:MM or decimal hours.</small>
        </p>
      {/if}

      <div class="buttons">
        <button type="submit" disabled={busy}>Save</button>
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      <FormMessage error={formError} />
</form>
</Modal>

<style>
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
</style>
