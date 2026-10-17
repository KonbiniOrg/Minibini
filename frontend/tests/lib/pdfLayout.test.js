import {
  cellStyle, columnCount, dropBlock, equalPreset, insertBlock, isLinesRow, moveBlock,
  hasLine, isDecoration, lineForTarget, newBlock, placeLine, placedCounts, presetsFor,
  removeBlock, setColumns, setGap, setLine, tidy, updateBlock,
} from '@/lib/pdfLayout.js';

const b = (type, extra = {}) => ({ type, ...extra });
const LINES = { columns: 'full', cells: [[b('line_items')]] };

// letterhead | title | lines | terms
function sample() {
  return {
    version: 1,
    rows: [
      { columns: '1/2-1/2', cells: [[b('logo')], [b('company_name'), b('company_phone')]] },
      { columns: 'full', cells: [[b('title')]] },
      LINES,
      { columns: '1/3-2/3', cells: [[b('text', { html: 'A' })], [b('text', { html: 'B' })]] },
    ],
  };
}

const types = (layout, r) => layout.rows[r].cells.map((cell) => cell.map((x) => x.html ?? x.type));

describe('pdfLayout', () => {
  it('counts columns from a preset key', () => {
    expect(columnCount('full')).toBe(1);
    expect(columnCount('1/3-2/3')).toBe(2);
    expect(columnCount('1/3-1/3-1/3')).toBe(3);
  });

  it('never mutates its input', () => {
    const layout = sample();
    const before = JSON.stringify(layout);
    setColumns(layout, 0, '1/3-2/3');
    moveBlock(layout, { row: 0, cell: 1, index: 0 }, 'left');
    removeBlock(layout, { row: 0, cell: 0, index: 0 });
    insertBlock(layout, b('divider'), { kind: 'newRow', index: 0 });
    dropBlock(layout, { row: 1, cell: 0, index: 0 }, { kind: 'newRow', index: 4 });
    updateBlock(layout, { row: 1, cell: 0, index: 0 }, { align: 'right' });
    expect(JSON.stringify(layout)).toBe(before);
  });

  it('re-splits a row only between presets of its column count', () => {
    expect(setColumns(sample(), 0, '1/3-2/3').rows[0].columns).toBe('1/3-2/3');
    const layout = sample();
    expect(setColumns(layout, 0, 'full')).toBe(layout);
    expect(setColumns(layout, 0, '1/3-1/3-1/3')).toBe(layout);
    expect(setColumns(layout, 2, '1/2-1/2')).toBe(layout);
  });

  it('updates a block\'s settings', () => {
    const layout = updateBlock(sample(), { row: 1, cell: 0, index: 0 }, { align: 'right' });
    expect(layout.rows[1].cells[0][0]).toEqual({ type: 'title', align: 'right' });
  });

  it('removes a block and tidies', () => {
    const layout = removeBlock(sample(), { row: 0, cell: 0, index: 0 });
    expect(layout.rows[0]).toEqual({ columns: 'full', cells: [[b('company_name'), b('company_phone')]] });
    expect(removeBlock(sample(), { row: 1, cell: 0, index: 0 }).rows).toHaveLength(3);
  });

  it('never removes the line items', () => {
    const layout = sample();
    expect(removeBlock(layout, { row: 2, cell: 0, index: 0 })).toBe(layout);
  });

  it('moves a block up and down within its column', () => {
    const down = moveBlock(sample(), { row: 0, cell: 1, index: 0 }, 'down');
    expect(types(down.layout, 0)[1]).toEqual(['company_phone', 'company_name']);
    expect(down.pos).toEqual({ row: 0, cell: 1, index: 1 });
    const up = moveBlock(down.layout, down.pos, 'up');
    expect(types(up.layout, 0)[1]).toEqual(['company_name', 'company_phone']);
    expect(up.pos).toEqual({ row: 0, cell: 1, index: 0 });
  });

  it('moves a block left and right into the neighbouring column', () => {
    const left = moveBlock(sample(), { row: 0, cell: 1, index: 1 }, 'left');
    expect(types(left.layout, 0)).toEqual([['logo', 'company_phone'], ['company_name']]);
    expect(left.pos).toEqual({ row: 0, cell: 0, index: 1 });
    // The logo's column empties: the row becomes one column.
    const right = moveBlock(sample(), { row: 0, cell: 0, index: 0 }, 'right');
    expect(right.layout.rows[0]).toEqual({
      columns: 'full', cells: [[b('company_name'), b('company_phone'), b('logo')]],
    });
    expect(moveBlock(sample(), { row: 1, cell: 0, index: 0 }, 'left')).toBeNull();
  });

  it('crosses into the row above or below, skipping the line-item row', () => {
    const up = moveBlock(sample(), { row: 1, cell: 0, index: 0 }, 'up');
    expect(types(up.layout, 0)[0]).toEqual(['logo', 'title']);
    expect(up.pos).toEqual({ row: 0, cell: 0, index: 1 });
    expect(up.layout.rows).toHaveLength(3);   // the title's row emptied

    const down = moveBlock(sample(), { row: 1, cell: 0, index: 0 }, 'down');
    expect(types(down.layout, 2)[0]).toEqual(['title', 'A']);
    expect(down.pos).toEqual({ row: 2, cell: 0, index: 0 });

    // A column index past the target row's columns lands in its last one.
    const fromRight = moveBlock(sample(), { row: 3, cell: 1, index: 0 }, 'up');
    expect(types(fromRight.layout, 1)).toEqual([['title', 'B']]);

    expect(moveBlock(sample(), { row: 0, cell: 0, index: 0 }, 'up')).toBeNull();
    expect(moveBlock(sample(), { row: 3, cell: 0, index: 0 }, 'down')).toBeNull();
  });

  it('moves the line items\' row up and down, never sideways', () => {
    const lines = { row: 2, cell: 0, index: 0 };
    const up = moveBlock(sample(), lines, 'up');
    expect(up.layout.rows.map(isLinesRow)).toEqual([false, true, false, false]);
    expect(up.pos).toEqual({ row: 1, cell: 0, index: 0 });
    const down = moveBlock(sample(), lines, 'down');
    expect(down.layout.rows.map(isLinesRow)).toEqual([false, false, false, true]);
    expect(moveBlock(down.layout, down.pos, 'down')).toBeNull();
    expect(moveBlock(sample(), lines, 'left')).toBeNull();
  });

  it('counts placed blocks by type', () => {
    expect(placedCounts(sample())).toMatchObject({ text: 2, title: 1, line_items: 1 });
  });

  it('builds a new block from a catalog entry', () => {
    expect(newBlock({ type: 'spacer', settings: { size: 'medium' } }))
      .toEqual({ type: 'spacer', size: 'medium' });
  });

});

