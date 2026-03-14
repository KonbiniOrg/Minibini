<script>
  const { businesses = [], onSelect = null } = $props();
</script>

{#if businesses.length === 0}
  <p>No businesses found.</p>
{:else}
  <table border="1">
    <thead>
      <tr>
        <th>Reference</th>
        <th>Name</th>
        <th>Phone</th>
      </tr>
    </thead>
    <tbody>
      {#each businesses as business}
        <tr>
          <td>{business.our_reference_code}</td>
          <td>
            {#if onSelect}
              <button onclick={() => onSelect(business)}>
                {business.business_name}
              </button>
            {:else}
              {business.business_name}
            {/if}
          </td>
          <td>{business.business_phone || ''}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
