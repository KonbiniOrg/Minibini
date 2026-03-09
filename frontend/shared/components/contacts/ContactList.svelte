<script>
  const { contacts = [], onSelect = null } = $props();
</script>

{#if contacts.length === 0}
  <p>No contacts found.</p>
{:else}
  <table border="1">
    <thead>
      <tr>
        <th>Name</th>
        <th>Email</th>
        <th>Phone</th>
      </tr>
    </thead>
    <tbody>
      {#each contacts as contact}
        <tr>
          <td>
            {#if onSelect}
              <a href="#" onclick={(e) => { e.preventDefault(); onSelect(contact); }}>
                {contact.name}
              </a>
            {:else}
              {contact.name}
            {/if}
          </td>
          <td>{contact.email}</td>
          <td>{contact.work_number || contact.mobile_number || contact.home_number || ''}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
