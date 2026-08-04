<script>
  // Line-item diff table for the change-order panel: a dumb renderer over
  // buildMergedRows/lineDiffTotals output. All actions are callbacks — the
  // panel owns the modal and the API calls. Extracted from the old
  // ChangeOrderDetailPage route (2026-07-19).
  import { formatMoney } from '../../lib/format.js';

  let {
    rows = [],              // buildMergedRows output
    estimateLines = [],     // for the empty-state check
    totals = { estimateTotal: 0, proposedTotal: 0, diffTotal: 0 },
    canEdit = false,        // canManageJobs && CO is draft
    onAddItem = () => {},
    onChangeLine = () => {},   // (estLine) → open replace modal
    onRemoveLine = () => {},   // (estLine) → POST remove item
    onEditLine = () => {},     // (coItem) → open edit modal
    onUndoLine = () => {},     // (coItem) → DELETE the CO item
    onDeleteLine = () => {},   // (coItem) → DELETE an added item
  } = $props();

  // Kind badge (task-owned-money Phase 2/3): same freeform_kind vocabulary
  // and markup/CSS as the estimate/invoice tables' LineItemTable.svelte —
  // 'work' | 'material' | 'fee', set IFF the row's line is a bare
  // hand-authored freeform line (catalog/service lines carry null).
  const KIND_LABELS = { work: 'Work', material: 'Material', fee: 'Fee/Credit' };
  function kindLabel(k) { return KIND_LABELS[k] || ''; }

  function fmtMoney(n) { return formatMoney(n ?? 0); }
  // "+$80.00" for an increase, "-$80.00" for a decrease (diffTotal =
  // proposedTotal - estimateTotal, so it's a real signed delta, not a
  // magnitude) — formatMoney on the magnitude plus an explicit sign, rather
  // than raw "$" string-concatenation which used to drop the "-" entirely
  // (Math.abs'd the value but only ever prepended "+", never "-").
  function fmtDiff(n) {
    const v = Number(n ?? 0);
    if (v === 0) return '$0.00';
    return (v > 0 ? '+' : '-') + formatMoney(Math.abs(v));
  }
</script>

