import { render } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import LineItemTable from '../src/components/LineItemTable.svelte';

const lineItems = [{
  line_item_id: 1, line_number: 1, description: 'Bundle', qty: 1, price: '30.00',
  units: 'none', accounting_category: null,
  sources: [
    { source_type: 'task', source_pk: 5, description: 'Cut (Hourly)', computed_amount: '20.00' },
    { source_type: 'material', source_pk: 9, description: 'Steel sheet', computed_amount: '10.00' },
  ],
}];

const categories = [
  { id: 7, name: 'Labor', taxable: false },
];

describe('LineItemTable source detail', () => {
  it('lists each source description and amount when showSource', () => {
    const { getByText } = render(LineItemTable, { props: { lineItems, showSource: true } });
    expect(getByText(/Cut \(Hourly\)/)).toBeTruthy();
    expect(getByText(/Steel sheet/)).toBeTruthy();
    expect(getByText(/\$10\.00/)).toBeTruthy();
  });

  it('shows "No source" for a line with no sources', () => {
    const bare = [{ ...lineItems[0], sources: [], inventory_item: null }];
    const { getByText } = render(LineItemTable, { props: { lineItems: bare, showSource: true } });
    expect(getByText('No source')).toBeTruthy();
  });
});

describe('LineItemTable negative (fee/credit) price formatting', () => {
  it('puts the minus sign before the dollar sign, not "$-"', () => {
    const items = [{
      line_item_id: 2, line_number: 1, description: 'Loyalty credit', qty: 1,
      price: '-80.00', units: 'none', accounting_category: null, freeform_kind: 'fee',
    }];
    const { getAllByText, queryByText } = render(LineItemTable, { props: { lineItems: items } });
    expect(getAllByText('-$80.00').length).toBeGreaterThan(0);
    expect(queryByText('$-80.00')).toBeNull();
  });
});

describe('LineItemTable category cell — needs-category flag', () => {
  it('flags the category cell when canEdit and accounting_category is null', () => {
    const items = [{ ...lineItems[0], accounting_category: null }];
    const { getByText, container } = render(LineItemTable, {
      props: { lineItems: items, categories, canEdit: true },
    });
    expect(getByText(/needs category/i)).toBeTruthy();
    const flaggedCell = container.querySelector('td.needs-category');
    expect(flaggedCell).toBeTruthy();
  });

  it('shows the category name (no flag) when canEdit and accounting_category is set', () => {
    const items = [{ ...lineItems[0], accounting_category: 7 }];
    const { getByText, container } = render(LineItemTable, {
      props: { lineItems: items, categories, canEdit: true },
    });
    expect(getByText('Labor')).toBeTruthy();
    const flaggedCell = container.querySelector('td.needs-category');
    expect(flaggedCell).toBeNull();
  });

  it('does not flag the cell when !canEdit even if accounting_category is null', () => {
    const items = [{ ...lineItems[0], accounting_category: null }];
    const { container, queryByText } = render(LineItemTable, {
      props: { lineItems: items, categories, canEdit: false },
    });
    expect(queryByText(/needs category/i)).toBeNull();
    const flaggedCell = container.querySelector('td.needs-category');
    expect(flaggedCell).toBeNull();
  });
});
