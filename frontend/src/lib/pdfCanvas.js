// Geometry for the PDF layout canvas: which drop target (lib/pdfLayout.js)
// lies under the pointer, where its indicator is drawn, and which column
// preset a dragged divider snaps to. Pure functions over a geometry snapshot
// the canvas measures from the DOM when a drag starts:
//
//   { rows: [{ top, bottom, left, right, lines,
//              cells: [{ top, bottom, left, right,
//                        blocks: [{ top, bottom, left, right }] }] }] }
//
// All coordinates are page-relative pixels.

// Within this many px of a row's top / bottom edge, a drop makes a new row.
const ROW_EDGE = 8;
// Within this fraction of a column's width from its left / right edge, a
// drop goes beside the column (a new column).
const SIDE = 0.2;

/** The drop target at (x, y). Always returns one; whether it is allowed is
 *  for insertBlock / dropBlock to say. */
export function targetAt(geometry, x, y) {
  const { rows } = geometry;
  for (const [r, row] of rows.entries()) {
    if (y < row.top) return { kind: 'newRow', index: r };
    if (y > row.bottom) continue;
    if (y - row.top < ROW_EDGE) return { kind: 'newRow', index: r };
    if (row.bottom - y < ROW_EDGE) return { kind: 'newRow', index: r + 1 };
    if (row.lines) {
      return { kind: 'newRow', index: y < (row.top + row.bottom) / 2 ? r : r + 1 };
    }
    const c = cellAt(row.cells, x);
    const cell = row.cells[c];
    const width = cell.right - cell.left;
    if (width > 0 && x - cell.left < width * SIDE) {
      return { kind: 'beside', row: r, cell: c, side: 'left' };
    }
    if (width > 0 && cell.right - x < width * SIDE) {
      return { kind: 'beside', row: r, cell: c, side: 'right' };
    }
    const index = cell.blocks.filter((b) => (b.top + b.bottom) / 2 < y).length;
    return { kind: 'stack', row: r, cell: c, index };
  }
  return { kind: 'newRow', index: rows.length };
}

// The column containing x, else the nearest one.
function cellAt(cells, x) {
  let best = 0;
  let bestDistance = Infinity;
  for (const [c, cell] of cells.entries()) {
    if (x >= cell.left && x <= cell.right) return c;
    const distance = Math.min(Math.abs(x - cell.left), Math.abs(x - cell.right));
    if (distance < bestDistance) {
      best = c;
      bestDistance = distance;
    }
  }
  return best;
}

/** Where to draw `target`'s indicator: { left, top, width, height } — a
 *  horizontal line for stack / newRow, a vertical bar for beside. */
export function indicatorFor(geometry, target) {
  const { rows } = geometry;
  const THICK = 3;
  if (target.kind === 'newRow') {
    const left = Math.min(...rows.map((r) => r.left));
    const right = Math.max(...rows.map((r) => r.right));
    let y;
    if (!rows.length) y = 0;
    else if (target.index === 0) y = rows[0].top - 6;
    else if (target.index >= rows.length) y = rows.at(-1).bottom + 4;
    else y = (rows[target.index - 1].bottom + rows[target.index].top) / 2 - 1;
    return { left, top: y, width: right - left, height: THICK };
  }
  const row = rows[target.row];
  const cell = row.cells[target.cell];
  if (target.kind === 'beside') {
    const x = target.side === 'left' ? cell.left - THICK - 1 : cell.right + 1;
    return { left: x, top: row.top, width: THICK, height: row.bottom - row.top };
  }
  const { blocks } = cell;
  let y;
  if (!blocks.length) y = cell.top;
  else if (target.index < blocks.length) y = blocks[target.index].top - 2;
  else y = blocks.at(-1).bottom;
  return { left: cell.left, top: y, width: cell.right - cell.left, height: THICK };
}

const TWO_COLUMN_SNAPS = [[1 / 3, '1/3-2/3'], [1 / 2, '1/2-1/2'], [2 / 3, '2/3-1/3']];

/** The two-column preset whose divider is nearest `fraction` (0–1 across
 *  the row). */
export function snapPreset(fraction) {
  let best = TWO_COLUMN_SNAPS[0];
  for (const snap of TWO_COLUMN_SNAPS) {
    if (Math.abs(snap[0] - fraction) < Math.abs(best[0] - fraction)) best = snap;
  }
  return best[1];
}
