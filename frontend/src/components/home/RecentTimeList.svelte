<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import { blepActivityVersion } from '../../stores/blepActivity.js';
  import BlepEditModal from '../tasks/BlepEditModal.svelte';

  let bleps = $state([]);
  let loading = $state(true);
  let editingBlep = $state(null);
  let modalOpen = $state(false);

  const userPermissions = $derived($userStore?.permissions || []);
  const canManageTime = $derived(userPermissions.includes('can_manage_time'));

  function within24h(iso) {
    if (!iso) return false;
    return Date.now() - new Date(iso).getTime() < 24 * 60 * 60 * 1000;
  }

  function isEditable(blep) {
    if (canManageTime) return true;
    return blep.user === $userStore?.id && within24h(blep.start_time);
  }

  async function load() {
    loading = true;
    try {
      const since = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
      const resp = await api.get(`/api/bleps/?user=me&since=${encodeURIComponent(since)}`);
      bleps = resp.results || resp;
    } finally {
      loading = false;
    }
  }

  function openEdit(blep) {
    editingBlep = blep;
    modalOpen = true;
  }

  function requestEdit() {
    alert('Request Edit: not yet implemented.');
  }

  async function handleSaved() {
    modalOpen = false;
    editingBlep = null;
    await load();
  }

  function closeModal() {
    modalOpen = false;
    editingBlep = null;
  }

  function fmt(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString();
  }

  $effect(() => { load(); });

  // Refresh when any blep changes (Stop/Cancel/edit from anywhere).
  let lastBlepVersion = $state(0);
  $effect(() => {
    const v = $blepActivityVersion;
    if (v !== lastBlepVersion) {
      lastBlepVersion = v;
      load();
    }
  });
</script>

<section>
  <h3>Recent Time</h3>
  {#if loading}
    <p>Loading…</p>
  {:else if bleps.length === 0}
    <p>No recent time entries.</p>
  {:else}
    <table border="1">
      <thead>
        <tr>
          <th>Task</th><th>Job</th><th>Start</th><th>End</th><th></th>
        </tr>
      </thead>
      <tbody>
        {#each bleps as blep (blep.blep_id)}
          <tr>
            <td>
              {#if blep.job_id}
                <a href={`/jobs/${blep.job_id}/tasks/${blep.task}`} use:link>
                  {blep.task_name}
                </a>
              {:else}
                {blep.task_name}
              {/if}
            </td>
            <td>
              {#if blep.job_id}
                <a href={`/jobs/${blep.job_id}`} use:link>
                  {blep.job_number} {blep.job_name}
                </a>
              {/if}
            </td>
            <td>{fmt(blep.start_time)}</td>
            <td>{blep.end_time ? fmt(blep.end_time) : 'Active'}</td>
            <td>
              {#if isEditable(blep)}
                <button type="button" onclick={() => openEdit(blep)}>Edit</button>
              {:else}
                <button type="button" onclick={requestEdit}>Request Edit</button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<BlepEditModal
  open={modalOpen}
  mode="edit"
  blep={editingBlep}
  currentUser={$userStore}
  {userPermissions}
  onSaved={handleSaved}
  onClose={closeModal}
/>
