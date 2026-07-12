<script>
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import { canManageTime as canManageTimeStore } from '../../stores/permissions.js';
  import { blepActivityVersion } from '../../stores/blepActivity.js';
  import TimeEditModal from './TimeEditModal.svelte';
  import BlepLogTable from './BlepLogTable.svelte';

  // Reusable list of work sessions (bleps), recent-first by start time.
  // Surfaces: the Users page "Work Sessions" tab (all users, worker column,
  // paged), a user's detail page (userId set, no worker column), and the
  // home "Ongoing and Completed Tasks" list (own sessions via the
  // RecentTimeList wrapper).
  //
  // "Work Sessions" is the UI term for bleps — same vocabulary as the task
  // detail page's session table and the "time entry" phrasing in API errors.
  let {
    userId = null,        // 'me' | user id | null (all users)
    showWorker = false,   // single-user surfaces suppress the column
    title = 'Work Sessions',
    sinceDays = null,     // optional look-back window
    paginate = true,      // pager UI; the API pages at 25 regardless
    emptyText = 'No work sessions.',
  } = $props();

  const PAGE_SIZE = 25;

  let bleps = $state([]);
  let count = $state(0);
  let page = $state(1);
  let loading = $state(true);
  let loadError = $state('');
  let editingBlep = $state(null);
  let modalOpen = $state(false);
  let modalAction = $state('edit');

  const canManageTime = $derived($canManageTimeStore);

  function within30h(iso) {
    if (!iso) return false;
    return Date.now() - new Date(iso).getTime() < 30 * 60 * 60 * 1000;
  }

  function isOwn(blep) {
    return blep.user === $userStore?.id;
  }

  function isEditable(blep) {
    if (canManageTime) return true;
    return isOwn(blep) && within30h(blep.start_time);
  }

  async function load() {
    loading = true;
    loadError = '';
    try {
      let url = `/api/bleps/?page=${page}`;
      if (userId != null) url += `&user=${encodeURIComponent(userId)}`;
      if (sinceDays != null) {
        const since = new Date(Date.now() - sinceDays * 24 * 60 * 60 * 1000).toISOString();
        url += `&since=${encodeURIComponent(since)}`;
      }
      const resp = await api.get(url);
      bleps = resp.results || resp;
      count = resp.count ?? bleps.length;
    } catch (e) {
      loadError = e.message || 'Could not load work sessions.';
    } finally {
      loading = false;
    }
  }

  // `page` is a deliberate dependency (pager buttons write it); load()
  // itself only WRITES state — see frontend/README.md § write-only loaders.
  $effect(() => {
    void page;
    load();
  });

  // Refresh when any blep changes (Stop/Cancel/edit from anywhere).
  let lastBlepVersion = $state(0);
  $effect(() => {
    const v = $blepActivityVersion;
    if (v !== lastBlepVersion) {
      lastBlepVersion = v;
      load();
    }
  });

  function openEdit(blep) { editingBlep = blep; modalAction = 'edit'; modalOpen = true; }
  function requestEdit(blep) { editingBlep = blep; modalAction = 'request'; modalOpen = true; }
  async function handleSaved() { modalOpen = false; editingBlep = null; await load(); }
  function closeModal() { modalOpen = false; editingBlep = null; }
</script>

<section>
  {#if title}<h3>{title}</h3>{/if}
  {#if sinceDays != null}<p class="window-note">(past {sinceDays} days)</p>{/if}
  {#if loading && bleps.length === 0}
    <p>Loading…</p>
  {:else if loadError}
    <p class="error">{loadError}</p>
  {:else if bleps.length === 0}
    <p>{emptyText}</p>
  {:else}
    <BlepLogTable {bleps} {showWorker}>
      {#snippet actions(blep)}
        {#if isEditable(blep)}
          <button type="button" onclick={() => openEdit(blep)}>Edit</button>
        {:else if isOwn(blep)}
          <button type="button" onclick={() => requestEdit(blep)}>Request Edit</button>
        {/if}
      {/snippet}
    </BlepLogTable>
    {#if paginate && count > PAGE_SIZE}
      <p class="pager">
        {#if page > 1}
          <button type="button" onclick={() => { page--; }}>Previous</button>
        {/if}
        Page {page}
        {#if page * PAGE_SIZE < count}
          <button type="button" onclick={() => { page++; }}>Next</button>
        {/if}
      </p>
    {/if}
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

<style>
  .pager { display: flex; gap: 8px; align-items: center; }
  .error { color: #a8071a; }
  .window-note { color: #6b7280; font-size: 0.85em; margin: -0.5em 0 0.5em; }
</style>
