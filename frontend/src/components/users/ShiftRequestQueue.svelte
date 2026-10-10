<script>
  import { api, errorMessage } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import TimeEditModal from '../time/TimeEditModal.svelte';
  import LoadState from '../LoadState.svelte';
  import DataTable from '../DataTable.svelte';

  let rows = $state([]);
  let loading = $state(true);
  let error = $state('');

  // Editing the target shift/blep in place so the manager can adjust it and
  // then approve, without hunting for the record elsewhere.
  let modalOpen = $state(false);
  let modalType = $state('shift');   // 'shift' | 'blep'
  let modalRecord = $state(null);

  async function load() {
    loading = true; error = '';
    try {
      const [sh, bl] = await Promise.all([
        api.get('/api/shift-change-requests/?status=pending'),
        api.get('/api/blep-change-requests/?status=pending'),
      ]);
      const tag = (list, kind, ep) => (list.results || list).map(r => ({ ...r, kind, ep }));
      rows = [...tag(sh, 'Shift', 'shift-change-requests'),
              ...tag(bl, 'Time', 'blep-change-requests')]
        .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    } catch (e) { error = errorMessage(e, 'Could not load requests.'); }
    finally { loading = false; }
  }

  // Open any shift/blep (the request's target, or a conflicting record the
  // check surfaced) in the edit modal so the manager can adjust it in place.
  async function openRecord(type, id) {
    error = '';
    try {
      modalRecord = await api.get(`/api/${type === 'shift' ? 'shifts' : 'bleps'}/${id}/`);
      modalType = type;
      modalOpen = true;
    } catch (e) { error = errorMessage(e, 'Could not load the record.'); }
  }
  function openTarget(r) {
    return openRecord(r.kind === 'Shift' ? 'shift' : 'blep',
                      r.kind === 'Shift' ? r.shift : r.blep);
  }

  async function onModalSaved() {
    modalOpen = false; modalRecord = null;
    await load();   // re-evaluate conflicts after the edit
  }

  async function approve(r) {
    error = '';
    try { await api.post(`/api/${r.ep}/${r.request_id}/approve/`); await load(); }
    catch (e) { error = errorMessage(e, 'Approve failed (resolve the conflict first).'); }
  }
  async function deny(r) {
    const note = prompt('Reason for denial (optional):') ?? '';
    try { await api.post(`/api/${r.ep}/${r.request_id}/deny/`, { note }); await load(); }
    catch (e) { error = errorMessage(e, 'Deny failed.'); }
  }

  $effect(() => { load(); });
</script>

<section>
  <h3>Pending Time Change Requests</h3>
  {#if error}<p style="color:#b91c1c">{error}</p>{/if}
  <LoadState {loading}>
  <DataTable
    rows={rows}
    key={(r) => r.kind + r.request_id}
    emptyText="No pending requests."
    columns={[
      { id: 'type',      label: 'Type',      field: 'kind' },
      { id: 'worker',    label: 'Worker',    field: 'requester_name' },
      { id: 'record',    label: 'Record',    cell: recordCell },
      { id: 'requested', label: 'Requested', cell: requestedCell },
      { id: 'reason',    label: 'Reason',    field: 'reason' },
      { id: 'conflict',  label: 'Conflict',  cell: conflictCell },
      { id: 'actions',   label: 'Actions',   cell: actionsCell },
    ]}
  />
  {#if rows.length > 0}
    <p><em>If Approve is blocked by a conflict, open the relevant shift/timeslip here, adjust
      it so the shift encloses the timeslip, then approve.</em></p>
  {/if}
  </LoadState>
</section>

<TimeEditModal
  open={modalOpen}
  recordType={modalType}
  action="edit"
  record={modalRecord}
  currentUser={$userStore}
  onSaved={onModalSaved}
  onClose={() => { modalOpen = false; modalRecord = null; }}
/>

{#snippet recordCell(r)}
  {#if r.kind === 'Shift' && r.shift}
    <button type="button" onclick={() => openTarget(r)}>Open shift</button>
  {:else if r.kind === 'Time' && r.blep}
    <button type="button" onclick={() => openTarget(r)}>Open timeslip{#if r.task_name} ({r.task_name}){/if}</button>
  {:else}
    <em>new {r.kind === 'Shift' ? 'shift' : 'entry'}</em>
  {/if}
{/snippet}
{#snippet requestedCell(r)}{new Date(r.requested_start).toLocaleString()} → {r.requested_end ? new Date(r.requested_end).toLocaleString() : '—'}{/snippet}
{#snippet conflictCell(r)}
  {#if r.conflicts && r.conflicts.length}
    ⚠
    {#each r.conflicts as c}
      <button type="button" onclick={() => openRecord(c.type, c.id)}>Open {c.type === 'shift' ? 'shift' : 'timeslip'} ({c.label})</button>
    {/each}
  {:else if r.has_known_conflict}
    ⚠ no covering shift
  {:else}—{/if}
{/snippet}
{#snippet actionsCell(r)}
  <button type="button" onclick={() => approve(r)}>Approve</button>
  <button type="button" onclick={() => deny(r)}>Deny</button>
{/snippet}