<section class="section">
  <div class="section-head">
    <h3>Line items</h3>
    <span class="spacer"></span>
    {#if canEdit}
      <button type="button" onclick={onAddItem}>+ New line</button>
    {/if}
  </div>

  <table class="diff-table">
    <colgroup>
      <col style="width:30px">
      <col>
      <col style="width:50px">
      <col style="width:50px">
      <col style="width:75px">
      <col style="width:80px">
      <col style="width:150px">
    </colgroup>
    <thead>
      <tr>
        <th>#</th>
        <th>Description</th>
        <th class="num">Qty</th>
        <th>Units</th>
        <th class="num">Price</th>
        <th class="num">Total</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {#if rows.length === 0 && estimateLines.length === 0}
        <tr>
          <td colspan="7" class="empty-msg">No estimate lines or CO lines yet.</td>
        </tr>
      {:else}
        {#each rows as row}
          {#if row.kind === 'unchanged'}
            <tr>
              <td>{row.lineNumber}</td>
              <td>
                {#if row.freeform_kind}
                  <span class="kind-badge kind-{row.freeform_kind}">{kindLabel(row.freeform_kind)}</span>
                {/if}
                {row.description || '—'}
              </td>
              <td class="num">{row.qty ?? '—'}</td>
              <td>{row.units || '—'}</td>
              <td class="num">{fmtMoney(row.price)}</td>
              <td class="num">{fmtMoney(row.total)}</td>
              <td class="acts">
                {#if canEdit}
                  <button type="button" onclick={() => onChangeLine(row.estLine)}>Change</button>
                  <button type="button" onclick={() => onRemoveLine(row.estLine)}>Delete</button>
                {/if}
              </td>
            </tr>
          {:else if row.kind === 'changed'}
            <tr class="row-changed">
              <td>{row.lineNumber}</td>
              <td>
                {#if row.freeform_kind}
                  <span class="kind-badge kind-{row.freeform_kind}">{kindLabel(row.freeform_kind)}</span>
                {/if}
                {row.description || '—'}
              </td>
              <td class="num">{row.qty ?? '—'}</td>
              <td>{row.units || '—'}</td>
              <td class="num">{fmtMoney(row.price)}</td>
              <td class="num">{fmtMoney(row.total)}</td>
              <td class="acts">
                {#if canEdit}
                  <button type="button" onclick={() => onEditLine(row.coItem)}>Edit</button>
                  <button type="button" onclick={() => onUndoLine(row.coItem)}>Undo</button>
                {/if}
              </td>
            </tr>
          {:else if row.kind === 'changed-orig'}
            <tr class="row-gone">
              <td class="keep">{row.lineNumber}</td>
              <td>
                {#if row.freeform_kind}
                  <span class="kind-badge kind-{row.freeform_kind}">{kindLabel(row.freeform_kind)}</span>
                {/if}
                {row.description || '—'}
              </td>
              <td class="num">{row.qty ?? '—'}</td>
              <td>{row.units || '—'}</td>
              <td class="num">{fmtMoney(row.price)}</td>
              <td class="num">{fmtMoney(row.total)}</td>
              <td></td>
            </tr>
          {:else if row.kind === 'removed'}
            <tr class="row-gone">
              <td class="keep">{row.lineNumber}</td>
              <td>
                {#if row.freeform_kind}
                  <span class="kind-badge kind-{row.freeform_kind}">{kindLabel(row.freeform_kind)}</span>
                {/if}
                {row.description || '—'}
              </td>
              <td class="num">{row.qty ?? '—'}</td>
              <td>{row.units || '—'}</td>
              <td class="num">{fmtMoney(row.price)}</td>
              <td class="num">{fmtMoney(row.total)}</td>
              <td class="acts keep">
                {#if canEdit}
                  <button type="button" onclick={() => onUndoLine(row.coItem)}>Undo</button>
                {/if}
              </td>
            </tr>
          {:else if row.kind === 'added'}
            <tr class="row-added">
              <td>{row.lineNumber}</td>
              <td>
                <span class="added-tag">+</span>
                {#if row.freeform_kind}
                  <span class="kind-badge kind-{row.freeform_kind}">{kindLabel(row.freeform_kind)}</span>
                {/if}
                {row.description || '—'}
              </td>
              <td class="num">{row.qty ?? '—'}</td>
              <td>{row.units || '—'}</td>
              <td class="num">{fmtMoney(row.price)}</td>
              <td class="num">{fmtMoney(row.total)}</td>
              <td class="acts">
                {#if canEdit}
                  <button type="button" onclick={() => onEditLine(row.coItem)}>Edit</button>
                  <button type="button" onclick={() => onDeleteLine(row.coItem)}>Delete</button>
                {/if}
              </td>
            </tr>
          {/if}
        {/each}
      {/if}
    </tbody>
    <tfoot>
      <tr>
        <td colspan="5" class="num footer-left">
          Estimate <span class="est-struck">{fmtMoney(totals.estimateTotal)}</span> &rarr; proposed
        </td>
        <td class="num"><strong>{fmtMoney(totals.proposedTotal)}</strong></td>
        <td class="num footer-diff">{fmtDiff(totals.diffTotal)}</td>
      </tr>
    </tfoot>
  </table>
</section>

<style>
  /* Vertical rhythm only — no horizontal inset, so the diff table aligns to
     the .page-body gutter like the estimate panel's tables. */
  .section { padding: 16px 0; }
  .section-head {
    display: flex; align-items: center; gap: 12px; margin-bottom: 8px;
  }
  .section-head h3 { margin: 0; }
  .spacer { flex: 1; }

  /* ---- Merged diff table (shared idiom with CODeliverablesSection) ---- */
  .diff-table {
    width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 13px;
  }
  /* Adopt the house .data-table teal header band for consistency with the
     estimate's tables — but keep the diff's compact sizing, and deliberately
     NOT the house zebra striping (it would fight the semantic row tints below)
     nor the generous house cell padding (this diff is intentionally dense). */
  .diff-table th {
    text-align: left; color: #115e59; font-size: 12px; font-weight: 600;
    padding: 5px 8px; background: #f0fdfa; border-bottom: 2px solid #99f6e4;
  }
  .diff-table td { padding: 6px 8px; vertical-align: middle; }
  .diff-table tbody tr { border-bottom: 1px solid #f3f4f6; }

  .diff-table .num { text-align: right; font-variant-numeric: tabular-nums; }
  .diff-table .acts { text-align: right; white-space: nowrap; }
  .diff-table .acts button { margin-left: 4px; }

  /* Row tints */
  .diff-table tr.row-changed { background: #fff7ed; }
  .diff-table tr.row-added   { background: #dcfce7; }
  .diff-table tr.row-gone td { color: #9ca3af; text-decoration: line-through; }
  .diff-table tr.row-gone td.keep { text-decoration: none; color: #9ca3af; }
  .diff-table tr.row-gone td.acts.keep { text-decoration: none; }

  .added-tag { color: #166534; font-weight: 600; margin-right: 5px; }

  /* Kind badge — same markup/palette as LineItemTable.svelte's estimate/
     invoice tables (task-owned-money Phase 2), reused here for CO lines. */
  .kind-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
    margin-right: 6px;
  }
  .kind-work { background: #e0e7ff; color: #3730a3; }
  .kind-material { background: #d1fae5; color: #065f46; }
  .kind-fee { background: #ffedd5; color: #9a3412; }

  /* Footer */
  .diff-table tfoot td { padding: 8px; border-top: 2px solid #e5e7eb; font-size: 13px; }
  .footer-left { color: #6b7280; }
  .est-struck { text-decoration: line-through; }
  .footer-diff { font-weight: 700; }

  .empty-msg { color: #888; font-size: 13px; padding: 8px 0; }
</style>
