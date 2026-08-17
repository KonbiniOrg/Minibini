<script>
  // One informational atom (task or material) shown "under" a document
  // line — e.g. what a seeded/backing line is actually made of. Read-only
  // display row; `onRemove` (when wired) renders a compact ✕ at the LEFT of
  // the description (RM 2026-08-17): pulling an atom back out of a line is
  // a different, lighter gesture than removing the line itself, and the two
  // must read differently — the line keeps its worded "Remove" button in
  // the Actions column; the atom gets the ✕ here.
  import { fmtMoney } from '@/lib/taskTotals.js';
  import { atomKindTag } from '@/lib/format.js';

  // colspanBefore: empty cells rendered BEFORE the description (e.g. the
  // line-number column). colspanAfter: additive empty cells AFTER the
  // qty/rate/amount content — callers whose tables have more trailing
  // columns (Based on, Actions) pad to taste; this row renders NO cell of
  // its own under Actions (the estimate surface rowspans the line's
  // Actions cell across its atom group instead).
  let { atom, colspanBefore = 0, colspanAfter = 0, onRemove = null, note = '' } = $props();
</script>

<tr class="doc-atom-row">
  {#each Array(colspanBefore) as _}
    <td></td>
  {/each}
  <td>
    {#if onRemove}
      <button
        type="button"
        class="doc-atom-remove"
        title="Remove from this line"
        aria-label="Remove from this line"
        onclick={onRemove}
      >✕</button>
    {/if}
    <small>[{atomKindTag(atom.kind)}]</small>
    {atom.description}
    {#if note}<small> &mdash; {note}</small>{/if}
  </td>
  <td class="text-right">{atom.qty_display}</td>
  <td class="text-right">{fmtMoney(atom.rate)}</td>
  <td class="text-right">{fmtMoney(atom.amount)}</td>
  {#each Array(colspanAfter) as _}
    <td></td>
  {/each}
</tr>

<style>
  .doc-atom-remove {
    border: none; background: none; cursor: pointer;
    color: #b91c1c; font-size: 12px; line-height: 1;
    padding: 0 4px 0 0; vertical-align: baseline;
  }
  .doc-atom-remove:hover { color: #7f1d1d; }
</style>
