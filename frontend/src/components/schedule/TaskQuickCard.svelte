<script>
  import { onMount, onDestroy } from 'svelte';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import { currentBlep } from '../../stores/currentBlep.js';
  import TaskActions from '../tasks/TaskActions.svelte';
  import StartWorkConflictModal from '../tasks/StartWorkConflictModal.svelte';
  import AssignModal from '../AssignModal.svelte';

  let {
    bar,                 // schedule bar: task_id, name, status, accent_color, est_minutes, elapsed_minutes, is_running, job_id
    assigneeName = '',
    jobNumber = '',
    jobName = '',
    onClose = () => {},
    onChanged = () => {},
  } = $props();

  let task = $state(null);   // full task fetched from /api/tasks/{id}/
  let loading = $state(true);
  let error = $state('');
  let conflict = $state(null);
  let assignModalOpen = $state(false);

  const userPermissions = $derived($userStore?.permissions || []);
  const canManageJobs = $derived(userPermissions.includes('can_manage_jobs'));

  const activeBlepOnThisTask = $derived.by(() => {
    const cb = $currentBlep;
    if (!cb || !task) return null;
    return cb.task && cb.task.id === task.task_id ? cb : null;
  });

  const statusLabel = $derived(({
    pending: 'Pending', in_progress: 'In Progress', blocked: 'Blocked',
    complete: 'Complete', cancelled: 'Cancelled',
  })[bar.status] || bar.status);

  async function loadTask() {
    loading = true;
    error = '';
    try {
      task = await api.get(`/api/tasks/${bar.task_id}/`);
    } catch (e) {
      error = e.message || 'Could not load task.';
    } finally {
      loading = false;
    }
  }

  function handleActionChanged() {
    // Refresh local task state and let the schedule refetch.
    loadTask();
    onChanged();
  }

  function handleConflict(c) { conflict = c; }
  function handleResolved() { conflict = null; handleActionChanged(); }
  function handleCancelConflict() { conflict = null; }

  function onKeydown(e) {
    if (e.key === 'Escape') onClose();
  }

  function onOverlayClick(e) {
    if (e.target === e.currentTarget) onClose();
  }

  onMount(() => {
    loadTask();
    window.addEventListener('keydown', onKeydown);
  });
  onDestroy(() => window.removeEventListener('keydown', onKeydown));
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="overlay" onclick={onOverlayClick}>
  <div class="card">
    <div class="card-accent" style="background: {bar.accent_color || '#888'};"></div>
    <button class="close" onclick={onClose} title="Close" aria-label="Close">×</button>
    <div class="card-body">
      <div class="task-name">{bar.name}</div>
      <div class="job-line">
        {#if jobNumber}<a href="#/jobs/{bar.job_id}">{jobNumber}</a>{/if}
        {#if jobName} · {jobName}{/if}
      </div>

      <div class="meta-row">
        <span class="status-chip st-{bar.status}">{statusLabel}</span>
        <span class="meta">est {bar.est_minutes}m · elapsed {bar.elapsed_minutes}m</span>
      </div>
      {#if assigneeName}
        <div class="meta-row">
          <span class="assignee">Assignee: <strong>{assigneeName}</strong></span>
        </div>
      {/if}

      {#if bar.is_running}
        <div class="blep-banner">
          <span class="blep-dot"></span>
          {assigneeName || 'Worker'} working · {bar.elapsed_minutes}m logged
        </div>
      {/if}

      {#if error}
        <p class="error">{error}</p>
      {/if}

      {#if loading}
        <p class="loading">Loading…</p>
      {:else if task}
        <div class="section-label">Actions</div>
        <TaskActions
          {task}
          user={$userStore}
          {userPermissions}
          {activeBlepOnThisTask}
          onChanged={handleActionChanged}
          onConflict={handleConflict}
        />

        <div class="actions secondary">
          {#if canManageJobs}
            <button type="button" onclick={() => { assignModalOpen = true; }}>Reassign</button>
          {/if}
        </div>

        <div class="section-label">On behalf of {assigneeName || 'worker'} (coming soon)</div>
        <div class="actions onbehalf">
          <button type="button" disabled title="Follow-on work">Start for {assigneeName || 'worker'}</button>
          <button type="button" disabled title="Follow-on work">Stop {assigneeName || 'worker'}'s timer</button>
        </div>
      {/if}

      <div class="footer">
        <a href="#/jobs/{bar.job_id}/tasks/{bar.task_id}">Open full task page →</a>
      </div>
    </div>
  </div>
</div>

{#if task}
  <AssignModal
    open={assignModalOpen}
    {task}
    onSaved={() => { assignModalOpen = false; handleActionChanged(); }}
    onClose={() => { assignModalOpen = false; }}
  />
  <StartWorkConflictModal
    {conflict}
    taskId={task.task_id}
    onResolved={handleResolved}
    onCancel={handleCancelConflict}
  />
{/if}

<style>
  .overlay {
    position: fixed; inset: 0; z-index: 1000;
    background: rgba(0,0,0,0.35);
    display: flex; align-items: center; justify-content: center;
  }
  .card {
    position: relative; width: 360px; max-width: 92vw;
    background: #fff; border-radius: 10px; overflow: hidden;
    box-shadow: 0 12px 40px rgba(0,0,0,0.25);
    font-family: ui-sans-serif, system-ui, sans-serif;
  }
  .card-accent { height: 5px; }
  .close {
    position: absolute; top: 8px; right: 8px;
    width: 26px; height: 26px; border: none; background: none;
    font-size: 22px; line-height: 1; color: #9ca3af; cursor: pointer;
    border-radius: 4px;
  }
  .close:hover { background: #f3f4f6; color: #374151; }
  .card-body { padding: 16px; }
  .task-name { font-size: 15px; font-weight: 700; color: #1f2937; line-height: 1.25; padding-right: 24px; }
  .job-line { font-size: 12px; color: #6b7280; margin-top: 2px; }
  .job-line a { color: #2563eb; text-decoration: none; }
  .meta-row { display: flex; gap: 8px; align-items: center; margin-top: 8px; flex-wrap: wrap; }
  .status-chip { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; text-transform: uppercase; letter-spacing: .03em; }
  .st-in_progress { background: #dbeafe; color: #1d4ed8; }
  .st-pending { background: #f3f4f6; color: #4b5563; }
  .st-blocked { background: #fee2e2; color: #b91c1c; }
  .st-complete { background: #dcfce7; color: #166534; }
  .st-cancelled { background: #f3f4f6; color: #9ca3af; }
  .meta { font-size: 12px; color: #4b5563; }
  .assignee { font-size: 12px; color: #374151; }
  .blep-banner {
    margin-top: 10px; padding: 7px 9px; border-radius: 6px; font-size: 12px;
    background: #ecfdf5; color: #065f46; display: flex; align-items: center; gap: 6px;
  }
  .blep-dot { width: 8px; height: 8px; border-radius: 50%; background: #10b981; }
  .section-label { font-size: 10px; text-transform: uppercase; letter-spacing: .05em; color: #9ca3af; margin: 14px 0 6px; }
  .actions { display: flex; flex-wrap: wrap; gap: 6px; }
  .actions.secondary { margin-top: 8px; }
  .actions button { font-size: 12px; padding: 6px 10px; border-radius: 6px; border: 1px solid #d1d5db; background: #fff; color: #1f2937; cursor: pointer; }
  .actions.onbehalf button { color: #9ca3af; cursor: not-allowed; border-style: dashed; }
  .footer { border-top: 1px solid #eee; margin-top: 14px; padding-top: 10px; }
  .footer a { font-size: 12px; color: #2563eb; text-decoration: none; font-weight: 600; }
  .error { color: #b91c1c; font-size: 12px; margin-top: 8px; }
  .loading { color: #6b7280; font-size: 12px; margin-top: 10px; }
</style>
