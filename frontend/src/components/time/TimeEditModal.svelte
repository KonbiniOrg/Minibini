<script>
  import { api } from '../../lib/api.js';
  import { modalKeys } from '../../lib/modalKeys.js';
  import { notifyBlepChanged } from '../../stores/blepActivity.js';
  import { notifyShiftChanged } from '../../stores/shift.js';

  let {
    open = false,
    recordType = 'blep',          // 'blep' | 'shift'
    action = 'edit',              // 'edit' | 'create' | 'request'
    record = null,                // existing record when editing/requesting-amend
    taskId = null,                // blep create/request needs a task
    currentUser,
    userPermissions = [],
    onSaved = () => {},
    onClose = () => {},
  } = $props();

  const canManageTime = $derived(userPermissions.includes('can_manage_time'));

  let startTime = $state('');
  let endTime = $state('');
  let reason = $state('');
  let targetUserId = $state('');
  let users = $state([]);
  let busy = $state(false);
  let error = $state('');
  let conflictMsg = $state('');     // soft conflict text

  function isoToLocal(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  function localToIso(local) { return local ? new Date(local).toISOString() : null; }

  async function loadUsers() {
    try { users = await api.get('/api/auth/users/'); } catch { users = []; }
  }

  $effect(() => {
    if (open) {
      startTime = record ? isoToLocal(record.start_time) : '';
      endTime = record ? isoToLocal(record.end_time) : '';
      reason = '';
      conflictMsg = '';
      error = '';
      const rid = record?.user;
      targetUserId = String(rid ?? currentUser?.id ?? '');
      if (canManageTime) loadUsers();
    }
  });

  // Soft conflict detection against the counterpart records.
  async function checkConflict() {
    conflictMsg = '';
    const s = localToIso(startTime), e = localToIso(endTime);
    if (!s || !e) return;
    const uid = targetUserId || currentUser?.id;
    try {
      if (recordType === 'shift') {
        const resp = await api.get(`/api/bleps/?user=${uid}&since=${encodeURIComponent(s)}`);
        const bleps = resp.results || resp;
        const bad = bleps.filter(b => b.end_time &&
          !(new Date(s) <= new Date(b.start_time) && new Date(b.end_time) <= new Date(e)) &&
          (new Date(b.start_time) < new Date(e) && new Date(b.end_time) > new Date(s)));
        if (bad.length) {
          const names = bad.map(b => b.task_name).join(', ');
          conflictMsg = action === 'request'
            ? `Heads up: this shift wouldn't cover your blep(s) on ${names} — your manager will reconcile that when reviewing the request.`
            : `This shift would not cover blep(s) on ${names}.`;
        }
      } else {
        const resp = await api.get(`/api/shifts/?user=${uid}&since=${encodeURIComponent(
          new Date(new Date(s).getTime() - 86400000).toISOString())}`);
        const shifts = (resp.results || resp).filter(sh => sh.end_time);
        const enclosed = shifts.some(sh =>
          new Date(sh.start_time) <= new Date(s) && new Date(e) <= new Date(sh.end_time));
        if (!enclosed) conflictMsg = action === 'request'
          ? "Heads up: this time isn't covered by one of your shifts — your manager will adjust the shift when reviewing the request."
          : 'No shift covers this time — widen the enclosing shift first.';
      }
    } catch { /* soft check only */ }
  }

  const blocked = $derived(action !== 'request' && !!conflictMsg);

  async function save() {
    busy = true; error = '';
    const payload = { start_time: localToIso(startTime), end_time: localToIso(endTime) };
    if (canManageTime && targetUserId) payload.user = Number(targetUserId);
    try {
      if (action === 'request') {
        // Change-request API expects requested_start / requested_end (not the
        // start_time/end_time the direct blep/shift edit endpoints use).
        const reqPayload = {
          requested_start: localToIso(startTime),
          requested_end: localToIso(endTime),
          reason,
        };
        if (recordType === 'shift') {
          if (record) reqPayload.shift = record.shift_id;
          await api.post('/api/shift-change-requests/', reqPayload);
        } else {
          reqPayload.task = record ? record.task : taskId;
          if (record) reqPayload.blep = record.blep_id;
          await api.post('/api/blep-change-requests/', reqPayload);
        }
      } else if (recordType === 'shift') {
        if (action === 'edit') await api.patch(`/api/shifts/${record.shift_id}/`, payload);
        else await api.post('/api/shifts/', payload);
      } else {
        if (action === 'edit') await api.patch(`/api/bleps/${record.blep_id}/`, payload);
        else { payload.task = taskId; await api.post('/api/bleps/', payload); }
      }
      if (recordType === 'shift') await notifyShiftChanged(); else await notifyBlepChanged();
      onSaved();
    } catch (e) {
      error = e.message || 'Could not save.';
    } finally { busy = false; }
  }

  async function remove() {
    if (!record) return;
    // Deletion is irreversible — confirm (per app UI convention).
    if (!confirm(recordType === 'shift' ? 'Delete this shift?' : 'Delete this time entry?')) return;
    busy = true; error = '';
    try {
      if (recordType === 'shift') {
        await api.delete(`/api/shifts/${record.shift_id}/`);
        await notifyShiftChanged();
      } else {
        await api.delete(`/api/bleps/${record.blep_id}/`);
        await notifyBlepChanged();
      }
      onSaved();
    } catch (e) {
      error = e.message || 'Could not delete.';
    } finally { busy = false; }
  }
</script>

{#if open}
  <div class="overlay" use:modalKeys={{ onSave: () => { if (!busy && !blocked) save(); }, onCancel: onClose }}>
    <div class="modal">
      <h3>{action === 'request' ? 'Request change' : action === 'create' ? 'Add' : 'Edit'}
          {recordType === 'shift' ? 'shift' : 'time entry'}</h3>
      <p><label><strong>Start</strong><br>
        <input type="datetime-local" bind:value={startTime} onblur={checkConflict}></label></p>
      <p><label><strong>End</strong><br>
        <input type="datetime-local" bind:value={endTime} onblur={checkConflict}></label></p>

      {#if action === 'request'}
        <p><label><strong>Reason *</strong><br>
          <textarea bind:value={reason} required></textarea></label></p>
      {/if}

      {#if canManageTime && action !== 'request'}
        <p><label><strong>User (manager only)</strong><br>
          <select bind:value={targetUserId}>
            <option value="">-- Select user --</option>
            {#each users as u}<option value={String(u.id)}>{u.name} ({u.username})</option>{/each}
          </select></label></p>
      {/if}

      {#if conflictMsg}
        <p class={blocked ? 'error' : 'warn'}>{conflictMsg}
          {#if blocked}<br><em>Fix the conflicting record first, then save.</em>{/if}</p>
      {/if}

      <div class="buttons">
        <button type="button" onclick={save} disabled={busy || blocked || (action === 'request' && !reason.trim())}>
          {action === 'request' ? 'Submit request' : 'Save'}
        </button>
        {#if action === 'edit' && record}
          <button type="button" onclick={remove} disabled={busy}>Delete</button>
        {/if}
        <button type="button" onclick={onClose} disabled={busy}>Cancel</button>
      </div>
      {#if error}<p class="error">{error}</p>{/if}
    </div>
  </div>
{/if}

<style>
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex;
             align-items: center; justify-content: center; z-index: 200; }
  .modal { background: white; padding: 1.5em; border: 2px solid #333; max-width: 420px; width: 90%; }
  .buttons { display: flex; gap: 0.5em; margin-top: 1em; }
  .error { color: #b91c1c; }
  .warn { color: #b45309; }
  textarea { width: 100%; min-height: 3em; }
</style>
