<script>
  import { link } from 'svelte-spa-router';
  import { api } from '../lib/api.js';
  import { blepActivityVersion } from '../stores/blepActivity.js';
  import BlepLogTable from '../components/time/BlepLogTable.svelte';

  // Single-glance dashboard: who's on shift right now and what changed recently
  // across estimates/jobs, POs, and invoices. One fetch of /api/activity/ drives
  // every region; the look-back window is server-side (activity_recent_days).
  let data = $state(null);
  let loading = $state(true);
  let error = $state('');

  async function load() {
    loading = true;
    error = '';
    try {
      data = await api.get('/api/activity/');
    } catch (e) {
      error = e.message || 'Could not load activity.';
    } finally {
      loading = false;
    }
  }

  $effect(() => { load(); });

  // Reflect this client's own blep changes immediately (e.g. starting/stopping
  // work elsewhere in the app). Cross-client live refresh is future work.
  let lastBlepVersion = $state(0);
  $effect(() => {
    const v = $blepActivityVersion;
    if (v !== lastBlepVersion) {
      lastBlepVersion = v;
      load();
    }
  });

  const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  // Readable local clock time, rounded to the minute (matches BlepLogTable).
  function fmtClock(iso) {
    if (!iso) return '—';
    const d = new Date(Math.round(new Date(iso).getTime() / 60000) * 60000);
    let h = d.getHours();
    const ampm = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    return `${h}:${String(d.getMinutes()).padStart(2, '0')} ${ampm}`;
  }

  // Day-granularity date for event rows (server sends ISO date strings).
  function fmtDate(iso) {
    if (!iso) return '—';
    // Treat a bare YYYY-MM-DD as a local date (avoid UTC off-by-one).
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
    const d = m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(iso);
    return `${DOW[d.getDay()]} ${d.getMonth() + 1}/${d.getDate()}`;
  }

  function jobEventLabel(kind) {
    return kind === 'estimate_sent' ? 'estimate sent' : 'approved';
  }
</script>

<div class="page-body">
{#if loading}
  <p>Loading…</p>
{:else if error}
  <p class="error">{error}</p>
{:else if data}
  <h2>Recent activity (last {data.recent_days} days)</h2>

  <section class="on-shift">
    <h3>On shift</h3>
    {#if data.on_shift.length === 0}
      <p class="empty">Nobody is clocked in right now.</p>
    {:else}
      <div class="cards">
        {#each data.on_shift as s (s.user_id)}
          <div class="shift-card">
            <div class="who">{s.user_name}</div>
            <div class="since">since {fmtClock(s.shift_start)}</div>
            {#if s.current_blep}
              <div class="doing">
                <a href={`/jobs/${s.current_blep.job_id}/tasks/${s.current_blep.task_id}`} use:link>{s.current_blep.task_name}</a>
                <div class="job">
                  <a href={`/jobs/${s.current_blep.job_id}`} use:link>{s.current_blep.job_number} — {s.current_blep.job_name}</a>
                </div>
              </div>
            {:else}
              <div class="idle">idle</div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </section>

  <div class="event-columns">
    <section class="events">
      <h3>Jobs &amp; Estimates</h3>
      {#if data.job_events.length === 0}
        <p class="empty">No job or estimate activity in the last {data.recent_days} days.</p>
      {:else}
        <ul>
          {#each data.job_events as e (e.kind + '-' + e.job_id + '-' + (e.estimate_id ?? '') + '-' + e.date)}
            <li>
              <a href={`/jobs/${e.job_id}`} use:link>{e.job_number}</a>
              — {jobEventLabel(e.kind)} · {fmtDate(e.date)}
            </li>
          {/each}
        </ul>
      {/if}
    </section>

    <section class="events">
      <h3>Purchase Orders</h3>
      {#if data.po_events.length === 0}
        <p class="empty">No purchase order activity in the last {data.recent_days} days.</p>
      {:else}
        <ul>
          {#each data.po_events as e (e.kind + '-' + e.po_id + '-' + e.date)}
            <li>
              <a href={`/purchase-orders/${e.po_id}`} use:link>{e.po_number}</a>
              — {e.kind} · {fmtDate(e.date)}
            </li>
          {/each}
        </ul>
      {/if}
    </section>

    <section class="events">
      <h3>Invoices</h3>
      {#if data.invoice_events.length === 0}
        <p class="empty">No invoice activity in the last {data.recent_days} days.</p>
      {:else}
        <ul>
          {#each data.invoice_events as e (e.kind + '-' + e.invoice_id + '-' + e.date)}
            <li>
              <a href={`/invoices/${e.invoice_id}`} use:link>{e.invoice_number}</a>
              — {e.kind} · {fmtDate(e.date)}
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  </div>

  <section class="completed">
    <h3>Recently completed work</h3>
    {#if data.completed_bleps.length === 0}
      <p class="empty">No completed work in the last {data.recent_days} days.</p>
    {:else}
      <BlepLogTable bleps={data.completed_bleps} showWorker={true} />
    {/if}
  </section>
{/if}
</div>

<style>
  .error { color: #a8071a; }
  .empty { color: #666; font-size: 13px; }

  section { margin-bottom: 1.5rem; }

  .cards { display: flex; flex-wrap: wrap; gap: 0.75rem; }
  .shift-card {
    border: 1px solid #d0d0d0;
    border-left: 3px solid #16a34a;
    border-radius: 4px;
    padding: 0.5rem 0.75rem;
    min-width: 12rem;
    background: #fafdfb;
  }
  .who { font-weight: 600; }
  .since { color: #666; font-size: 12px; }
  .doing { margin-top: 0.4rem; }
  .job { font-size: 13px; }
  .idle { margin-top: 0.4rem; color: #999; font-style: italic; }

  .event-columns { display: flex; flex-wrap: wrap; gap: 1.5rem; align-items: flex-start; }
  .event-columns .events {
    flex: 1 1 18rem;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
    padding: 0.5rem 0.75rem 0.75rem;
    margin-bottom: 0;
  }
  .events h3 { margin-top: 0.25rem; }
  .events ul { list-style: none; padding: 0; margin: 0; }
  .events li { padding: 0.2rem 0; border-bottom: 1px solid #eee; font-size: 14px; }
</style>
