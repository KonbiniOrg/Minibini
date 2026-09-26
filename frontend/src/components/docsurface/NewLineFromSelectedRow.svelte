<script>
  // Dashed placeholder row that appears once at least one uncovered-work
  // atom is checked off in UncoveredWorkSection. Clicking through commits
  // the current selection into one new merged document line. (No line-number
  // preview — RM 2026-08-11: we don't yet care where the line will land.)
  //
  // `buttonLabel` is overridable so the estimate/CO edit views can read
  // "Bundle into line…" (the action opens BundleModal there, Task 8) while
  // the invoice edit view — which keeps its original one-click behavior —
  // stays on the default "Create line" without touching its call site.
  let { visible = false, onCreate, buttonLabel = 'Create line' } = $props();
</script>

{#if visible}
  <tr class="doc-newline">
    <td colspan="100%">
      <span class="cta">＋ New line from selected</span>
      <button type="button" onclick={onCreate}>{buttonLabel}</button>
    </td>
  </tr>
{/if}
