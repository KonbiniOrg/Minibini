<script>
  import PmJobList from '../../components/jobs/PmJobList.svelte';
  import { querystring } from 'svelte-spa-router';

  let pmId = $derived(new URLSearchParams($querystring || '').get('pm') || '');
  let count = $state(0);
  let pmName = $state('');
</script>

<div class="page-body">
{#if pmId}
  <h2>Jobs managed by {pmName || 'selected manager'} ({count})</h2>
{:else}
  <h2>Jobs ({count})</h2>
{/if}

<p><a href="#/jobs/new">New Job</a></p>

<PmJobList {pmId} onLoaded={(d) => { count = d.count; pmName = d.pmName; }} />
</div>
