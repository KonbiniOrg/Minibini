<script>
  // Customer / vendor / payment-term suggestions inside Contacts &
  // Businesses. Straight mirrors — no edits, just include/exclude.
  import SuggestionPanel from './SuggestionPanel.svelte';
  import { qboImportApi } from '../../lib/qboImport.js';

  let { onCommitted = () => {} } = $props();

  function commit(rows) {
    const withAction = (r) => ({
      ...r, action: r.state === 'changed' ? 'update' : 'create',
    });
    return qboImportApi.commitContacts({
      terms: rows.filter((r) => r.kind === 'term').map(withAction),
      customers: rows.filter((r) => r.kind === 'customer').map(withAction),
      vendors: rows.filter((r) => r.kind === 'vendor').map(withAction),
    });
  }

  const LABELS = { customer: 'Customer', vendor: 'Vendor', term: 'Payment terms' };
</script>

{#snippet table(rows, toggles)}
  <table class="data-table">
    <thead>
      <tr><th></th><th>Kind</th><th>Name</th><th>Details</th><th>Action</th></tr>
    </thead>
    <tbody>
      {#each rows as row (row.kind + row.qbo_id)}
        <tr>
          <td>
            {#if row.state === 'imported'}
              <input type="checkbox" checked disabled title="imported">
            {:else}
              <input type="checkbox" checked={toggles.isChecked(row)}
                     onchange={(e) => toggles.setChecked(row, e.target.checked)}>
            {/if}
          </td>
          <td>{LABELS[row.kind]}
            {#if row.merge_hint}<small>(also a customer — will share one business)</small>{/if}
          </td>
          <td>{row.display_name || row.name}</td>
          <td>
            {#if row.kind === 'term'}{row.due_days} days
            {:else}{row.email || '—'}{/if}
          </td>
          <td>{row.state === 'changed' ? 'update' : 'create'}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/snippet}

<SuggestionPanel area="contacts" title="Customers, vendors & terms from QuickBooks"
  {table} {commit} {onCommitted}
  rowKey={(r) => r.kind + r.qbo_id} />
