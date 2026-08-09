<script>
  // One informational atom (task or material) shown "under" a document
  // line — e.g. what a seeded/backing line is actually made of. Read-only
  // display row; `onRemove` (when wired) lets an editable context pull the
  // atom back out of the line it's attached to.
  import { fmtMoney } from '@/lib/taskTotals.js';

  let { atom, colspanBefore = 0, onRemove = null, note = '' } = $props();
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
  {#if onRemove}
    <td><button type="button" onclick={onRemove}>Remove</button></td>
  {/if}
</tr>
