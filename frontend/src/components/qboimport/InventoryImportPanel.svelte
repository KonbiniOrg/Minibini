<script>
  // Inventory-item suggestions inside the Catalog → Inventory tab:
  // each row needs an accounting category. Filter box for bulk lists.
  import SuggestionPanel from './SuggestionPanel.svelte';
  import { qboImportApi } from '../../lib/qboImport.js';

  let { onCommitted = () => {} } = $props();
  let edits = $state({});
  let filter = $state('');

  function initEdits(rows) {
    const next = { ...edits };
    for (const row of rows) {
      if (!next[row.qbo_id]) {
        next[row.qbo_id] = { code: row.code_suggestion,
                             accounting_category: row.category };
      }
    }
    edits = next;
  }

  function edit(row) {
    return edits[row.qbo_id]
      || { code: row.code_suggestion, accounting_category: row.category };
  }

  function set(row, field, value) {
    edits = { ...edits, [row.qbo_id]: { ...edit(row), [field]: value } };
  }

  function visible(rows) {
    const q = filter.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) =>
      (r.code_suggestion || '').toLowerCase().includes(q)
      || (r.description || '').toLowerCase().includes(q));
  }

  function commit(rows) {
    const missingCat = rows.filter(
      (r) => r.state !== 'changed' && !edit(r).accounting_category);
    if (missingCat.length) {
      throw new Error('Before applying, pick a category for: '
        + missingCat.map((r) => edit(r).code).join(', ') + '.');
    }
    return qboImportApi.commitCatalog(rows.map((r) => ({
      kind: 'inventory',
      action: r.state === 'changed' ? 'update' : 'create',
      qbo_id: r.qbo_id,
      code: edit(r).code,
      description: r.description,
      selling_price: r.selling_price,
      purchase_price: r.purchase_price,
      units: 'none',
      accounting_category: edit(r).accounting_category,
    })));
  }
</script>

{#snippet table(rows, toggles, data)}
  {#if rows.some((r) => r.state === 'new') && !(data?.category_options || []).length}
    <p class="dep-note"><strong>No accounting categories exist yet.</strong>
      Inventory items need one — commit the category suggestions on the
      Settings → Accounting tab first, then pull here again (or reload).</p>
  {/if}
  <p><input type="search" placeholder="Filter…" bind:value={filter}></p>
  <table class="data-table">
    <thead>
      <tr><th></th><th>Name / code</th><th>Price</th>
          <th>Category</th><th>Action</th></tr>
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
          <td>
            {#if row.state === 'new'}
              <input type="text" value={edit(row).code}
                     oninput={(e) => set(row, 'code', e.target.value)}>
            {:else}
              {row.code_suggestion}
            {/if}
          </td>
          <td>${row.selling_price}</td>
          <td>
            {#if row.state !== 'new'}
              <!-- Already imported (or a QBO-side update): bindings live on
                   the konbini record now; nothing to pick here. -->
              —
            {:else}
              <select value={edit(row).accounting_category ?? ''}
                      class:missing={toggles.isChecked(row)
                                     && !edit(row).accounting_category}
                      onchange={(e) => set(row, 'accounting_category', Number(e.target.value) || null)}>
                <option value="">— required —</option>
                {#each data?.category_options || [] as cat}
                  <option value={cat.pk}>{cat.name}</option>
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

<SuggestionPanel area="inventory" title="Inventory suggestions from QuickBooks"
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
