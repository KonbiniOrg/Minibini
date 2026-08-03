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
