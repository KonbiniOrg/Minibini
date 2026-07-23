<script>
  // Category suggestions inside Settings → Accounting: income-account
  // clusters → editable kAC candidates with the two mapping pulldowns.
  import SuggestionPanel from './SuggestionPanel.svelte';
  import { qboImportApi } from '../../lib/qboImport.js';

  let { onCommitted = () => {} } = $props();
  let edits = $state({});

  function initEdits(rows) {
    const next = { ...edits };
    for (const row of rows) {
      const key = row.income_account.qbo_id;
      if (!next[key]) {
        next[key] = {
          name: row.suggested.name,
          code: row.suggested.code,
          taxable: row.suggested.taxable,
          qbo_item_id: row.fallback_item_default,
          qbo_expense_account_id: row.expense_account_default,
        };
      }
    }
    edits = next;
  }

  function edit(row) {
    return edits[row.income_account.qbo_id] || row.suggested;
  }

  function set(row, field, value) {
    const key = row.income_account.qbo_id;
    edits = { ...edits, [key]: { ...edit(row), [field]: value } };
  }

  function commit(rows) {
    return qboImportApi.commitCategories(rows.map((r) => ({ ...edit(r) })));
  }
</script>

{#snippet table(rows, toggles, data)}
  <table class="data-table">
    <thead>
      <tr><th></th><th>Name</th><th>Code</th><th>Taxable</th><th>Items</th>
          <th>Fallback QBO item</th><th>Expense account</th></tr>
    </thead>
    <tbody>
      {#each rows as row (row.income_account.qbo_id)}
        <tr>
          <td>
            {#if row.state === 'imported'}
              <input type="checkbox" checked disabled title="imported">
            {:else}
              <input type="checkbox" checked={toggles.isChecked(row)}
                     onchange={(e) => toggles.setChecked(row, e.target.checked)}>
            {/if}
          </td>
          <td><input type="text" value={edit(row).name}
                     oninput={(e) => set(row, 'name', e.target.value)}></td>
          <td><input type="text" class="code" value={edit(row).code}
                     oninput={(e) => set(row, 'code', e.target.value)}></td>
          <td><input type="checkbox" checked={edit(row).taxable}
                     onchange={(e) => set(row, 'taxable', e.target.checked)}></td>
          <td>{row.member_count}</td>
          <td>
            <select value={edit(row).qbo_item_id}
                    onchange={(e) => set(row, 'qbo_item_id', e.target.value)}>
              <option value="">— none —</option>
              {#each row.fallback_item_options as opt}
                <option value={opt.qbo_id}>{opt.name}</option>
              {/each}
            </select>
            {#if !row.member_count}<small>no QBO item mapped yet</small>{/if}
          </td>
          <td>
            <select value={edit(row).qbo_expense_account_id}
                    onchange={(e) => set(row, 'qbo_expense_account_id', e.target.value)}>
              <option value="">— none —</option>
              {#each data?.expense_accounts || [] as acct}
                <option value={acct.qbo_id}>{acct.name}</option>
              {/each}
            </select>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
{/snippet}

<SuggestionPanel area="categories" title="Category suggestions from QuickBooks"
  {table} {commit} {onCommitted} onLoaded={initEdits}
  rowKey={(r) => r.income_account.qbo_id} />

<style>
  .code { width: 6em; }
</style>
