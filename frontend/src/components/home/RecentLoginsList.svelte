<script>
  import { formatSessionDateTime } from '../../lib/format.js';
  import DataTable from '../DataTable.svelte';

  // The current user's own logins from the home payload, windowed
  // server-side by activity_recent_days.
  let { logins = [], sinceDays = 7 } = $props();
</script>

<section>
  <h3>Recent Logins</h3>
  <p class="window-note">(past {sinceDays} days)</p>
  <DataTable
    rows={logins}
    key={(l) => l.timestamp}
    emptyText="No recent logins."
    columns={[
      { id: 'time', label: 'Time',       cell: timeCell },
      { id: 'ip',   label: 'IP address', cell: ipCell },
    ]}
  />
</section>


{#snippet timeCell(l)}{formatSessionDateTime(l.timestamp)}{/snippet}
{#snippet ipCell(l)}{l.ip_address || '—'}{/snippet}

<style>
  .window-note { color: #6b7280; font-size: 0.85em; margin: -0.5em 0 0.5em; }
</style>