describe('pdfLayout canvas drops', () => {
  const pos = (layout, block) => {
    for (const [r, row] of layout.rows.entries()) {
      for (const [c, cell] of row.cells.entries()) {
        const i = cell.findIndex((x) => x.html === block || x.type === block);
        if (i >= 0) return { row: r, cell: c, index: i };
      }
    }
    return null;
  };

  it('picks equal presets and the snap choices for a column count', () => {
    expect(equalPreset(1)).toBe('full');
    expect(equalPreset(2)).toBe('1/2-1/2');
    expect(equalPreset(3)).toBe('1/3-1/3-1/3');
    expect(presetsFor(2)).toEqual(['1/3-2/3', '1/2-1/2', '2/3-1/3']);
    expect(presetsFor(3)).toEqual(['1/3-1/3-1/3']);
  });

  it('tidies away empty columns and rows', () => {
    const layout = {
      version: 1,
      rows: [
        { columns: '1/3-1/3-1/3', cells: [[b('logo')], [], [b('title')]] },
        { columns: '1/2-1/2', cells: [[], []] },
        LINES,
        { columns: '1/2-1/2', cells: [[], [b('divider')]] },
      ],
    };
    const tidied = tidy(layout);
    expect(tidied.rows.map((r) => r.columns)).toEqual(['1/2-1/2', 'full', 'full']);
    expect(types(tidied, 0)).toEqual([['logo'], ['title']]);
    expect(types(tidied, 2)).toEqual([['divider']]);
  });

  it('inserts a new block stacked, beside, or as a new row', () => {
    const stacked = insertBlock(sample(), b('divider'), { kind: 'stack', row: 1, cell: 0, index: 0 });
    expect(types(stacked.layout, 1)).toEqual([['divider', 'title']]);
    expect(stacked.pos).toEqual({ row: 1, cell: 0, index: 0 });

    const beside = insertBlock(sample(), b('logo'), { kind: 'beside', row: 1, cell: 0, side: 'left' });
    expect(beside.layout.rows[1].columns).toBe('1/2-1/2');
    expect(types(beside.layout, 1)).toEqual([['logo'], ['title']]);
    expect(beside.pos).toEqual({ row: 1, cell: 0, index: 0 });

    const right = insertBlock(sample(), b('logo'), { kind: 'beside', row: 0, cell: 1, side: 'right' });
    expect(right.layout.rows[0].columns).toBe('1/3-1/3-1/3');
    expect(types(right.layout, 0)).toEqual([['logo'], ['company_name', 'company_phone'], ['logo']]);

    const row = insertBlock(sample(), b('divider'), { kind: 'newRow', index: 2 });
    expect(row.layout.rows[2]).toEqual({ columns: 'full', cells: [[b('divider')]] });
    expect(row.pos).toEqual({ row: 2, cell: 0, index: 0 });
  });

  it('refuses a fourth column and anything inside the line-item row', () => {
    const three = insertBlock(sample(), b('logo'), { kind: 'beside', row: 0, cell: 1, side: 'right' }).layout;
    expect(insertBlock(three, b('divider'), { kind: 'beside', row: 0, cell: 0, side: 'left' })).toBeNull();
    expect(insertBlock(sample(), b('divider'), { kind: 'stack', row: 2, cell: 0, index: 0 })).toBeNull();
    expect(insertBlock(sample(), b('divider'), { kind: 'beside', row: 2, cell: 0, side: 'left' })).toBeNull();
  });

  it('drops an existing block and tidies where it came from', () => {
    // Title beside the logo: row 2 empties and goes away.
    const moved = dropBlock(sample(), { row: 1, cell: 0, index: 0 },
      { kind: 'beside', row: 0, cell: 0, side: 'right' });
    expect(moved.layout.rows[0].columns).toBe('1/3-1/3-1/3');
    expect(types(moved.layout, 0)).toEqual([['logo'], ['title'], ['company_name', 'company_phone']]);
    expect(moved.layout.rows).toHaveLength(3);
    expect(moved.pos).toEqual(pos(moved.layout, 'title'));

    // The logo leaves its column: the letterhead row drops to one column.
    const out = dropBlock(sample(), { row: 0, cell: 0, index: 0 }, { kind: 'newRow', index: 4 });
    expect(out.layout.rows[0]).toEqual({ columns: 'full', cells: [[b('company_name'), b('company_phone')]] });
    expect(types(out.layout, 4)).toEqual([['logo']]);
    expect(out.pos).toEqual({ row: 4, cell: 0, index: 0 });
  });

  it('stacks within the same column, accounting for its own removal', () => {
    const down = dropBlock(sample(), { row: 0, cell: 1, index: 0 }, { kind: 'stack', row: 0, cell: 1, index: 2 });
    expect(types(down.layout, 0)[1]).toEqual(['company_phone', 'company_name']);
    expect(down.pos).toEqual({ row: 0, cell: 1, index: 1 });
  });

  it('dropping beside itself in a one-block column changes nothing', () => {
    const layout = sample();
    const same = dropBlock(layout, { row: 1, cell: 0, index: 0 }, { kind: 'beside', row: 1, cell: 0, side: 'left' });
    expect(same).toBeNull();
  });

  it('moves the line items only as a whole row', () => {
    const lines = { row: 2, cell: 0, index: 0 };
    expect(dropBlock(sample(), lines, { kind: 'stack', row: 1, cell: 0, index: 0 })).toBeNull();
    expect(dropBlock(sample(), lines, { kind: 'beside', row: 1, cell: 0, side: 'left' })).toBeNull();
    const up = dropBlock(sample(), lines, { kind: 'newRow', index: 1 });
    expect(up.layout.rows.map(isLinesRow)).toEqual([false, true, false, false]);
    expect(up.pos).toEqual({ row: 1, cell: 0, index: 0 });
  });
});

