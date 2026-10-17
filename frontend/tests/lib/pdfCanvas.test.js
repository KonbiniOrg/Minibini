import { describe, it, expect } from 'vitest';
import { indicatorFor, snapPreset, targetAt } from '@/lib/pdfCanvas.js';

const box = (top, bottom, left = 0, right = 600) => ({ top, bottom, left, right });

// Row 0: two columns (0–300 with two blocks, 300–600 with one).
// Row 1: the line items. Row 2: one column, one block.
const GEOMETRY = {
  rows: [
    {
      ...box(0, 100), lines: false,
      cells: [
        { ...box(0, 100, 0, 300), blocks: [box(0, 40, 0, 300), box(40, 80, 0, 300)] },
        { ...box(0, 100, 300, 600), blocks: [box(0, 50, 300, 600)] },
      ],
    },
    { ...box(120, 300), lines: true, cells: [{ ...box(120, 300), blocks: [box(120, 300)] }] },
    { ...box(320, 360), lines: false, cells: [{ ...box(320, 360), blocks: [box(320, 360)] }] },
  ],
};

describe('targetAt', () => {
  it('stacks before or after a block by its middle', () => {
    expect(targetAt(GEOMETRY, 150, 15)).toEqual({ kind: 'stack', row: 0, cell: 0, index: 0 });
    expect(targetAt(GEOMETRY, 150, 30)).toEqual({ kind: 'stack', row: 0, cell: 0, index: 1 });
    expect(targetAt(GEOMETRY, 150, 70)).toEqual({ kind: 'stack', row: 0, cell: 0, index: 2 });
    // Empty space below a column's blocks: the end of that column.
    expect(targetAt(GEOMETRY, 450, 80)).toEqual({ kind: 'stack', row: 0, cell: 1, index: 1 });
  });

  it('goes beside a column near its left or right edge', () => {
    expect(targetAt(GEOMETRY, 20, 50)).toEqual({ kind: 'beside', row: 0, cell: 0, side: 'left' });
    expect(targetAt(GEOMETRY, 290, 50)).toEqual({ kind: 'beside', row: 0, cell: 0, side: 'right' });
    expect(targetAt(GEOMETRY, 590, 340)).toEqual({ kind: 'beside', row: 2, cell: 0, side: 'right' });
  });

  it('makes a new row in the gaps and at row edges', () => {
    expect(targetAt(GEOMETRY, 300, 110)).toEqual({ kind: 'newRow', index: 1 });
    expect(targetAt(GEOMETRY, 300, 2)).toEqual({ kind: 'newRow', index: 0 });
    expect(targetAt(GEOMETRY, 150, 97)).toEqual({ kind: 'newRow', index: 1 });
    expect(targetAt(GEOMETRY, 300, 500)).toEqual({ kind: 'newRow', index: 3 });
  });

  it('only offers above or below the line items', () => {
    expect(targetAt(GEOMETRY, 300, 150)).toEqual({ kind: 'newRow', index: 1 });
    expect(targetAt(GEOMETRY, 300, 250)).toEqual({ kind: 'newRow', index: 2 });
  });

  it('a pointer beside the page picks the nearest column', () => {
    expect(targetAt(GEOMETRY, 700, 25).cell).toBe(1);
  });
});

describe('indicatorFor', () => {
  it('draws a line across the column for a stack', () => {
    expect(indicatorFor(GEOMETRY, { kind: 'stack', row: 0, cell: 0, index: 1 }))
      .toEqual({ left: 0, top: 38, width: 300, height: 3 });
    expect(indicatorFor(GEOMETRY, { kind: 'stack', row: 0, cell: 1, index: 1 }))
      .toEqual({ left: 300, top: 50, width: 300, height: 3 });
  });

  it('draws a bar down the row for beside', () => {
    expect(indicatorFor(GEOMETRY, { kind: 'beside', row: 0, cell: 1, side: 'right' }))
      .toEqual({ left: 601, top: 0, width: 3, height: 100 });
  });

  it('draws a line across the page between rows for a new row', () => {
    expect(indicatorFor(GEOMETRY, { kind: 'newRow', index: 1 }))
      .toEqual({ left: 0, top: 109, width: 600, height: 3 });
    expect(indicatorFor(GEOMETRY, { kind: 'newRow', index: 3 }))
      .toEqual({ left: 0, top: 364, width: 600, height: 3 });
  });
});

describe('snapPreset', () => {
  it('snaps a divider to the nearest supported split', () => {
    expect(snapPreset(0.1)).toBe('1/3-2/3');
    expect(snapPreset(0.45)).toBe('1/2-1/2');
    expect(snapPreset(0.6)).toBe('2/3-1/3');
    expect(snapPreset(0.95)).toBe('2/3-1/3');
  });
});
