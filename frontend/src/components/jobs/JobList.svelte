<script>
  const { jobs = [], onSelect = null } = $props();
</script>

{#if jobs.length === 0}
  <p>No jobs found.</p>
{:else}
  <table class="data-table">
    <thead>
      <tr>
        <th>Job #</th>
        <th>Name</th>
        <th>Status</th>
        <th>PM</th>
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
          <td>
            {#if job.project_manager_name}
              <a href="#/jobs?pm={job.project_manager}">{job.project_manager_name}</a>
            {:else}
              —
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
