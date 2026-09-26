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

  it('still resolves the name of a category flagged is_fallback (display paths read the unfiltered list)', () => {
    // Pickers (LineItemModal/AddLineForm selects) omit an is_fallback
    // category from their <option> lists, but a line already carrying
    // that category must still show its name here — this table never
    // filters `categories`, it only looks a name up by id.
    const fallbackCategories = [
      { id: 7, name: 'Labor', taxable: false },
      { id: 9, name: 'Fallback', taxable: false, is_fallback: true },
    ];
    const items = [{ ...lineItems[0], accounting_category: 9 }];
    const { getByText, container } = render(LineItemTable, {
      props: { lineItems: items, categories: fallbackCategories, canEdit: true },
    });
    expect(getByText('Fallback')).toBeTruthy();
    const flaggedCell = container.querySelector('td.needs-category');
    expect(flaggedCell).toBeNull();
  });
});
