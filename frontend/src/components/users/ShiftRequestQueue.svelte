<script>
  import { api } from '../../lib/api.js';
  import { user as userStore } from '../../stores/auth.js';
  import TimeEditModal from '../time/TimeEditModal.svelte';

  let rows = $state([]);
  let loading = $state(true);
  let error = $state('');

  // Editing the target shift/blep in place so the manager can adjust it and
  // then approve, without hunting for the record elsewhere.
  let modalOpen = $state(false);
  let modalType = $state('shift');   // 'shift' | 'blep'
  let modalRecord = $state(null);

  const perms = $derived($userStore?.permissions || []);

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
    } catch (e) { error = e.message || 'Could not load requests.'; }
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
    } catch (e) { error = e.message || 'Could not load the record.'; }
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
    catch (e) { error = e.message || 'Approve failed (resolve the conflict first).'; }
  }
  async function deny(r) {
    const note = prompt('Reason for denial (optional):') ?? '';
    try { await api.post(`/api/${r.ep}/${r.request_id}/deny/`, { note }); await load(); }
    catch (e) { error = e.message || 'Deny failed.'; }
  }

  $effect(() => { load(); });
</script>

<section>
  <h3>Pending Time Change Requests</h3>
  {#if error}<p style="color:#b91c1c">{error}</p>{/if}
  {#if loading}<p>Loading…</p>
  {:else if rows.length === 0}<p>No pending requests.</p>
  {:else}
    <table class="data-table">
      <thead><tr>
        <th>Type</th><th>Worker</th><th>Record</th><th>Requested</th>
        <th>Reason</th><th>Conflict</th><th>Actions</th>
      </tr></thead>
      <tbody>
        {#each rows as r (r.kind + r.request_id)}
          <tr>
            <td>{r.kind}</td>
            <td>{r.requester_name}</td>
            <td>
              {#if r.kind === 'Shift' && r.shift}
                <button type="button" onclick={() => openTarget(r)}>Open shift</button>
              {:else if r.kind === 'Time' && r.blep}
                <button type="button" onclick={() => openTarget(r)}>Open blep{#if r.task_name} ({r.task_name}){/if}</button>
              {:else}
                <em>new {r.kind === 'Shift' ? 'shift' : 'entry'}</em>
              {/if}
            </td>
            <td>{new Date(r.requested_start).toLocaleString()} → {r.requested_end ? new Date(r.requested_end).toLocaleString() : '—'}</td>
            <td>{r.reason}</td>
            <td>
              {#if r.conflicts && r.conflicts.length}
                ⚠
                {#each r.conflicts as c}
                  <button type="button" onclick={() => openRecord(c.type, c.id)}>Open {c.type} ({c.label})</button>
                {/each}
              {:else if r.has_known_conflict}
                ⚠ no covering shift
              {:else}—{/if}
            </td>
            <td>
              <button type="button" onclick={() => approve(r)}>Approve</button>
              <button type="button" onclick={() => deny(r)}>Deny</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p><em>If Approve is blocked by a conflict, open the relevant shift/blep here, adjust
      it so the shift encloses the blep, then approve.</em></p>
  {/if}
</section>

<TimeEditModal
  open={modalOpen}
  recordType={modalType}
  action="edit"
  record={modalRecord}
  currentUser={$userStore}
  userPermissions={perms}
  onSaved={onModalSaved}
  onClose={() => { modalOpen = false; modalRecord = null; }}
/>
