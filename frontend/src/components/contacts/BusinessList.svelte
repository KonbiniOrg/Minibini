<script>
  import DataTable from '../DataTable.svelte';
  const { businesses = [], onSelect = null } = $props();
</script>

<DataTable
  rows={businesses}
  key={(business) => business.business_id}
  emptyText="No businesses found."
  columns={[
    { id: 'reference', label: 'Reference', field: 'our_reference_code' },
    { id: 'name',      label: 'Name',      cell: nameCell },
    { id: 'phone',     label: 'Phone',     field: 'business_phone' },
  ]}
/>

{#snippet nameCell(business)}
  {#if onSelect}
    <button onclick={() => onSelect(business)}>{business.business_name}</button>
  {:else}
    {business.business_name}
  {/if}
{/snippet}
