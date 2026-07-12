<script>
  import { formatSessionDateTime } from '../../lib/format.js';

  // The current user's own logins from the home payload, windowed
  // server-side by activity_recent_days.
  let { logins = [], sinceDays = 7 } = $props();
</script>

<section>
  <h3>Recent Logins</h3>
  <p class="window-note">(past {sinceDays} days)</p>
  {#if logins.length === 0}
    <p>No recent logins.</p>
  {:else}
    <table class="data-table">
      <thead>
        <tr><th>Time</th><th>IP address</th></tr>
      </thead>
      <tbody>
        {#each logins as l (l.timestamp)}
          <tr>
            <td>{formatSessionDateTime(l.timestamp)}</td>
            <td>{l.ip_address || '—'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .window-note { color: #6b7280; font-size: 0.85em; margin: -0.5em 0 0.5em; }
</style>
