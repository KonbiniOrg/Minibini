<script>
  const { jobs = [], onSelect = null } = $props();
</script>

{#if jobs.length === 0}
  <p>No jobs found.</p>
{:else}
  <table border="1">
    <thead>
      <tr>
        <th>Job #</th>
        <th>Name</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
      {#each jobs as job}
        <tr>
          <td>
            {#if onSelect}
              <button onclick={() => onSelect(job)}>
                {job.job_number}
              </button>
            {:else}
              {job.job_number}
            {/if}
          </td>
          <td>{job.name}</td>
          <td>{job.status}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
