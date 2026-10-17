// Pure operations on a document-PDF layout — rows of columns holding blocks
// (apps/core/pdf_layout.py is the authority and re-validates on save):
//
//   { version: 1, rows: [{ columns: '1/2-1/2', cells: [[block, ...], [...]] }] }
//
// Every operation returns a new layout and never mutates its input, and
// leaves no empty column or row behind (`tidy`). The line-item block lives
// alone in a full-width row: nothing moves into or out of that row, its
// column layout can't change, and the row itself moves only as a whole.

// JSON round trip, not structuredClone: a layout is often a $state proxy,
// which structuredClone refuses.
const clone = (value) => JSON.parse(JSON.stringify(value));

export const LINE_ITEMS = 'line_items';

/** Number of columns a preset key describes ('full' → 1, '1/3-2/3' → 2). */
export function columnCount(preset) {
  return preset === 'full' ? 1 : preset.split('-').length;
}

export function isLinesRow(row) {
  return row.cells.some((cell) => cell.some((block) => block.type === LINE_ITEMS));
}

/** A new block of `entry` (a catalog entry) with its default settings. */
export function newBlock(entry) {
  return { type: entry.type, ...clone(entry.settings) };
}

/** How many of each block type the layout holds. */
export function placedCounts(layout) {
  const counts = {};
  for (const row of layout.rows) {
    for (const cell of row.cells) {
      for (const block of cell) counts[block.type] = (counts[block.type] ?? 0) + 1;
    }
  }
  return counts;
}

function moveRow(layout, r, delta) {
  const to = r + delta;
  if (to < 0 || to >= layout.rows.length) return layout;
  const next = clone(layout);
  const [row] = next.rows.splice(r, 1);
  next.rows.splice(to, 0, row);
  return next;
}

/** Re-split a row between the presets its column count allows (the
 *  canvas's column dividers). */
export function setColumns(layout, r, preset) {
  const row = layout.rows[r];
  if (isLinesRow(row) || !presetsFor(row.cells.length).includes(preset)) return layout;
  const next = clone(layout);
  next.rows[r].columns = preset;
  return next;
}

export function updateBlock(layout, pos, changes) {
  const next = clone(layout);
  const cell = next.rows[pos.row].cells[pos.cell];
  cell[pos.index] = { ...cell[pos.index], ...changes };
  return next;
}

export function removeBlock(layout, pos) {
  const block = layout.rows[pos.row].cells[pos.cell][pos.index];
  if (block.type === LINE_ITEMS) return layout;
  const next = clone(layout);
  next.rows[pos.row].cells[pos.cell].splice(pos.index, 1);
  return tidyInPlace(next);
}

/** The nearest row from `r` in direction `delta` that can take blocks. */
function neighbourRow(layout, r, delta) {
  for (let i = r + delta; i >= 0 && i < layout.rows.length; i += delta) {
    if (!isLinesRow(layout.rows[i])) return i;
  }
  return -1;
}

/** Move a block one step (the selected block's arrow buttons): up / down
 *  within its column, crossing into the row above / below (skipping the
 *  line-item row) at either end; left / right into the neighbouring
 *  column. The line items move their whole row up / down. Returns
 *  { layout, pos } or null. */
export function moveBlock(layout, pos, direction) {
  const { row, cell, index } = pos;
  const horizontal = direction === 'left' || direction === 'right';
  if (isLinesRow(layout.rows[row])) {
    if (horizontal) return null;
    const gap = direction === 'up' ? row - 1 : row + 2;
    if (gap < 0 || gap > layout.rows.length) return null;
    return dropBlock(layout, pos, { kind: 'newRow', index: gap });
  }
  const cells = layout.rows[row].cells;
  if (horizontal) {
    const c = cell + (direction === 'left' ? -1 : 1);
    if (c < 0 || c >= cells.length) return null;
    return dropBlock(layout, pos, { kind: 'stack', row, cell: c, index: cells[c].length });
  }
  const delta = direction === 'up' ? -1 : 1;
  const inCell = index + delta;
  if (inCell >= 0 && inCell < cells[cell].length) {
    return dropBlock(layout, pos, { kind: 'stack', row, cell, index: delta < 0 ? inCell : inCell + 1 });
  }
  const r = neighbourRow(layout, row, delta);
  if (r < 0) return null;
  const c = Math.min(cell, layout.rows[r].cells.length - 1);
  return dropBlock(layout, pos, {
    kind: 'stack', row: r, cell: c, index: delta < 0 ? layout.rows[r].cells[c].length : 0,
  });
}

