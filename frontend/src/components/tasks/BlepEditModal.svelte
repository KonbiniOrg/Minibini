<script>
  import { api } from '../../lib/api.js';
  import { notifyBlepChanged } from '../../stores/blepActivity.js';
  import { modalKeys } from '../../lib/modalKeys.js';

  let {
    open = false,
    mode = 'edit', // 'edit' | 'create'
    blep = null,   // when mode='edit'
    taskId = null, // when mode='create'
    currentUser,
    userPermissions = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  const canManageTime = $derived(userPermissions.includes('can_manage_time'));

  let startTime = $state('');
  let endTime = $state('');
  let targetUserId = $state('');
  let users = $state([]);
  let busy = $state(false);
  let error = $state('');

  async function loadUsers() {
    try {
      users = await api.get('/api/auth/users/');
    } catch (e) {
      users = [];
    }
  }

  function isoToLocal(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
      + `T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function localToIso(local) {
    if (!local) return null;
    return new Date(local).toISOString();
  }

  $effect(() => {
    if (open) {
      if (mode === 'edit' && blep) {
        startTime = isoToLocal(blep.start_time);
        endTime = isoToLocal(blep.end_time);
        targetUserId = String(blep.user ?? '');
      } else {
        startTime = '';
        endTime = '';
        targetUserId = String(currentUser?.id ?? '');
      }
      error = '';
      if (canManageTime) loadUsers();
    }
  });

  async function save() {
    busy = true;
    error = '';
    try {
      if (mode === 'edit') {
        const payload = {
          start_time: localToIso(startTime),
          end_time: localToIso(endTime),
        };
        if (canManageTime && targetUserId) payload.user = Number(targetUserId);
        await api.patch(`/api/bleps/${blep.blep_id}/`, payload);
      } else {
        const payload = {
          task: taskId,
          start_time: localToIso(startTime),
          end_time: localToIso(endTime),
        };
        if (canManageTime && targetUserId) payload.user = Number(targetUserId);
        await api.post('/api/bleps/', payload);
      }
      await notifyBlepChanged();
      onSaved();
    } catch (e) {
      error = e.message || 'Could not save.';
    } finally {
      busy = false;
    }
  }

  async function remove() {
    if (!blep) return;
    if (!confirm('Delete this time entry?')) return;
    busy = true;
    error = '';
    try {
      await api.delete(`/api/bleps/${blep.blep_id}/`);
      await notifyBlepChanged();
      onSaved();
    } catch (e) {
      error = e.message || 'Could not delete.';
    } finally {
      busy = false;
    }
  }
</script>

{#if open}
  <div class="overlay" use:modalKeys={{ onSave: () => { if (!busy) save(); }, onCancel: onClose }}>
    <div class="modal">
      <h3>{mode === 'edit' ? 'Edit time entry' : 'Add time entry'}</h3>
      <p>
        <label><strong>Start</strong><br>
          <input type="datetime-local" bind:value={startTime}>
        </label>
      </p>
      <p>
        <label><strong>End</strong><br>
          <input type="datetime-local" bind:value={endTime}>
        </label>
      </p>
      {#if canManageTime}
        <p>
          <label><strong>User (manager only)</strong><br>
            <select bind:value={targetUserId}>
              <option value="">-- Select user --</option>
              {#each users as u}
                <option value={String(u.id)}>{u.name} ({u.username})</option>
              {/each}
            </select>
          </label>
        </p>
      {/if}
      <div class="buttons">
        <button type="button" onclick={save} disabled={busy}>Save</button>
        {#if mode === 'edit'}
          <button type="button" onclick={remove} disabled={busy}>Delete</button>
        {/if}
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; background: rgba(0,0,0,0.4);
    display: flex; align-items: center; justify-content: center; z-index: 1100;
  }
  .modal { background: white; padding: 16px; max-width: 440px; border: 1px solid #ccc; }
  .buttons { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }
  .error { color: #a8071a; }
</style>
