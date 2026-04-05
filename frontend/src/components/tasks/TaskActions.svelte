<script>
  import { api } from '../../lib/api.js';

  let {
    task,
    user,
    userPermissions = [],
    activeBlepOnThisTask = null,
    onChanged = () => {},
    onConflict = () => {},
  } = $props();

  let busy = $state(false);
  let error = $state('');

  const isManager = $derived(userPermissions.includes('can_manage_jobs'));

  // Visibility per status (see design doc § Action visibility)
  const show = $derived.by(() => {
    const status = task?.status;
    const isActiveHere = activeBlepOnThisTask !== null;
    const base = {
      startWork: false, stopWork: false, complete: false,
      block: false, unblock: false, cancel: false,
    };
    if (status === 'pending' || status === 'in_progress') {
      base.startWork = !isActiveHere;
      base.stopWork = isActiveHere;
      base.complete = true;
      base.block = true;
      base.cancel = isManager;
    } else if (status === 'blocked') {
      base.unblock = true;
      base.cancel = isManager;
    }
    return base;
  });

  async function call(url, body = {}) {
    busy = true;
    error = '';
    try {
      const resp = await api.post(url, body);
      if (resp && resp.conflict) {
        onConflict(resp);
      } else {
        onChanged();
      }
    } catch (e) {
      error = e.message || 'Action failed.';
    } finally {
      busy = false;
    }
  }

  const startWork = () => call(`/api/tasks/${task.task_id}/start-work/`);
  const stopWork = () => call(`/api/tasks/${task.task_id}/stop-work/`);
  const complete = () => call(`/api/tasks/${task.task_id}/complete/`);
  const block = () => {
    const reason = prompt('Reason for blocking?');
    if (reason) call(`/api/tasks/${task.task_id}/block/`, { reason });
  };
  const unblock = () => call(`/api/tasks/${task.task_id}/unblock/`);
  const cancel = () => {
    if (confirm('Cancel this task?')) call(`/api/tasks/${task.task_id}/cancel/`);
  };
</script>

<div class="actions">
  {#if show.startWork}<button type="button" onclick={startWork} disabled={busy}>Start Work</button>{/if}
  {#if show.stopWork}<button type="button" onclick={stopWork} disabled={busy}>Stop Work</button>{/if}
  {#if show.complete}<button type="button" onclick={complete} disabled={busy}>Complete</button>{/if}
  {#if show.block}<button type="button" onclick={block} disabled={busy}>Block</button>{/if}
  {#if show.unblock}<button type="button" onclick={unblock} disabled={busy}>Unblock</button>{/if}
  {#if show.cancel}<button type="button" onclick={cancel} disabled={busy}>Cancel</button>{/if}
</div>
{#if error}<p class="error">{error}</p>{/if}

<style>
  .actions { display: flex; gap: 8px; margin: 8px 0; flex-wrap: wrap; }
  .error { color: #a8071a; }
</style>
