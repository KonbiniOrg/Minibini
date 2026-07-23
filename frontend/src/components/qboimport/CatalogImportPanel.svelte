<script>
  // Catalog item suggestions inside the Catalog area: services bind to
  // schemes, inventory rows need a category. Filter box for bulk lists.
  import SuggestionPanel from './SuggestionPanel.svelte';
  import { qboImportApi } from '../../lib/qboImport.js';

  let { onCommitted = () => {} } = $props();
  let edits = $state({});
  let filter = $state('');

  function initEdits(rows) {
    const next = { ...edits };
    for (const row of rows) {
      if (!next[row.qbo_id]) {
        next[row.qbo_id] = row.kind === 'service'
          ? { rate_scheme: row.rate_scheme_default ?? null }
          : { code: row.code_suggestion, accounting_category: row.category };
      }
    }
    edits = next;
  }

  function edit(row) {
    return edits[row.qbo_id] || (row.kind === 'service'
      ? { rate_scheme: row.rate_scheme_default ?? null }
      : { code: row.code_suggestion, accounting_category: row.category });
  }

  function set(row, field, value) {
    edits = { ...edits, [row.qbo_id]: { ...edit(row), [field]: value } };
  }

  function visible(rows) {
    const q = filter.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) =>
      (r.name || r.code_suggestion || '').toLowerCase().includes(q)
      || (r.description || '').toLowerCase().includes(q));
  }

  function commit(rows) {
    const missingScheme = rows.filter(
      (r) => r.kind === 'service' && r.state !== 'changed' && !edit(r).rate_scheme);
    const missingCat = rows.filter(
      (r) => r.kind === 'inventory' && r.state !== 'changed' && !edit(r).accounting_category);
    if (missingScheme.length || missingCat.length) {
      const parts = [];
      if (missingScheme.length) parts.push(
        'pick a rate scheme for: ' + missingScheme.map((r) => r.name).join(', '));
      if (missingCat.length) parts.push(
        'pick a category for: ' + missingCat.map((r) => edit(r).code).join(', '));
      throw new Error('Before applying, ' + parts.join('; ') + '.');
    }
    return qboImportApi.commitCatalog(rows.map((r) => {
      const action = r.state === 'changed' ? 'update' : 'create';
      if (r.kind === 'service') {
        return { kind: 'service', action, qbo_id: r.qbo_id, name: r.name,
                 description: r.description, rate: r.rate,
                 rate_scheme: edit(r).rate_scheme };
      }
      return { kind: 'inventory', action, qbo_id: r.qbo_id,
               code: edit(r).code, description: r.description,
               selling_price: r.selling_price,
               purchase_price: r.purchase_price, units: 'none',
               accounting_category: edit(r).accounting_category };
    }));
  }
</script>

{#snippet table(rows, toggles, data)}
  {#if rows.some((r) => r.kind === 'service') && !(data?.scheme_options || []).length}
    <p class="dep-note"><strong>No rate schemes exist yet.</strong>
      Service items bind to a rate scheme, so those rows can't apply until
      at least one scheme is saved — commit the rate-scheme suggestions in
      Settings → Pricing first, then pull here again (or reload).</p>
  {/if}
  {#if rows.some((r) => r.kind === 'inventory') && !(data?.category_options || []).length}
    <p class="dep-note"><strong>No accounting categories exist yet.</strong>
      Inventory items need one — commit the category suggestions on the
      Settings → Accounting tab first, then pull here again (or reload).</p>
  {/if}
  <p><input type="search" placeholder="Filter…" bind:value={filter}></p>
  <table class="data-table">
    <thead>
      <tr><th></th><th>Kind</th><th>Name / code</th><th>Price</th>
          <th>Category / scheme</th><th>Action</th></tr>
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
          <td>{row.kind}</td>
          <td>
            {#if row.kind === 'inventory' && row.state === 'new'}
              <input type="text" value={edit(row).code}
                     oninput={(e) => set(row, 'code', e.target.value)}>
            {:else}
              {row.name || row.code_suggestion}
            {/if}
          </td>
          <td>${row.kind === 'service' ? row.rate : row.selling_price}</td>
          <td>
            {#if row.kind === 'service'}
              <select value={edit(row).rate_scheme ?? ''}
                      class:missing={row.state === 'new'
                                     && toggles.isChecked(row)
                                     && !edit(row).rate_scheme}
                      onchange={(e) => set(row, 'rate_scheme', Number(e.target.value) || null)}>
                <option value="">— required —</option>
                {#each data?.scheme_options || [] as s}
                  <option value={s.pk}>{s.name}</option>
                {/each}
              </select>
            {:else}
              <select value={edit(row).accounting_category ?? ''}
                      class:missing={row.state === 'new'
                                     && toggles.isChecked(row)
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

<SuggestionPanel area="catalog" title="Catalog suggestions from QuickBooks"
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
