<script>
  // Same collapsed document as DocCustomerView, plus a trailing up/down
  // arrows column for reordering lines. Composes DocCustomerView and hands
  // it the arrows as a snippet, so the row markup itself lives in exactly
  // one place (DocCustomerView) — not duplicated here.
  import DocCustomerView from './DocCustomerView.svelte';

  let { title, lines = [], grandTotal, onReorder } = $props();
</script>

{#snippet arrowsHeader()}
  <th></th>
{/snippet}

{#snippet arrowsCell(line, i)}
  <td class="doc-reorder-arrows">
    <button
      type="button"
      disabled={i === 0}
      onclick={() => onReorder(line.line_id, 'up')}
    >▲</button>
    <button
      type="button"
      disabled={i === lines.length - 1}
      onclick={() => onReorder(line.line_id, 'down')}
    >▼</button>
  </td>
{/snippet}

<DocCustomerView {title} {lines} {grandTotal} extraHeader={arrowsHeader} extraCell={arrowsCell} />
