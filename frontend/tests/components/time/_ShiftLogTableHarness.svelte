<script>
  import ShiftLogTable from '@/components/time/ShiftLogTable.svelte';
  let { shifts = [] } = $props();
</script>

<ShiftLogTable {shifts}>
  {#snippet actions(s)}
    <button>Edit {s.shift_id}</button>
  {/snippet}
</ShiftLogTable>