describe('pdfLayout column frames', () => {
  const indent = (side, size) => b('spacer', { orientation: 'horizontal', side, size });

  it('knows which blocks frame their column', () => {
    expect(isDecoration(indent('left', 'small'))).toBe(true);
    expect(isDecoration(b('spacer', { orientation: 'vertical' }))).toBe(false);
  });

  // Same cases as tests/test_pdf_layout.py SpacerAndGapTests / LineTests:
  // the canvas must frame columns exactly as the PDF does.
  it('matches the server\'s cell styles', () => {
    const lined = {
      columns: '1/2-1/2', column_lines: [true],
      cells: [[b('company_name')], [b('company_address')]],
    };
    expect(cellStyle(lined, 0)).toBe('border-right: 1px solid #333; padding-right: 8px');
    expect(cellStyle(lined, 1)).toBe('padding-left: 8px');

    const indented = {
      columns: '1/2-1/2', gap: 'large',
      cells: [[b('company_name'), indent('right', 'large')], [indent('left', 'small'), b('company_address')]],
    };
    expect(cellStyle(indented, 0)).toBe('padding-right: 48px');
    expect(cellStyle(indented, 1)).toBe('padding-left: 44px');

    const both = { ...indented, column_lines: [true], cells: [[b('logo')], [indent('left', 'medium'), b('company_name')]] };
    expect(cellStyle(both, 0)).toBe('border-right: 1px solid #333; padding-right: 16px');
    expect(cellStyle(both, 1)).toBe('padding-left: 40px');
    expect(cellStyle({ columns: 'full', cells: [[b('logo')]] }, 0)).toBe('');
  });

  it('sets a column row\'s gap, storing nothing for medium', () => {
    const large = setGap(sample(), 0, 'large');
    expect(large.rows[0].gap).toBe('large');
    expect('gap' in setGap(large, 0, 'medium').rows[0]).toBe(false);
    const layout = sample();
    expect(setGap(layout, 1, 'large')).toBe(layout);
  });

  it('keeps a row\'s gap and line while it has columns; column lines go on a re-split', () => {
    const three = {
      version: 1,
      rows: [{ columns: '1/3-1/3-1/3', gap: 'small', line_below: true, column_lines: [true, true],
        cells: [[b('logo')], [], [b('title')]] }, LINES],
    };
    expect(tidy(three).rows[0]).toEqual({
      columns: '1/2-1/2', gap: 'small', line_below: true, cells: [[b('logo')], [b('title')]],
    });
    const two = { version: 1, rows: [{ columns: '1/2-1/2', gap: 'small', cells: [[b('logo')], []] }, LINES] };
    expect(tidy(two).rows[0]).toEqual({ columns: 'full', cells: [[b('logo')]] });
  });
});

