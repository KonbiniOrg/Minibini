import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import COCustomerView from '@/components/changeorders/COCustomerView.svelte';

// A representative amended-agreement `rows` slice: one untouched baseline
// line (shown plain — the customer view displays the WHOLE amended
// agreement, mirroring the portal), one replaced line over its struck
// original, one removed (struck) line, one added line.
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

// originalTotal = 10 + 100 + 30 = 140; revisedTotal = 10 + 120 + 75 = 205.
function props(overrides = {}) {
  return {
    title: 'Change Order CO-3',
    rows: ROWS,
    originalTotal: '140.00',
    coDelta: '65.00',
    revisedTotal: '205.00',
    ...overrides,
  };
}

describe('COCustomerView', () => {
  it('renders the "Change Order {number}" title', () => {
    const { getByText } = render(COCustomerView, {
      props: props({ rows: [], originalTotal: '0.00', coDelta: '0.00', revisedTotal: '0.00' }),
    });
    expect(getByText('Change Order CO-3')).toBeInTheDocument();
  });

  it('shows an untouched "agreement" row plain, at its full amount', () => {
    const { getByText, container } = render(COCustomerView, { props: props() });
    expect(getByText('Untouched')).toBeInTheDocument();
    const row = [...container.querySelectorAll('tbody tr')]
      .find((tr) => tr.textContent.includes('Untouched'));
    expect(row.textContent).toContain('$10.00');
    expect(row.classList.contains('row-unchanged')).toBe(true);
    expect(row.classList.contains('row-changed')).toBe(false);
  });

  it('shows a replaced line tinted above its struck original', () => {
    const { getByText, container } = render(COCustomerView, { props: props() });
    expect(getByText('New price')).toBeInTheDocument();
    expect(getByText('$120.00')).toBeInTheDocument();
    // The struck original is VISIBLE now (portal grammar), styled struck.
    expect(getByText('Old price')).toBeInTheDocument();
    const rows = [...container.querySelectorAll('tbody tr')];
    const newRow = rows.find((tr) => tr.textContent.includes('New price'));
    const origRow = rows.find((tr) => tr.textContent.includes('Old price'));
    expect(newRow.classList.contains('row-changed')).toBe(true);
    expect(origRow.classList.contains('row-changed-orig')).toBe(true);
    // New row renders directly above the struck original.
    expect(rows.indexOf(origRow)).toBe(rows.indexOf(newRow) + 1);
  });

  it('shows a removed line struck, at its original amount', () => {
    const { getByText, container } = render(COCustomerView, { props: props() });
    expect(getByText('Dropped line')).toBeInTheDocument();
    const row = [...container.querySelectorAll('tbody tr')]
      .find((tr) => tr.textContent.includes('Dropped line'));
    expect(row.textContent).toContain('$30.00');
    expect(row.classList.contains('row-removed')).toBe(true);
  });

  it('shows an added line tinted with a "+" tag at its own full amount', () => {
    const { getByText, container } = render(COCustomerView, { props: props() });
    expect(getByText('New line')).toBeInTheDocument();
    expect(getByText('$75.00')).toBeInTheDocument();
    const row = [...container.querySelectorAll('tbody tr')]
      .find((tr) => tr.textContent.includes('New line'));
    expect(row.classList.contains('row-added')).toBe(true);
    expect(row.querySelector('.tag-add')).toBeTruthy();
  });

  it('shows the Previous total / New total / Change footer rows', () => {
    const { getByText } = render(COCustomerView, { props: props() });
    expect(getByText('Previous total')).toBeInTheDocument();
    expect(getByText('$140.00')).toBeInTheDocument();
    expect(getByText('New total')).toBeInTheDocument();
    expect(getByText('$205.00')).toBeInTheDocument();
    expect(getByText('Change')).toBeInTheDocument();
    expect(getByText('+$65.00')).toBeInTheDocument();
  });

  it('renders a negative change with a leading minus sign', () => {
    const { getByText } = render(COCustomerView, {
      props: props({ rows: [], originalTotal: '100.00', coDelta: '-42.50', revisedTotal: '57.50' }),
    });
    expect(getByText('-$42.50')).toBeInTheDocument();
  });
});
