<script>
  // Real two-way bind:selected wiring, so the "binds selection into the
  // array" contract can be verified from a .js test (a plain `render()`
  // call has no owning parent to bind back to). Not collected as a test
  // (no .test.js name).
  import UncoveredWorkSection from '@/components/docsurface/UncoveredWorkSection.svelte';
  let {
    rows = [],
    onDirect = null,
    directLabel = undefined,
    emptyText = '',
  } = $props();
  let selected = $state([]);
</script>

<div data-testid="selected">{JSON.stringify(selected)}</div>
<UncoveredWorkSection
  title="Uncovered work"
  {rows}
  bind:selected
  {onDirect}
  {directLabel}
  {emptyText}
/>
