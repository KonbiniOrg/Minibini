import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import LineItemTable from '@/components/LineItemTable.svelte';

const CATEGORIES = [{ id: 10, code: 'LAB', name: 'Labor', taxable: false }];

function makeLine(overrides = {}) {
  return {
    line_item_id: 1,
    line_number: 1,
    description: 'Hand-authored line',
    qty: 1,
    price: '30.00',
    units: 'none',
    accounting_category: 10,
    adjustment_service: null,
    freeform_kind: null,
    sources: [],
    ...overrides,
  };
}

describe('LineItemTable kind badges', () => {
  it('shows a Work badge for a freeform_kind=work line', () => {
    const { container, getByText } = render(LineItemTable, {
      props: { lineItems: [makeLine({ freeform_kind: 'work' })], categories: CATEGORIES },
    });
    const badge = container.querySelector('.kind-badge.kind-work');
    expect(badge).toBeTruthy();
    expect(getByText('Work')).toBeInTheDocument();
  });

  it('shows a Material badge for a freeform_kind=material line', () => {
    const { container, getByText } = render(LineItemTable, {
      props: { lineItems: [makeLine({ freeform_kind: 'material' })], categories: CATEGORIES },
    });
    const badge = container.querySelector('.kind-badge.kind-material');
    expect(badge).toBeTruthy();
    expect(getByText('Material')).toBeInTheDocument();
  });

  it('shows a Fee/Credit badge for a freeform_kind=fee line', () => {
    const { container, getByText } = render(LineItemTable, {
      props: { lineItems: [makeLine({ freeform_kind: 'fee' })], categories: CATEGORIES },
    });
    const badge = container.querySelector('.kind-badge.kind-fee');
    expect(badge).toBeTruthy();
    expect(getByText(/fee.?credit/i)).toBeInTheDocument();
  });

  it('shows no kind badge for a catalog/service line (freeform_kind null)', () => {
    const { container } = render(LineItemTable, {
      props: { lineItems: [makeLine({ freeform_kind: null })], categories: CATEGORIES },
    });
    expect(container.querySelector('.kind-badge')).toBeNull();
  });

  it('still renders the adjustment badge (not a kind badge) for an adjustment line', () => {
    const adjLine = makeLine({
      description: 'Rush 15%',
      adjustment_service: 1,
      adjustment_service_detail: { name: 'Rush', rate: '15.00', algorithm: 'percentage' },
      adjustment_target_categories: [],
      freeform_kind: null,
    });
    const { container } = render(LineItemTable, {
      props: { lineItems: [adjLine], categories: CATEGORIES },
    });
    expect(container.querySelector('.adj-badge')).toBeTruthy();
    expect(container.querySelector('.kind-badge')).toBeNull();
  });
});
