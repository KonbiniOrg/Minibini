<script>
  // The COLUMN seam of the view-mode design
  // (docs/designs/architecture-and-conventions.md §6). A page declares its
  // columns as data; this component decides which are visible for the
  // current density ($viewMode: lite/full) and layout ($layout:
  // desktop/phone) and renders a <table> on desktop or stacked cards on a
  // phone. Pages never branch on mode themselves.
  //
  // Column def: { id, label, liteLabel?, field?, cell?, lite?, phone?, align? }
  //   id        stable key; emitted as data-col on th/td/dd
  //   label     header text; liteLabel replaces it in lite density
  //   field     render row[field] as text ('' for null/undefined)
  //   cell      snippet (row) => markup; wins over field
  //   lite      false => hidden in lite density        (default true)
  //   phone     false => hidden in phone layout        (default true)
  //   align     'left' | 'right' | 'center' (text-align on th/td)
  //   header    optional snippet (col) => markup rendered inside <th> instead of
  //             the label text (sortable headers); phone cards still show label
  // rowClass  (row) => extra class on the <tr> / card (e.g. a status class)
  import { viewMode } from '../stores/viewMode.js';
  import { layout } from '../stores/layout.js';

  let {
    rows = [],
    columns = [],
    key = (row, i) => i,
    emptyText = 'No results found.',
    class: className = '',
    rowClass = () => undefined,
  } = $props();

  let visibleColumns = $derived(
    columns.filter((c) =>
      ($viewMode === 'full' || c.lite !== false) &&
      ($layout === 'desktop' || c.phone !== false)
    )
  );

  function header(col) {
    return $viewMode === 'lite' && col.liteLabel ? col.liteLabel : col.label;
  }

  function text(row, col) {
    const v = row?.[col.field];
    return v == null ? '' : v;
  }

  function alignStyle(col) {
    return col.align ? `text-align: ${col.align}` : undefined;
  }
</script>

{#snippet cellContent(row, col)}
  {#if col.cell}
    {@render col.cell(row)}
  {:else}
    {text(row, col)}
  {/if}
{/snippet}

{#if rows.length === 0}
  <p class="data-table-empty">{emptyText}</p>
{:else if $layout === 'phone'}
  <ul class="data-cards {className}">
    {#each rows as row, i (key(row, i))}
      <li class="data-card {rowClass(row) || ''}">
        <dl>
          {#each visibleColumns as col (col.id)}
            <dt>{header(col)}</dt>
            <dd data-col={col.id}>{@render cellContent(row, col)}</dd>
          {/each}
        </dl>
      </li>
    {/each}
  </ul>
{:else}
  <table class="data-table {className}">
    <thead>
      <tr>
        {#each visibleColumns as col (col.id)}
          <th data-col={col.id} style={alignStyle(col)}>{#if col.header}{@render col.header(col)}{:else}{header(col)}{/if}</th>
        {/each}
      </tr>
    </thead>
    <tbody>
      {#each rows as row, i (key(row, i))}
        <tr class={rowClass(row)}>
          {#each visibleColumns as col (col.id)}
            <td data-col={col.id} style={alignStyle(col)}>{@render cellContent(row, col)}</td>
          {/each}
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
