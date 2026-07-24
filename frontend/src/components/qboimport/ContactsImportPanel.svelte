<script>
  // Customer / vendor suggestions inside Contacts & Businesses.
  // Straight mirrors — no edits, just include/exclude. (Payment terms
  // have their own panel on Settings → Business.)
  import SuggestionPanel from './SuggestionPanel.svelte';
  import { qboImportApi } from '../../lib/qboImport.js';

  let { onCommitted = () => {} } = $props();

  async function commit(rows) {
    const withAction = (r) => ({
      ...r, action: r.state === 'changed' ? 'update' : 'create',
    });
    const resp = await qboImportApi.commitContacts({
      customers: rows.filter((r) => r.kind === 'customer').map(withAction),
      vendors: rows.filter((r) => r.kind === 'vendor').map(withAction),
    });
    const skipped = [...(resp.customers?.skipped || []),
                     ...(resp.vendors?.skipped || [])];
    if (!skipped.length) return resp;
    const noun = skipped.length === 1 ? 'contact' : 'contacts';
    return { warnings: [
      `${skipped.length} ${noun} couldn't be imported:`,
      ...skipped.map((s) => `${s.name}: ${s.reason}`),
    ] };
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

{#snippet table(rows, toggles, data)}
  {@const customers = rows.filter((r) => r.kind === 'customer')}
  {@const vendors = rows.filter((r) => r.kind === 'vendor')}

  {#if data?.missing_term_refs}
    <p class="dep-note">Some customers reference QBO payment terms that
      aren't in konbini yet — import terms on Settings → Business first,
      or those customers will be created without terms.</p>
  {/if}

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

{/snippet}

<style>
  h5 { margin: 10px 0 4px; }
  .dep-note {
    border: 2px solid #f59e0b;
    background: #fffbeb;
    color: #b45309;
    border-radius: 6px;
    padding: 0.5em 0.75em;
  }
</style>

<SuggestionPanel area="contacts" title="Customers & vendors from QuickBooks"
  {table} {commit} {onCommitted}
  rowKey={(r) => r.kind + r.qbo_id} />
