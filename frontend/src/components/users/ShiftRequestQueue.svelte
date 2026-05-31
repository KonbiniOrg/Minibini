<script>
  import { api } from '../../lib/api.js';

  let rows = $state([]);
  let loading = $state(true);
  let error = $state('');

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
      <thead><tr><th>Type</th><th>Worker</th><th>Requested</th><th>Reason</th><th>Conflict</th><th>Actions</th></tr></thead>
      <tbody>
        {#each rows as r (r.kind + r.request_id)}
          <tr>
            <td>{r.kind}</td>
            <td>{r.requester_name}</td>
            <td>{new Date(r.requested_start).toLocaleString()} → {r.requested_end ? new Date(r.requested_end).toLocaleString() : '—'}</td>
            <td>{r.reason}</td>
            <td>{r.has_known_conflict ? '⚠ yes' : '—'}</td>
            <td>
              <button type="button" onclick={() => approve(r)}>Approve</button>
              <button type="button" onclick={() => deny(r)}>Deny</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p><em>If Approve fails with a conflict, edit the conflicting shift/blep (via the worker's
      record) so the shift encloses the blep, then approve again.</em></p>
  {/if}
</section>
