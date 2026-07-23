<script>
  // Shared QBO suggestion panel shell: loads an area's suggestions, renders
  // nothing when dismissed or empty, and provides pull / dismiss / commit
  // chrome around a caller-supplied table (Svelte snippet).
  //
  //   {#snippet table(rows, toggles)} … {/snippet}
  //   <SuggestionPanel {area} title="…" {table}
  //     commit={(checkedRows) => qboImportApi.commitX(...)}
  //     onCommitted={() => …refresh lists…} />
  //
  // `toggles` = { isChecked(row), setChecked(row, bool) } keyed by qbo id.
  import { qboImportApi, formatPullTime } from '../../lib/qboImport.js';
  import { refreshSetupStatus } from '../../stores/setupStatus.js';
  import { errorMessage } from '../../lib/api.js';

  let { area, title, table, commit, onCommitted = () => {},
        rowKey = (r) => r.qbo_id, defaultChecked = (r) => r.state !== 'new' ? true : true } = $props();

  let data = $state(null);          // suggestions response
  let checked = $state({});         // rowKey → bool
  let busy = $state(false);
  let message = $state('');
  let pullSummary = $state('');

  const toggles = {
    isChecked: (row) => checked[rowKey(row)] ?? false,
    setChecked: (row, value) => { checked = { ...checked, [rowKey(row)]: value }; },
  };

  async function load() {
    try {
      data = await qboImportApi.suggestions(area);
      const next = {};
      for (const row of data.rows) {
        next[rowKey(row)] = row.state === 'imported' ? true : defaultChecked(row);
      }
      checked = next;
    } catch (e) {
      data = { dismissed: false, fetched_at: null, rows: [] };
    }
  }

  async function pull() {
    busy = true; message = '';
    try {
      const resp = await qboImportApi.pull(area);
      const parts = Object.entries(resp.summary || {}).map(
        ([kind, c]) => `${kind}: ${c.new} new / ${c.imported} imported`);
      pullSummary = parts.length ? parts.join(' · ') : 'No data';
      await load();
    } catch (e) {
      message = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  async function dismissPanel() {
    try {
      await qboImportApi.dismiss(area);
      await load();
    } catch (e) {
      message = errorMessage(e);
    }
  }

  async function commitChecked() {
    busy = true; message = '';
    try {
      const rows = data.rows.filter(
        (r) => toggles.isChecked(r) && r.state !== 'imported');
      await commit(rows);
      refreshSetupStatus();
      await load();
      onCommitted();
    } catch (e) {
      message = errorMessage(e);
    } finally {
      busy = false;
    }
  }

  load();

  let actionable = $derived(
    data ? data.rows.some((r) => r.state !== 'imported') : false);
</script>

{#if data && !data.dismissed && data.rows.length}
  <section class="qbo-panel">
    <header>
      <h4>{title}</h4>
      <span class="pulled">pulled {formatPullTime(data.fetched_at)}</span>
      <button type="button" onclick={pull} disabled={busy}>Pull from QuickBooks</button>
      <button type="button" onclick={dismissPanel} disabled={busy}>Dismiss</button>
    </header>
    {#if pullSummary}<p class="summary">{pullSummary}</p>{/if}
    {#if message}<p class="error">{message}</p>{/if}
    {@render table(data.rows, toggles)}
    {#if actionable}
      <p>
        <button type="button" onclick={commitChecked} disabled={busy}>
          {busy ? 'Working…' : 'Apply selected'}
        </button>
      </p>
    {/if}
  </section>
{/if}

<style>
  .qbo-panel {
    border: 2px solid #f59e0b;
    background: #fffbeb;
    border-radius: 8px;
    padding: 10px 14px 12px;
    margin-bottom: 18px;
  }
  header { display: flex; gap: 12px; align-items: baseline; }
  header h4 { margin: 4px 0; }
  .pulled { color: #92400e; font-size: 0.85rem; }
  .summary { color: #92400e; font-size: 0.9rem; }
  .error { color: #b91c1c; }
</style>
