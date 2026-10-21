<script>
  // Drag-and-drop reorder for any list (issue #513) — the one place that owns
  // the dnd-kit provider, the optimistic order, and the drop → new id order.
  // First user: the job Tasks table (TaskTree); the other reorderable lists
  // (line items, document reorder mode, deliverables…) adopt it next.
  //
  // The caller renders each item through the `item` snippet and attaches
  // `sortable.ref` to the element that moves (a <tbody>, <tr>, <li>…) and
  // `sortable.handleRef` to its DragHandle; both are null while disabled.
  // It renders no element of its own, so it can sit directly inside a <table>.
  // `onReorder(ids)` saves the new order; the dropped order shows at once and
  // the caller's next `items` replaces it (which also undoes a failed save
  // once the caller reloads).
  import { DragDropProvider } from '@dnd-kit-svelte/svelte';
  import { useSortable } from '@dnd-kit-svelte/svelte/sortable';
  import { RestrictToVerticalAxis } from '@dnd-kit/abstract/modifiers';
  import { nextOrder } from '../lib/dragOrder.js';

  let { items = [], getId, disabled = false, onReorder, item } = $props();

  let localOrder = $state(null);
  $effect(() => { void items; localOrder = null; });
  const ordered = $derived.by(() => {
    if (!localOrder) return items;
    const byId = new Map(items.map((it) => [getId(it), it]));
    const list = localOrder.map((id) => byId.get(id)).filter(Boolean);
    return list.length === items.length ? list : items;
  });

  // A dragged table row (or <tbody>) is lifted out of the table while it
  // moves, so its cells stop sharing the table's column widths and rewrap.
  // Pin each cell to its width at pick-up; release on drop.
  let pinned = [];
  function pinCellWidths(el) {
    pinned = el ? Array.from(el.querySelectorAll(':scope > td, :scope > tr > td')) : [];
    for (const td of pinned) {
      const w = `${td.getBoundingClientRect().width}px`;
      td.style.width = w; td.style.minWidth = w; td.style.maxWidth = w;
    }
  }
  function releaseCellWidths() {
    for (const td of pinned) { td.style.width = ''; td.style.minWidth = ''; td.style.maxWidth = ''; }
    pinned = [];
  }

  function handleDragStart(event) {
    pinCellWidths(event.operation?.source?.element);
  }

  function handleDragEnd(event) {
    releaseCellWidths();
    const next = nextOrder(ordered.map(getId), event);
    if (!next) return;
    localOrder = next;
    onReorder?.(next);
  }

  const still = { ref: null, handleRef: null, dragging: false };
</script>

{#snippet sortableItem(it, index)}
  {@const s = useSortable({ id: getId(it), index: () => index })}
  {@render item(it, index, { ref: s.ref, handleRef: s.handleRef, dragging: s.isDragging.current })}
{/snippet}

{#if disabled}
  {#each ordered as it, index (getId(it))}
    {@render item(it, index, still)}
  {/each}
{:else}
  <DragDropProvider
    modifiers={[
      // @ts-expect-error @dnd-kit/abstract types (as in the dashboard-01 block)
      RestrictToVerticalAxis,
    ]}
    onDragStart={handleDragStart}
    onDragEnd={handleDragEnd}
  >
    {#each ordered as it, index (getId(it))}
      {@render sortableItem(it, index)}
    {/each}
  </DragDropProvider>
{/if}
