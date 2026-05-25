<script>
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import { blepActivityVersion } from '../../stores/blepActivity.js';
  import BlepEditModal from '../tasks/BlepEditModal.svelte';
  import BlepLogTable from '../time/BlepLogTable.svelte';

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

  function openEdit(blep) { editingBlep = blep; modalOpen = true; }
  function requestEdit() { alert('Request Edit: not yet implemented.'); }
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
          <button type="button" onclick={requestEdit}>Request Edit</button>
        {/if}
      {/snippet}
    </BlepLogTable>
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
