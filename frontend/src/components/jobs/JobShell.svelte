<script>
  import JobHeader from './JobHeader.svelte';
  import JobNavRail from './JobNavRail.svelte';
  import JobContextBand from './JobContextBand.svelte';
  // colorway: a .cw-* class (app.css) wrapping the page content so the
  // area's chrome — table bands, subnav/mode bars, modals — tints by
  // domain: cw-estimate (estimates/COs), cw-tasks, cw-invoice, cw-neutral
  // (POs/shipments/history/email). Empty = legacy teal defaults.
  let { job, contact = null, current = null, onJobChange = () => {}, showBand = true, colorway = '', children } = $props();
</script>

{#if job}
  <JobHeader {job} {contact} onStatusChange={onJobChange} />
  {#if showBand}<JobContextBand {job} />{/if}
  <JobNavRail {job} {current} />
{/if}
<div class={colorway || null}>
  {@render children?.()}
</div>
