<script>
  import { api } from '../../lib/api.js';

  function isoDate(d) { return d.toISOString().slice(0, 10); }
  let start = $state(isoDate(new Date(Date.now() - 6 * 86400000)));
  let end = $state(isoDate(new Date()));
  let workers = $state([]);
  let loading = $state(false);
  let error = $state('');

  function hm(mins) { return `${Math.floor(mins / 60)}h ${mins % 60}m`; }

  async function load() {
    loading = true; error = '';
    try {
      const r = await api.get(`/api/shifts/report/?start=${start}&end=${end}`);
      workers = r.workers;
    } catch (e) { error = e.message || 'Could not load report.'; }
    finally { loading = false; }
  }
  $effect(() => { load(); });
</script>

<section>
  <h3>Payroll — Shift Hours</h3>
  <fieldset style="margin-bottom:10px">
    <legend>Range</legend>
    <label>From <input type="date" bind:value={start} onchange={load}></label>
    <label>To <input type="date" bind:value={end} onchange={load}></label>
  </fieldset>
  {#if error}<p style="color:#b91c1c">{error}</p>{/if}
  {#if loading}<p>Loading…</p>
  {:else if workers.length === 0}<p>No shifts in range.</p>
  {:else}
    {#each workers as w (w.user_id)}
      <h4>{w.name} — total {hm(w.total_minutes)}</h4>
      <table class="data-table">
        <thead><tr><th>Date</th><th>Shifts</th><th>Day total</th></tr></thead>
        <tbody>
          {#each w.days as d (d.date)}
            <tr>
              <td>{d.date}</td>
              <td>{d.shifts.map(s => `${new Date(s.start).toLocaleTimeString()}–${s.end ? new Date(s.end).toLocaleTimeString() : 'open'}`).join(', ')}</td>
              <td>{hm(d.shifts.reduce((t, s) => t + s.minutes, 0))}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/each}
  {/if}
</section>