// --- Canvas drops ------------------------------------------------------------
// A drop target on the page canvas is one of:
//   { kind: 'stack', row, cell, index }  — into a column, before `index`
//   { kind: 'beside', row, cell, side }  — a new column left/right of `cell`
//   { kind: 'newRow', index }            — a new full-width row before row `index`
// Coordinates always refer to the layout as it was when the drag started.

const MAX_COLUMNS = 3;
const EQUAL_PRESETS = { 1: 'full', 2: '1/2-1/2', 3: '1/3-1/3-1/3' };
const SNAP_PRESETS = { 1: ['full'], 2: ['1/3-2/3', '1/2-1/2', '2/3-1/3'], 3: ['1/3-1/3-1/3'] };

/** The even split for a column count. */
export function equalPreset(count) {
  return EQUAL_PRESETS[count];
}

/** The presets a row of `count` columns can snap between. */
export function presetsFor(count) {
  return SNAP_PRESETS[count] ?? [];
}

// Drop empty columns from multi-column rows (re-splitting them evenly when
// their count changes) and rows left with no blocks — in place, keeping the
// block objects themselves.
function tidyInPlace(layout) {
  layout.rows = layout.rows.flatMap((row) => {
    const cells = row.cells.filter((cell) => cell.length);
    if (!cells.length) return [];
    if (cells.length === row.cells.length && columnCount(row.columns) === cells.length) {
      return [row];
    }
    // Re-split: the gap survives while there are columns, the row's line
    // stays; the column lines (one per old boundary) don't fit any more.
    const next = { columns: equalPreset(cells.length), cells };
    if (cells.length > 1 && row.gap) next.gap = row.gap;
    if (row.line_below) next.line_below = true;
    return [next];
  });
  return layout;
}

/** Drop empty columns from multi-column rows (re-splitting them evenly when
 *  their count changes) and rows left with no blocks at all. */
export function tidy(layout) {
  return tidyInPlace(clone(layout));
}

// Put `block` at `target` in `layout` (mutated). False when not allowed.
function insertAt(layout, block, target) {
  if (target.kind === 'newRow') {
    layout.rows.splice(target.index, 0, { columns: 'full', cells: [[block]] });
    return true;
  }
  const row = layout.rows[target.row];
  if (!row || isLinesRow(row)) return false;
  if (target.kind === 'stack') {
    row.cells[target.cell].splice(target.index, 0, block);
    return true;
  }
  if (row.cells.filter((cell) => cell.length).length >= MAX_COLUMNS) return false;
  row.cells.splice(target.cell + (target.side === 'right' ? 1 : 0), 0, [block]);
  return true;
}

// The position of the block object `block` (by identity) in `layout`.
function findBlock(layout, block) {
  for (const [r, row] of layout.rows.entries()) {
    for (const [c, cell] of row.cells.entries()) {
      const i = cell.indexOf(block);
      if (i >= 0) return { row: r, cell: c, index: i };
    }
  }
  return null;
}

function finish(original, next, block) {
  tidyInPlace(next);
  if (JSON.stringify(next) === JSON.stringify(original)) return null;
  return { layout: next, pos: findBlock(next, block) };
}

/** Add a new block at a drop target. Returns { layout, pos } or null. */
export function insertBlock(layout, block, target) {
  const next = clone(layout);
  const copy = clone(block);
  if (!insertAt(next, copy, target)) return null;
  return finish(layout, next, copy);
}

/** Move the block at `from` to a drop target, tidying the column / row it
 *  left. The line items move only as their whole row (`newRow` targets).
 *  Returns { layout, pos } or null when the drop isn't allowed or changes
 *  nothing. */
export function dropBlock(layout, from, target) {
  if (isLinesRow(layout.rows[from.row])) {
    if (target.kind !== 'newRow') return null;
    const to = target.index > from.row ? target.index - 1 : target.index;
    if (to === from.row) return null;
    return { layout: moveRow(layout, from.row, to - from.row), pos: { row: to, cell: 0, index: 0 } };
  }
  const next = clone(layout);
  const [block] = next.rows[from.row].cells[from.cell].splice(from.index, 1);
  let t = target;
  if (t.kind === 'stack' && t.row === from.row && t.cell === from.cell && from.index < t.index) {
    t = { ...t, index: t.index - 1 };
  }
  if (!insertAt(next, block, t)) return null;
  return finish(layout, next, block);
}

// --- Column frames ---------------------------------------------------------
// Horizontal spacers (indents) don't print as blocks: with the row's gap and
// column lines they frame their column. Mirrors apps/core/pdf_layout.py
// `_cell_style` — keep the two in step.

export const COLUMN_GAPS = { small: 8, medium: 16, large: 32 };
const INDENTS = { small: 12, medium: 24, large: 48 };
const RULE = '1px solid #333';

