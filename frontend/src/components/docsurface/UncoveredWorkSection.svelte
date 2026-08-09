<script>
  // A picklist of not-yet-billed atoms (tasks/materials) shown alongside a
  // document being edited. The biller checks off some subset into
  // `selected` (consumed by NewLineFromSelectedRow to build one merged
  // line), or bills a single row directly via the per-row `onDirect`
  // action. Rows the caller marks unselectable (e.g. task not yet
  // complete) render dimmed and can't be checked off.
  import { fmtMoney } from '@/lib/taskTotals.js';

  let {
    title,
    subtitle = '',
    rows = [],
    selected = $bindable([]),
    directLabel = 'Bill as its own line',
    onDirect = null,
    emptyText = '',
  } = $props();

  function isSelected(id) {
    return selected.includes(id);
  }

  function toggle(id, checked) {
    if (checked) {
      if (!selected.includes(id)) selected = [...selected, id];
    } else if (selected.includes(id)) {
      selected = selected.filter((x) => x !== id);
    }
  }
</script>

<section class="uncovered-work-section">
  <h3>{title}</h3>
  {#if subtitle}<p>{subtitle}</p>{/if}
  <table class="data-table">
    <thead>
      <tr>
        <th></th>
        <th>Description</th>
        <th class="text-right">Qty</th>
        <th class="text-right">Rate</th>
        <th class="text-right">Amount</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {#if rows.length === 0}
        <tr><td colspan="6">{emptyText}</td></tr>
      {:else}
        {#each rows as row (row.id)}
          {@const unselectable = row.selectable === false}
          <tr class:doc-unselectable-row={unselectable}>
            <td>
              <input
                type="checkbox"
                checked={isSelected(row.id)}
                disabled={unselectable}
                onchange={(e) => toggle(row.id, e.target.checked)}
              />
            </td>
            <td>
              <small>[{row.kind === 'task' ? 'task' : 'mat'}]</small>
              {row.description}
              {#if row.chip}<span class="backing-chip {row.chip.cls}">{row.chip.label}</span>{/if}
              {#if unselectable && row.unselectableNote}
                <small> &mdash; {row.unselectableNote}</small>
              {/if}
            </td>
            <td class="text-right">{row.qty_display}</td>
            <td class="text-right">{fmtMoney(row.rate)}</td>
            <td class="text-right">{fmtMoney(row.amount)}</td>
            <td>
              {#if onDirect && !unselectable && !isSelected(row.id)}
                <button type="button" onclick={() => onDirect(row.id)}>{directLabel}</button>
              {/if}
            </td>
          </tr>
        {/each}
      {/if}
    </tbody>
  </table>
</section>
