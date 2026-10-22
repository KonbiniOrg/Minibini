<script>
  // Test-only harness: a .js test can't author Svelte snippets, so the `item`
  // snippet lives here. Not collected as a test (no .test.js name).
  import SortableList from '@/components/SortableList.svelte';
  import DragHandle from '@/components/DragHandle.svelte';
  let { items = [], disabled = false, onReorder = () => {} } = $props();
</script>

<ul>
  <SortableList {items} getId={(it) => it.id} {disabled} {onReorder}>
    {#snippet item(it, index, sortable)}
      <li data-id={it.id} data-index={index} data-dragging={sortable.dragging} {@attach sortable.ref}>
        {#if sortable.handleRef}<DragHandle attach={sortable.handleRef} label={`Drag ${it.name}`} />{/if}
        {it.name}
      </li>
    {/snippet}
  </SortableList>
</ul>
