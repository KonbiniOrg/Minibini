<script>
  // One informational atom (task or material) shown "under" a document
  // line — e.g. what a seeded/backing line is actually made of. Read-only
  // display row; `onRemove` (when wired) lets an editable context pull the
  // atom back out of the line it's attached to.
  import { fmtMoney } from '@/lib/taskTotals.js';

  // colspanAfter: additive empty cells rendered AFTER the qty/rate/amount
  // content and BEFORE the onRemove cell — lets a caller with more trailing
  // columns than this row's own content (e.g. a Backing column ahead of an
  // Actions column) keep the Remove button landing under the right header.
  let { atom, colspanBefore = 0, colspanAfter = 0, onRemove = null, note = '' } = $props();
</script>

<tr class="doc-atom-row">
  {#each Array(colspanBefore) as _}
    <td></td>
  {/each}
  <td>
    <small>[{atom.kind === 'task' ? 'task' : 'mat'}]</small>
    {atom.description}
    {#if note}<small> &mdash; {note}</small>{/if}
  </td>
  <td class="text-right">{atom.qty_display}</td>
  <td class="text-right">{fmtMoney(atom.rate)}</td>
  <td class="text-right">{fmtMoney(atom.amount)}</td>
  {#each Array(colspanAfter) as _}
    <td></td>
  {/each}
  {#if onRemove}
    <td><button type="button" onclick={onRemove}>Remove</button></td>
  {/if}
</tr>