describe('pdfLayout divider lines', () => {
  // sample(): letterhead (½+½: logo | name, phone) / title / lines / A | B
  it('maps each drop target to the border it names', () => {
    const layout = sample();
    // Between stacked blocks: the upper block's line.
    expect(lineForTarget(layout, { kind: 'stack', row: 0, cell: 1, index: 1 }))
      .toEqual({ kind: 'block', row: 0, cell: 1, index: 0 });
    // Bottom of a column in a column row: under its last block.
    expect(lineForTarget(layout, { kind: 'stack', row: 0, cell: 1, index: 2 }))
      .toEqual({ kind: 'block', row: 0, cell: 1, index: 1 });
    // Bottom of a full-width row: under the row.
    expect(lineForTarget(layout, { kind: 'stack', row: 1, cell: 0, index: 1 }))
      .toEqual({ kind: 'row', row: 1 });
    // Top of a column: the line under the row above — none above row 1.
    expect(lineForTarget(layout, { kind: 'stack', row: 1, cell: 0, index: 0 }))
      .toEqual({ kind: 'row', row: 0 });
    expect(lineForTarget(layout, { kind: 'stack', row: 0, cell: 0, index: 0 })).toBeNull();
    // Between rows.
    expect(lineForTarget(layout, { kind: 'newRow', index: 3 })).toEqual({ kind: 'row', row: 2 });
    expect(lineForTarget(layout, { kind: 'newRow', index: 0 })).toBeNull();
    // Between columns; a page edge or a full-width row has no boundary.
    expect(lineForTarget(layout, { kind: 'beside', row: 0, cell: 0, side: 'right' }))
      .toEqual({ kind: 'column', row: 0, boundary: 0 });
    expect(lineForTarget(layout, { kind: 'beside', row: 0, cell: 1, side: 'left' }))
      .toEqual({ kind: 'column', row: 0, boundary: 0 });
    expect(lineForTarget(layout, { kind: 'beside', row: 0, cell: 0, side: 'left' })).toBeNull();
    expect(lineForTarget(layout, { kind: 'beside', row: 1, cell: 0, side: 'right' })).toBeNull();
  });

  it('draws and erases each kind of line, storing only what is set', () => {
    let layout = sample();
    for (const line of [
      { kind: 'block', row: 0, cell: 1, index: 0 },
      { kind: 'row', row: 1 },
      { kind: 'column', row: 3, boundary: 0 },
    ]) {
      layout = setLine(layout, line, true);
      expect(hasLine(layout, line)).toBe(true);
    }
    expect(layout.rows[0].cells[1][0].line_below).toBe(true);
    expect(layout.rows[1].line_below).toBe(true);
    expect(layout.rows[3].column_lines).toEqual([true]);
    layout = setLine(layout, { kind: 'column', row: 3, boundary: 0 }, false);
    layout = setLine(layout, { kind: 'row', row: 1 }, false);
    layout = setLine(layout, { kind: 'block', row: 0, cell: 1, index: 0 }, false);
    expect(layout).toEqual(sample());
  });

  it('places a new line, refusing where there is no border or one already', () => {
    const placed = placeLine(sample(), { kind: 'newRow', index: 2 });
    expect(placed.line).toEqual({ kind: 'row', row: 1 });
    expect(placed.layout.rows[1].line_below).toBe(true);
    expect(placeLine(placed.layout, { kind: 'newRow', index: 2 })).toBeNull();
    expect(placeLine(sample(), { kind: 'newRow', index: 0 })).toBeNull();
  });

  it('moves a line from one border to another', () => {
    const start = setLine(sample(), { kind: 'row', row: 1 }, true);
    const moved = placeLine(start, { kind: 'beside', row: 0, cell: 0, side: 'right' }, { kind: 'row', row: 1 });
    expect(moved.line).toEqual({ kind: 'column', row: 0, boundary: 0 });
    expect(moved.layout.rows[1].line_below).toBeUndefined();
    expect(moved.layout.rows[0].column_lines).toEqual([true]);
  });

  it('a block\'s line travels with it', () => {
    const lined = setLine(sample(), { kind: 'block', row: 0, cell: 1, index: 0 }, true);
    const moved = moveBlock(lined, { row: 0, cell: 1, index: 0 }, 'down');
    expect(moved.layout.rows[0].cells[1][1]).toEqual(b('company_name', { line_below: true }));
  });
});
