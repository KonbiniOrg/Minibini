<script>
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import { shiftActivityVersion } from '../../stores/shift.js';
  import ShiftLogTable from '../time/ShiftLogTable.svelte';
  import TimeEditModal from '../time/TimeEditModal.svelte';

  let shifts = $state([]);
  let loading = $state(true);
  let modalOpen = $state(false);
  let editing = $state(null);
  let modalAction = $state('edit');

  const perms = $derived($userStore?.permissions || []);
  const canManageTime = $derived(perms.includes('can_manage_time'));

  function within30h(iso) { return Date.now() - new Date(iso).getTime() < 30 * 3600 * 1000; }
  function isEditable(s) { return canManageTime || within30h(s.start_time); }

  async function load() {
    loading = true;
    try {
      const since = new Date(Date.now() - 7 * 86400000).toISOString();
      const resp = await api.get(`/api/shifts/?user=me&since=${encodeURIComponent(since)}`);
      shifts = resp.results || resp;
    } finally { loading = false; }
  }
  function openEdit(s) { editing = s; modalAction = 'edit'; modalOpen = true; }
  function openRequest(s) { editing = s; modalAction = 'request'; modalOpen = true; }
  async function onSaved() { modalOpen = false; editing = null; await load(); }

  $effect(() => { load(); });
  let last = $state(0);
  $effect(() => { const v = $shiftActivityVersion; if (v !== last) { last = v; load(); } });
</script>

<section>
  <h3>My Shifts</h3>
  {#if loading}<p>Loading…</p>
  {:else if shifts.length === 0}<p>No recent shifts.</p>
  {:else}
    <ShiftLogTable {shifts}>
      {#snippet actions(s)}
        {#if isEditable(s)}
          <button type="button" onclick={() => openEdit(s)}>Edit</button>
        {:else}
          <button type="button" onclick={() => openRequest(s)}>Request Change</button>
        {/if}
      {/snippet}
    </ShiftLogTable>
  {/if}
</section>

<TimeEditModal open={modalOpen} recordType="shift" action={modalAction} record={editing}
  currentUser={$userStore} userPermissions={perms} onSaved={onSaved} onClose={() => { modalOpen = false; editing = null; }} />
