<script>
  // Test-only harness: a .js test can't author Svelte snippets, so the `cell`
  // snippet lives here. Not collected as a test (no .test.js name). Mirrors
  // the harness pattern in tests/components/docsurface/.
  import DataTable from '@/components/DataTable.svelte';
  let { rows = [], emptyText = undefined, extraClass = '' } = $props();
</script>

<DataTable
  {rows}
  {emptyText}
  class={extraClass}
  key={(r) => `${r.kind}-${r.id}`}
  columns={[
    { id: 'name',  label: 'Name',  cell: nameCell },
    { id: 'kind',  label: 'Kind',  field: 'kind',  lite: false },
    { id: 'email', label: 'Email', field: 'email', phone: false },
    { id: 'phone', label: 'Phone number', liteLabel: 'Phone', field: 'phone' },
    { id: 'tags',  label: 'Tags',  field: 'tags',  lite: false, phone: false },
    { id: 'total', label: 'Total', field: 'total', align: 'right' },
  ]}
/>

{#snippet nameCell(row)}
  <a href={row.href}>{row.name}</a>
{/snippet}
