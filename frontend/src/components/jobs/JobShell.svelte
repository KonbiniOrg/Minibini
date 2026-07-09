<script>
  import JobHeader from './JobHeader.svelte';
  import JobNavRail from './JobNavRail.svelte';
  import JobContextBand from './JobContextBand.svelte';
  let { job, contact = null, current = null, onJobChange = () => {}, showBand = true, children } = $props();
</script>

{#if job}
  <JobHeader {job} {contact} onStatusChange={onJobChange} />
  <JobNavRail {job} {current} />
  {#if showBand}<JobContextBand {job} />{/if}
{/if}
{@render children?.()}
