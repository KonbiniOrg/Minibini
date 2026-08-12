<script>
  // Dashed placeholder row that appears once at least one uncovered-work
  // atom is checked off in UncoveredWorkSection. Clicking through commits
  // the current selection into one new merged document line. (No line-number
  // preview — RM 2026-08-11: we don't yet care where the line will land.)
  let { visible = false, onCreate } = $props();
</script>

{#if visible}
  <tr class="doc-newline">
    <td colspan="100%">
      <span class="cta">＋ New line from selected</span>
      <button type="button" onclick={onCreate}>Create line</button>
    </td>
  </tr>
{/if}
