<script>
  // Payment-term suggestions on Settings → Business, above the terms
  // manager. Straight mirrors — no edits, just include/exclude.
  import SuggestionPanel from './SuggestionPanel.svelte';
  import { qboImportApi } from '../../lib/qboImport.js';

  let { onCommitted = () => {} } = $props();

  function commit(rows) {
    return qboImportApi.commitTerms(rows.map((r) => ({
      ...r, action: r.state === 'changed' ? 'update' : 'create',
    })));
  }
</script>

{#snippet table(rows, toggles)}
  <table class="data-table">
    <thead><tr><th></th><th>Terms</th><th>Days</th><th>Action</th></tr></thead>
    <tbody>
      {#each rows as row (row.qbo_id)}
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
          <td>{row.due_days}</td>
          <td>{row.state === 'changed' ? 'update' : 'create'}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/snippet}

<SuggestionPanel area="terms" title="Payment terms from QuickBooks"
  {table} {commit} {onCommitted} />