/** A horizontal spacer: an indent of its column, not a block in the flow. */
export function isDecoration(block) {
  return block.type === 'spacer' && block.orientation === 'horizontal';
}

/** Inline CSS for column `index` of `row`: its indents, the row's gap
 *  before it (a column after the first) and the column lines either side —
 *  a line sits mid-gap, as the left column's right border. */
export function cellStyle(row, index) {
  const cell = row.cells[index];
  const at = row.columns === 'full' ? 0 : index;
  const gap = COLUMN_GAPS[row.gap ?? 'medium'];
  const lines = row.columns === 'full' ? [] : (row.column_lines ?? []);
  const lineLeft = at > 0 && lines[at - 1];
  const lineRight = Boolean(lines[at]);
  const indent = { left: 0, right: 0 };
  for (const block of cell) {
    if (isDecoration(block)) indent[block.side] += INDENTS[block.size];
  }
  const before = at ? (lineLeft ? Math.floor(gap / 2) : gap) : 0;
  const left = before + indent.left;
  const right = (lineRight ? Math.floor(gap / 2) : 0) + indent.right;
  const parts = [];
  if (lineRight) parts.push(`border-right: ${RULE}`);
  if (left || at) parts.push(`padding-left: ${left}px`);
  if (right) parts.push(`padding-right: ${right}px`);
  return parts.join('; ');
}

/** Set a column row's gap (medium is the unstored default). */
export function setGap(layout, r, gap) {
  if (layout.rows[r].columns === 'full') return layout;
  const next = clone(layout);
  if (gap === 'medium') delete next.rows[r].gap;
  else next.rows[r].gap = gap;
  return next;
}

// --- Divider lines -----------------------------------------------------------
// A divider is not a block: it is a line on a border, and takes no space of
// its own. A line is one of
//   { kind: 'block', row, cell, index }  — under that block (block.line_below)
//   { kind: 'row', row }                 — under that row, across the page
//   { kind: 'column', row, boundary }    — between columns `boundary` and
//                                          `boundary + 1` (row.column_lines)

/** The border a drop target names, as a line — or null where there is no
 *  border to draw on (the top of the page, a page edge). Between stacked
 *  blocks it is the upper block's line; at the end of a full-width row,
 *  the row's; at the top of a column, the line under the row above. */
export function lineForTarget(layout, target) {
  if (target.kind === 'newRow') {
    return target.index > 0 ? { kind: 'row', row: target.index - 1 } : null;
  }
  const row = layout.rows[target.row];
  if (target.kind === 'beside') {
    if (row.columns === 'full') return null;
    const boundary = target.side === 'left' ? target.cell - 1 : target.cell;
    if (boundary < 0 || boundary >= row.cells.length - 1) return null;
    return { kind: 'column', row: target.row, boundary };
  }
  const { index } = target;
  const cell = row.cells[target.cell];
  if (index === 0) return target.row > 0 ? { kind: 'row', row: target.row - 1 } : null;
  if (row.columns === 'full' && index >= cell.length) return { kind: 'row', row: target.row };
  return { kind: 'block', row: target.row, cell: target.cell, index: Math.min(index, cell.length) - 1 };
}

export function hasLine(layout, line) {
  const row = layout.rows[line.row];
  if (!row) return false;
  if (line.kind === 'row') return Boolean(row.line_below);
  if (line.kind === 'column') return Boolean(row.column_lines?.[line.boundary]);
  return Boolean(row.cells[line.cell]?.[line.index]?.line_below);
}

/** Draw (`on`) or erase a line. Unset lines are not stored. */
export function setLine(layout, line, on) {
  const next = clone(layout);
  const row = next.rows[line.row];
  if (line.kind === 'row') {
    if (on) row.line_below = true;
    else delete row.line_below;
  } else if (line.kind === 'column') {
    const lines = row.column_lines ?? new Array(row.cells.length - 1).fill(false);
    lines[line.boundary] = on;
    if (lines.some(Boolean)) row.column_lines = lines;
    else delete row.column_lines;
  } else {
    const block = row.cells[line.cell][line.index];
    if (on) block.line_below = true;
    else delete block.line_below;
  }
  return next;
}

/** Put a divider on the border at `target` — a new one, or the line
 *  `from` moved there. Returns { layout, line } or null when there's no
 *  border there or it already has a line. */
export function placeLine(layout, target, from = null) {
  const line = lineForTarget(layout, target);
  if (!line) return null;
  const base = from ? setLine(layout, from, false) : layout;
  if (hasLine(base, line)) return null;
  return { layout: setLine(base, line, true), line };
}
