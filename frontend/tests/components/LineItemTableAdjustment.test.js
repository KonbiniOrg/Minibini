import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import LineItemTable from '@/components/LineItemTable.svelte';

const CATEGORIES = [
  { id: 10, code: 'LAB', name: 'Labor', taxable: false },
  { id: 20, code: 'MAT', name: 'Materials', taxable: true },
];

const ADJUSTMENT_SERVICE = {
  service_price_id: 1,
  name: 'Rush',
  algorithm: 'percentage',
  rate: '15.00',
};

function makeAdjLine(overrides = {}) {
  return {
    line_item_id: 99,
    line_number: 2,
    description: 'Rush 15%',
    qty: 1,
    price: '30.00',
    units: 'none',
    accounting_category: null,
    adjustment_service: ADJUSTMENT_SERVICE,
    target_categories: [{ id: 10, name: 'Labor', code: 'LAB' }],
    sources: [],
    ...overrides,
  };
}

function makeRegularLine() {
  return {
    line_item_id: 1,
    line_number: 1,
    description: 'Widget',
    qty: 1,
    price: '100.00',
    units: 'none',
    accounting_category: 10,
    adjustment_service: null,
    target_categories: [],
    sources: [],
  };
}

describe('LineItemTable adjustment row rendering', () => {
  it('shows an adjustment badge for lines with adjustment_service', () => {
    const lineItems = [makeRegularLine(), makeAdjLine()];
    const { getByText } = render(LineItemTable, {
      props: { lineItems, categories: CATEGORIES },
    });
    // Badge should show percent and service name
    expect(getByText(/15%.*Rush|Rush.*15%/i)).toBeInTheDocument();
  });

  it('shows target category names in the badge when present', () => {
    const lineItems = [makeAdjLine()];
    const { getByText } = render(LineItemTable, {
      props: { lineItems, categories: CATEGORIES },
    });
    // Should mention the target category
    expect(getByText(/Labor/i)).toBeInTheDocument();
  });

  it('shows Recalculate button for adjustment line when canEdit is true', () => {
    const onRecalculate = vi.fn();
    const lineItems = [makeAdjLine()];
    const { getByRole } = render(LineItemTable, {
      props: { lineItems, categories: CATEGORIES, canEdit: true, onRecalculate },
    });
    expect(getByRole('button', { name: /recalculate/i })).toBeInTheDocument();
  });

  it('does NOT show Recalculate button when canEdit is false', () => {
    const lineItems = [makeAdjLine()];
    const { queryByRole } = render(LineItemTable, {
      props: { lineItems, categories: CATEGORIES, canEdit: false },
    });
    expect(queryByRole('button', { name: /recalculate/i })).not.toBeInTheDocument();
  });

  it('does NOT show Recalculate button for a regular (non-adjustment) line even when canEdit', () => {
    const onRecalculate = vi.fn();
    const lineItems = [makeRegularLine()];
    const { queryByRole } = render(LineItemTable, {
      props: { lineItems, categories: CATEGORIES, canEdit: true, onRecalculate },
    });
    expect(queryByRole('button', { name: /recalculate/i })).not.toBeInTheDocument();
  });

  it('calls onRecalculate with the line item when Recalculate is clicked', async () => {
    const { fireEvent } = await import('@testing-library/svelte');
    const onRecalculate = vi.fn();
    const adjLine = makeAdjLine();
    const { getByRole } = render(LineItemTable, {
      props: { lineItems: [adjLine], categories: CATEGORIES, canEdit: true, onRecalculate },
    });
    await fireEvent.click(getByRole('button', { name: /recalculate/i }));
    expect(onRecalculate).toHaveBeenCalledWith(adjLine);
  });
});
