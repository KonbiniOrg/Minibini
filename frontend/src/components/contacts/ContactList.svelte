<script>
  import DataTable from '../DataTable.svelte';
  const { contacts = [], onSelect = null } = $props();
</script>

<DataTable
  rows={contacts}
  key={(contact) => contact.contact_id}
  emptyText="No contacts found."
  columns={[
    { id: 'name',  label: 'Name',  cell: nameCell },
    { id: 'email', label: 'Email', field: 'email' },
    { id: 'phone', label: 'Phone', cell: phoneCell },
  ]}
/>

{#snippet nameCell(contact)}
  {#if onSelect}
    <button onclick={() => onSelect(contact)}>{contact.name}</button>
  {:else}
    {contact.name}
  {/if}
{/snippet}

{#snippet phoneCell(contact)}
  {contact.work_number || contact.mobile_number || contact.home_number || ''}
{/snippet}
