import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import COLineItemsSection from '@/components/changeorders/COLineItemsSection.svelte';

// Mirrors LineItemTable.test.js's negative-price case: a fee/credit CO line
// (or a CO that reduces the estimate total) must render "-$80.00", never the
// mangled "$-80.00" that raw `$`-string-concatenation used to produce.
describe('COLineItemsSection negative (fee/credit) formatting', () => {
  it('puts the minus sign before the dollar sign on a negative row price/total, not "$-"', () => {
    const rows = [{
      kind: 'added', lineNumber: 1, description: 'Loyalty credit',
      qty: 1, units: 'none', price: -80, total: -80,
      coItem: { line_item_id: 1 }, estLine: null,
    }];
    const { getAllByText, queryByText } = render(COLineItemsSection, {
      props: { rows, estimateLines: [{ line_item_id: 9 }], canEdit: false },
    });
    expect(getAllByText('-$80.00').length).toBeGreaterThan(0);
    expect(queryByText('$-80.00')).toBeNull();
  });

  it('renders a negative diffTotal in the footer as "-$..." with an explicit minus, not silently dropped', () => {
    // No rows — isolates the footer-diff cell from the row cells so the
    // "-$80.00" match below is unambiguous.
    const { container, queryByText } = render(COLineItemsSection, {
      props: {
        rows: [], estimateLines: [{ line_item_id: 9 }], canEdit: false,
        totals: { estimateTotal: 100, proposedTotal: 20, diffTotal: -80 },
      },
    });
    const diffCell = container.querySelector('.footer-diff');
    expect(diffCell).not.toBeNull();
    expect(diffCell.textContent).toBe('-$80.00');
    expect(queryByText('$-80.00')).toBeNull();
    expect(queryByText('$80.00')).toBeNull();
  });
});

// task-owned-money Phase 3 Task 6: CO line tables get the same kind badges
// as the estimate tables (LineItemTable.svelte) — 'work' | 'material' |
// 'fee', rendered next to the description whenever the row's line carries
// a freeform_kind (bare hand-authored lines only).
describe('COLineItemsSection kind badge', () => {
  it('renders a kind badge on an unchanged row carrying freeform_kind', () => {
    const rows = [{
      kind: 'unchanged', lineNumber: 1, description: 'Rush handling',
      qty: 1, units: 'none', price: 25, total: 25, freeform_kind: 'fee',
      coItem: null, estLine: { line_item_id: 1 },
    }];
    const { getByText, container } = render(COLineItemsSection, {
      props: { rows, estimateLines: [{ line_item_id: 1 }], canEdit: false },
    });
    expect(getByText('Fee/Credit')).toBeInTheDocument();
    expect(container.querySelector('.kind-badge.kind-fee')).not.toBeNull();
  });

  it('renders a kind badge on an added row, alongside the added-tag', () => {
    const rows = [{
      kind: 'added', lineNumber: 1, description: 'Extra cutting',
      qty: 1, units: 'hour', price: 50, total: 50, freeform_kind: 'work',
      coItem: { line_item_id: 5 }, estLine: null,
    }];
    const { getByText, container } = render(COLineItemsSection, {
      props: { rows, estimateLines: [], canEdit: false },
    });
    expect(getByText('Work')).toBeInTheDocument();
    expect(container.querySelector('.kind-badge.kind-work')).not.toBeNull();
    expect(container.querySelector('.added-tag')).not.toBeNull();
  });

  it('renders a kind badge on a changed row (material) and its struck changed-orig counterpart', () => {
    const rows = [
      {
        kind: 'changed', lineNumber: 2, description: 'Panel XL',
        qty: 4, units: 'ea', price: 60, total: 240, freeform_kind: 'material',
        coItem: { line_item_id: 10 }, estLine: { line_item_id: 2 },
      },
      {
        kind: 'changed-orig', lineNumber: 2, description: 'Panel',
        qty: 4, units: 'ea', price: 50, total: 200, freeform_kind: null,
        coItem: null, estLine: { line_item_id: 2 },
      },
    ];
    const { getByText, container } = render(COLineItemsSection, {
      props: { rows, estimateLines: [{ line_item_id: 2 }], canEdit: false },
    });
    expect(getByText('Material')).toBeInTheDocument();
    expect(container.querySelectorAll('.kind-badge').length).toBe(1);
  });

  it('renders no badge when the row has no freeform_kind (catalog/service/adjustment line)', () => {
    const rows = [{
      kind: 'unchanged', lineNumber: 1, description: 'PLY 3/4"',
      qty: 2, units: 'ea', price: 30, total: 60, freeform_kind: null,
      coItem: null, estLine: { line_item_id: 1 },
    }];
    const { container } = render(COLineItemsSection, {
      props: { rows, estimateLines: [{ line_item_id: 1 }], canEdit: false },
    });
    expect(container.querySelector('.kind-badge')).toBeNull();
  });
});
