<script>
  import DataTable from '../DataTable.svelte';
  const { jobs = [], onSelect = null } = $props();
</script>

<DataTable
  rows={jobs}
  key={(job) => job.job_id}
  emptyText="No jobs found."
  rowClass={(job) => `job-status-${job.status}`}
  columns={[
    { id: 'number', label: 'Job #',  cell: numberCell },
    { id: 'name',   label: 'Name',   field: 'name' },
    { id: 'status', label: 'Status', field: 'status' },
    { id: 'pm',     label: 'PM',     cell: pmCell },
  ]}
/>

{#snippet numberCell(job)}
  {#if onSelect}
    <button onclick={() => onSelect(job)}>{job.job_number}</button>
  {:else}
    {job.job_number}
  {/if}
{/snippet}

{#snippet pmCell(job)}
  {#if job.project_manager_name}
    <a href="#/jobs?pm={job.project_manager}">{job.project_manager_name}</a>
  {:else}
    —
  {/if}
{/snippet}
