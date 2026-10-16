<script>
  import PmJobList from '../../components/jobs/PmJobList.svelte';
  import { querystring } from 'svelte-spa-router';
  import { canManageJobs } from '../../stores/permissions.js';
  import JobCreateModal from '../../components/jobs/JobCreateModal.svelte';

  let pmId = $derived(new URLSearchParams($querystring || '').get('pm') || '');
  let count = $state(0);
  let pmName = $state('');
  let newOpen = $state(false);
</script>

<div class="page-body">
{#if pmId}
  <h2>Jobs managed by {pmName || 'selected manager'} ({count})</h2>
{:else}
  <h2>Jobs ({count})</h2>
{/if}

<p>
  {#if $canManageJobs}
    <button type="button" onclick={() => { newOpen = true; }}>New Job</button>
  {/if}
</p>
<JobCreateModal open={newOpen} onClose={() => { newOpen = false; }} />

<PmJobList {pmId} onLoaded={(d) => { count = d.count; pmName = d.pmName; }} />
</div>
