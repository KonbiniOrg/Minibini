<script>
  // Dashed placeholder row that appears once at least one uncovered-work
  // atom is checked off in UncoveredWorkSection. Clicking through commits
  // the current selection into one new merged document line.
  let { visible = false, nextNumber = '', onCreate } = $props();
</script>

{#if visible}
  <tr class="doc-newline">
    <td colspan="100%">
      <span class="cta">＋ New line from selected</span>
      {#if nextNumber}<small> &mdash; line {nextNumber}</small>{/if}
      <button type="button" onclick={onCreate}>Create line</button>
    </td>
  </tr>
{/if}
