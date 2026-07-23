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
</script>

{#snippet checkbox(row, toggles)}
  {#if row.state === 'imported'}
    <input type="checkbox" checked disabled title="imported">
  {:else}
    <input type="checkbox" checked={toggles.isChecked(row)}
           onchange={(e) => toggles.setChecked(row, e.target.checked)}>
  {/if}
{/snippet}

{#snippet table(rows, toggles)}
  {@const customers = rows.filter((r) => r.kind === 'customer')}
  {@const vendors = rows.filter((r) => r.kind === 'vendor')}
  {@const terms = rows.filter((r) => r.kind === 'term')}

  {#if customers.length}
    <h5>Customers</h5>
    <table class="data-table">
      <thead><tr><th></th><th>Name</th><th>Email</th><th>Action</th></tr></thead>
      <tbody>
        {#each customers as row (row.qbo_id)}
          <tr>
            <td>{@render checkbox(row, toggles)}</td>
            <td>{row.display_name}</td>
            <td>{row.email || '—'}</td>
            <td>{row.state === 'changed' ? 'update' : 'create'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if vendors.length}
    <h5>Vendors</h5>
    <table class="data-table">
      <thead><tr><th></th><th>Name</th><th>Email</th><th>Action</th></tr></thead>
      <tbody>
        {#each vendors as row (row.qbo_id)}
          <tr>
            <td>{@render checkbox(row, toggles)}</td>
            <td>{row.display_name}
              {#if row.merge_hint}<small>(also a customer — will share one business)</small>{/if}
            </td>
            <td>{row.email || '—'}</td>
            <td>{row.state === 'changed' ? 'update' : 'create'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  {#if terms.length}
    <h5>Payment terms</h5>
    <p><small>Not contacts — these become entries in the payment-terms
      list that businesses can be assigned.</small></p>
    <table class="data-table terms-table">
      <thead><tr><th></th><th>Terms</th><th>Days</th><th>Action</th></tr></thead>
      <tbody>
        {#each terms as row (row.qbo_id)}
          <tr>
            <td>{@render checkbox(row, toggles)}</td>
            <td>{row.name}</td>
            <td>{row.due_days}</td>
            <td>{row.state === 'changed' ? 'update' : 'create'}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
{/snippet}

<style>
  h5 { margin: 10px 0 4px; }
  .terms-table { max-width: 420px; background: #f3f4f6; }
</style>

<SuggestionPanel area="contacts" title="Customers, vendors & terms from QuickBooks"
  {table} {commit} {onCommitted}
  rowKey={(r) => r.kind + r.qbo_id} />
