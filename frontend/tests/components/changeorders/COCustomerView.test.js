import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import COCustomerView from '@/components/changeorders/COCustomerView.svelte';

// A representative amended-agreement `rows` slice: one untouched baseline
// line (must be omitted — this is a delta document, not the whole
// agreement), one replaced line, one removed line, one added line.
const ROWS = [
  { kind: 'agreement', line: { description: 'Untouched', qty: '1', units: 'none', price: '10.00', amount: '10.00' } },
  {
    kind: 'replaced', co_line_id: 10, co_index: 1,
    line: { description: 'New price', qty: '2', units: 'hr', price: '60.00', amount: '120.00' },
    original: { description: 'Old price', qty: '2', units: 'hr', price: '50.00', amount: '100.00' },
  },
  {
    kind: 'removed', co_line_id: 11,
    original: { description: 'Dropped line', qty: '1', units: 'none', price: '30.00', amount: '30.00' },
  },
  {
    kind: 'added', co_line_id: 12, co_index: 2,
    line: { description: 'New line', qty: '3', units: 'none', price: '25.00', amount: '75.00' },
  },
];

describe('COCustomerView', () => {
  it('renders the "Change Order {number}" title', () => {
    const { getByText } = render(COCustomerView, {
      props: { title: 'Change Order CO-3', rows: [], coDelta: '0.00', revisedTotal: '0.00' },
    });
    expect(getByText('Change Order CO-3')).toBeInTheDocument();
  });

  it('shows only the changed lines — an untouched "agreement" row is omitted', () => {
    const { queryByText } = render(COCustomerView, {
      props: { title: 'CO', rows: ROWS, coDelta: '65.00', revisedTotal: '295.00' },
    });
    expect(queryByText('Untouched')).toBeNull();
  });

  it('shows a replaced line as the revised description with a new-minus-old delta amount', () => {
    const { getByText, queryByText } = render(COCustomerView, {
      props: { title: 'CO', rows: ROWS, coDelta: '65.00', revisedTotal: '295.00' },
    });
    expect(getByText('New price')).toBeInTheDocument();
    expect(queryByText('Old price')).toBeNull();
    // delta = 120.00 - 100.00 = 20.00
    expect(getByText('$20.00')).toBeInTheDocument();
  });

  it('shows a removed line as the original with its amount negated', () => {
    const { getByText } = render(COCustomerView, {
      props: { title: 'CO', rows: ROWS, coDelta: '65.00', revisedTotal: '295.00' },
    });
    expect(getByText('Dropped line')).toBeInTheDocument();
    expect(getByText('-$30.00')).toBeInTheDocument();
  });

  it('shows an added line at its own full amount', () => {
    const { getByText } = render(COCustomerView, {
      props: { title: 'CO', rows: ROWS, coDelta: '65.00', revisedTotal: '295.00' },
    });
    expect(getByText('New line')).toBeInTheDocument();
    expect(getByText('$75.00')).toBeInTheDocument();
  });

  it('shows the "Change total" and "Revised agreement total" footer rows', () => {
    const { getByText } = render(COCustomerView, {
      props: { title: 'CO', rows: ROWS, coDelta: '65.00', revisedTotal: '295.00' },
    });
    expect(getByText('Change total')).toBeInTheDocument();
    expect(getByText('$65.00')).toBeInTheDocument();
    expect(getByText('Revised agreement total')).toBeInTheDocument();
    expect(getByText('$295.00')).toBeInTheDocument();
  });

  it('renders a negative change total with a leading minus sign', () => {
    const { getByText } = render(COCustomerView, {
      props: { title: 'CO', rows: [], coDelta: '-42.50', revisedTotal: '57.50' },
    });
    expect(getByText('-$42.50')).toBeInTheDocument();
  });
});
