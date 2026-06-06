<script>
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import { canManageTime as canManageTimeStore } from '../../stores/permissions.js';
  import { blepActivityVersion } from '../../stores/blepActivity.js';
  import TimeEditModal from '../time/TimeEditModal.svelte';
  import BlepLogTable from '../time/BlepLogTable.svelte';

  let bleps = $state([]);
  let loading = $state(true);
  let editingBlep = $state(null);
  let modalOpen = $state(false);
  let modalAction = $state('edit');

  const canManageTime = $derived($canManageTimeStore);

  function within30h(iso) {
    if (!iso) return false;
    return Date.now() - new Date(iso).getTime() < 30 * 60 * 60 * 1000;
  }

  function isEditable(blep) {
    if (canManageTime) return true;
    return blep.user === $userStore?.id && within30h(blep.start_time);
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

  function openEdit(blep) { editingBlep = blep; modalAction = 'edit'; modalOpen = true; }
  function requestEdit(blep) { editingBlep = blep; modalAction = 'request'; modalOpen = true; }
  async function handleSaved() { modalOpen = false; editingBlep = null; await load(); }
  function closeModal() { modalOpen = false; editingBlep = null; }

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
    <BlepLogTable {bleps}>
      {#snippet actions(blep)}
        {#if isEditable(blep)}
          <button type="button" onclick={() => openEdit(blep)}>Edit</button>
        {:else}
          <button type="button" onclick={() => requestEdit(blep)}>Request Edit</button>
        {/if}
      {/snippet}
    </BlepLogTable>
  {/if}
</section>

<TimeEditModal
  open={modalOpen}
  recordType="blep"
  action={modalAction}
  record={editingBlep}
  currentUser={$userStore}
  onSaved={handleSaved}
  onClose={closeModal}
/>
