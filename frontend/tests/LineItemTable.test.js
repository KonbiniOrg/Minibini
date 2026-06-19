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
