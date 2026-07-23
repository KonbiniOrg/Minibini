<script>
  // Rate-scheme suggestions inside Settings → pricing (RateSchemeManager):
  // one row per QBO service, grouped visually by price; per-row algorithm /
  // unit overrides and an optional collapse-group name.
  import SuggestionPanel from './SuggestionPanel.svelte';
  import { qboImportApi } from '../../lib/qboImport.js';

  let { onCommitted = () => {} } = $props();
  let edits = $state({});

  function initEdits(rows) {
    const next = { ...edits };
    for (const row of rows) {
      if (!next[row.qbo_item_id]) {
        next[row.qbo_item_id] = {
          name: row.name,
          rate: row.rate,
          algorithm: row.algorithm_default,
          unit_label: row.unit_default,
          accounting_category: row.category,
          collapse_group: '',
        };
      }
    }
    edits = next;
  }

  function edit(row) {
    return edits[row.qbo_item_id] || {
      name: row.name, rate: row.rate, algorithm: row.algorithm_default,
      unit_label: row.unit_default, accounting_category: row.category,
      collapse_group: '',
    };
  }

  function set(row, field, value) {
    edits = { ...edits, [row.qbo_item_id]: { ...edit(row), [field]: value } };
  }

  function commit(rows) {
    return qboImportApi.commitSchemes(rows.map((r) => ({
      qbo_item_id: r.qbo_item_id,
      ...edit(r),
      collapse_group: edit(r).collapse_group || null,
    })));
  }
</script>

{#snippet table(rows, toggles, data)}
  <table class="data-table">
    <thead>
      <tr><th></th><th>Service</th><th>Rate</th><th>Algorithm</th>
          <th>Unit</th><th>Category</th><th>Share scheme (group name)</th></tr>
    </thead>
    <tbody>
      {#each [...rows].sort((a, b) => Number(b.price_group) - Number(a.price_group)) as row (row.qbo_item_id)}
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
            <select value={edit(row).algorithm}
                    onchange={(e) => set(row, 'algorithm', e.target.value)}>
              <option value="entered_qty">entered qty</option>
              <option value="elapsed_time">elapsed time (hourly)</option>
            </select>
          </td>
          <td><input type="text" class="unit" value={edit(row).unit_label}
                     oninput={(e) => set(row, 'unit_label', e.target.value)}></td>
          <td>
            <select value={edit(row).accounting_category}
                    onchange={(e) => set(row, 'accounting_category', Number(e.target.value) || null)}>
              <option value="">— required —</option>
              {#each data?.category_options || [] as cat}
                <option value={cat.pk}>{cat.name}</option>
              {/each}
            </select>
          </td>
          <td><input type="text" class="group" placeholder="(own scheme)"
                     value={edit(row).collapse_group}
                     oninput={(e) => set(row, 'collapse_group', e.target.value)}></td>
        </tr>
      {/each}
    </tbody>
  </table>
  <p><small>Rows sharing a group name share ONE scheme (first row names it).
    Same-price rows are adjacent to make sharing easy to spot.</small></p>
{/snippet}

<SuggestionPanel area="schemes" title="Rate scheme suggestions from QuickBooks"
  {table} {commit} {onCommitted} onLoaded={initEdits}
  rowKey={(r) => r.qbo_item_id} />

<style>
  .unit { width: 6em; }
  .group { width: 9em; }
</style>
