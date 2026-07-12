<script>
  import { api } from '../../lib/api.js';
  import { formatSessionDateTime } from '../../lib/format.js';
  import { shiftActivityVersion } from '../../stores/shift.js';
  import { blepActivityVersion } from '../../stores/blepActivity.js';

  let rows = $state([]);
  let loading = $state(true);

  async function load() {
    loading = true;
    try {
      const [sh, bl] = await Promise.all([
        api.get('/api/shift-change-requests/?mine=true'),
        api.get('/api/blep-change-requests/?mine=true'),
      ]);
      const tag = (list, kind) => (list.results || list).map(r => ({ ...r, kind }));
      rows = [...tag(sh, 'Shift'), ...tag(bl, 'Time')]
        .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    } finally { loading = false; }
  }
  $effect(() => { load(); });
  let lastS = $state(0), lastB = $state(0);
  $effect(() => { const v = $shiftActivityVersion; if (v !== lastS) { lastS = v; load(); } });
  $effect(() => { const v = $blepActivityVersion; if (v !== lastB) { lastB = v; load(); } });
</script>

<section>
  <h3>My Change Requests</h3>
  {#if loading}<p>Loading…</p>
  {:else if rows.length === 0}<p>No change requests.</p>
  {:else}
    <table class="data-table">
      <thead><tr><th>Type</th><th>Requested</th><th>Status</th><th>Reason</th></tr></thead>
      <tbody>
        {#each rows as r (r.kind + r.request_id)}
          <tr>
            <td>{r.kind}</td>
            <td>{formatSessionDateTime(r.requested_start)} → {r.requested_end ? formatSessionDateTime(r.requested_end) : '—'}</td>
            <td>{r.status}{#if r.has_known_conflict && r.status === 'pending'} ⚠{/if}</td>
            <td>{r.reason}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>
