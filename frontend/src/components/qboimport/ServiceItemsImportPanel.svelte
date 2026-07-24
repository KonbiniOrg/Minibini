<script>
  // Service-item suggestions inside the Catalog → Service items tab:
  // each row binds to a rate scheme. Filter box for bulk lists.
  import SuggestionPanel from './SuggestionPanel.svelte';
  import { qboImportApi } from '../../lib/qboImport.js';

  let { onCommitted = () => {} } = $props();
  let edits = $state({});
  let filter = $state('');

  function initEdits(rows) {
    const next = { ...edits };
    for (const row of rows) {
      if (!next[row.qbo_id]) {
        next[row.qbo_id] = { rate_scheme: row.rate_scheme_default ?? null };
      }
    }
    edits = next;
  }

  function edit(row) {
    return edits[row.qbo_id]
      || { rate_scheme: row.rate_scheme_default ?? null };
  }

  function set(row, field, value) {
    edits = { ...edits, [row.qbo_id]: { ...edit(row), [field]: value } };
  }

  function visible(rows) {
    const q = filter.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) =>
      (r.name || '').toLowerCase().includes(q)
      || (r.description || '').toLowerCase().includes(q));
  }

  function commit(rows) {
    const missingScheme = rows.filter(
      (r) => r.state !== 'changed' && !edit(r).rate_scheme);
    if (missingScheme.length) {
      throw new Error('Before applying, pick a rate scheme for: '
        + missingScheme.map((r) => r.name).join(', ') + '.');
    }
    return qboImportApi.commitCatalog(rows.map((r) => ({
      kind: 'service',
      action: r.state === 'changed' ? 'update' : 'create',
      qbo_id: r.qbo_id,
      name: r.name,
      description: r.description,
      rate: r.rate,
      rate_scheme: edit(r).rate_scheme,
    })));
  }
</script>

{#snippet table(rows, toggles, data)}
  {#if rows.some((r) => r.state === 'new') && !(data?.scheme_options || []).length}
    <p class="dep-note"><strong>No rate schemes exist yet.</strong>
      Service items bind to a rate scheme, so these rows can't apply until
      at least one scheme is saved — commit the rate-scheme suggestions in
      Settings → Pricing first, then pull here again (or reload).</p>
  {/if}
  <p><input type="search" placeholder="Filter…" bind:value={filter}></p>
  <table class="data-table">
    <thead>
      <tr><th></th><th>Name</th><th>Price</th>
          <th>Scheme</th><th>Action</th></tr>
    </thead>
    <tbody>
      {#each visible(rows) as row (row.qbo_id)}
        <tr>
          <td>
            {#if row.state === 'imported'}
              <input type="checkbox" checked disabled title="imported">
            {:else}
              <input type="checkbox" checked={toggles.isChecked(row)}
                     onchange={(e) => toggles.setChecked(row, e.target.checked)}>
            {/if}
          </td>
          <td>{row.name}</td>
          <td>${row.rate}</td>
          <td>
            {#if row.state !== 'new'}
              <!-- Already imported (or a QBO-side update): bindings live on
                   the konbini record now; nothing to pick here. -->
              —
            {:else}
              <select value={edit(row).rate_scheme ?? ''}
                      class:missing={toggles.isChecked(row)
                                     && !edit(row).rate_scheme}
                      onchange={(e) => set(row, 'rate_scheme', Number(e.target.value) || null)}>
                <option value="">— required —</option>
                {#each data?.scheme_options || [] as s}
                  <option value={s.pk}>{s.name}</option>
                {/each}
              </select>
            {/if}
          </td>
          <td>{row.state === 'changed' ? 'update' : 'create'}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/snippet}

<SuggestionPanel area="services" title="Service item suggestions from QuickBooks"
  {table} {commit} {onCommitted} onLoaded={initEdits} />

<style>
  select.missing { border: 2px solid #b91c1c; background: #fef2f2; }
  .dep-note {
    border: 2px solid #f59e0b;
    background: #fffbeb;
    color: #b45309;
    border-radius: 6px;
    padding: 0.5em 0.75em;
  }
</style>
