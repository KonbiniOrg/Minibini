<script>
  // Supplies the optional `actions` snippet so the snippet-rendering path is
  // testable from a .js test. Not collected as a test (no .test.js name).
  import BlepLogTable from '@/components/time/BlepLogTable.svelte';
  let { bleps = [] } = $props();
</script>

<BlepLogTable {bleps}>
  {#snippet actions(blep)}
    <button>Edit {blep.blep_id}</button>
  {/snippet}
</BlepLogTable>
