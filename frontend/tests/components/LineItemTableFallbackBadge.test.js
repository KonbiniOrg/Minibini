import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import LineItemTable from '@/components/LineItemTable.svelte';

// task-owned-money Phase 3, Task 4: invoice line payloads carry
// used_fallback_ac (Task 3, backend). AC name + taxable come from the
// existing `categories` prop LineItemTable already receives — no serializer
// change needed (accounting_category_name/taxable already round-trip via
// the categories list + accounting_category PK).
const CATEGORIES = [
  { id: 10, code: 'UNC', name: 'Uncategorized income', taxable: true },
  { id: 20, code: 'MAT', name: 'Materials', taxable: false },
];

function makeLine(overrides = {}) {
  return {
    line_item_id: 1, line_number: 1, description: 'Flat task', qty: 1, price: '50.00',
    units: 'none', accounting_category: 10, used_fallback_ac: false, sources: [],
    ...overrides,
  };
}

describe('LineItemTable fallback-AC badge (task-owned-money Phase 3, Task 4)', () => {
  it('shows the fallback badge with AC name and taxable status when used_fallback_ac is true', () => {
    const items = [makeLine({ used_fallback_ac: true, accounting_category: 10 })];
    const { getByText } = render(LineItemTable, { props: { lineItems: items, categories: CATEGORIES } });
    expect(getByText('Uncategorized → Uncategorized income · taxable')).toBeInTheDocument();
  });

  it('shows "non-taxable" when the fallback AC is not taxable', () => {
    const items = [makeLine({ used_fallback_ac: true, accounting_category: 20 })];
    const { getByText } = render(LineItemTable, { props: { lineItems: items, categories: CATEGORIES } });
    expect(getByText('Uncategorized → Materials · non-taxable')).toBeInTheDocument();
  });

  it('does not show the badge when used_fallback_ac is false', () => {
    const items = [makeLine({ used_fallback_ac: false, accounting_category: 10 })];
    const { queryByText } = render(LineItemTable, { props: { lineItems: items, categories: CATEGORIES } });
    expect(queryByText(/Uncategorized →/)).not.toBeInTheDocument();
  });

  it('does not show the badge when used_fallback_ac is absent (e.g. estimate lines)', () => {
    const items = [{
      line_item_id: 2, line_number: 1, description: 'Est line', qty: 1, price: '10.00',
      units: 'none', accounting_category: 10, sources: [],
    }];
    const { queryByText } = render(LineItemTable, { props: { lineItems: items, categories: CATEGORIES } });
    expect(queryByText(/Uncategorized →/)).not.toBeInTheDocument();
  });

  it('carries a distinguishing class for styling', () => {
    const items = [makeLine({ used_fallback_ac: true, accounting_category: 10 })];
    const { container } = render(LineItemTable, { props: { lineItems: items, categories: CATEGORIES } });
    expect(container.querySelector('.fallback-badge')).toBeTruthy();
  });

  it('replaces the plain category name with the badge (no duplicate text)', () => {
    const items = [makeLine({ used_fallback_ac: true, accounting_category: 10 })];
    const { container } = render(LineItemTable, { props: { lineItems: items, categories: CATEGORIES } });
    const cell = container.querySelector('td.fallback-flag');
    expect(cell).toBeTruthy();
    expect(cell.textContent.trim()).toBe('Uncategorized → Uncategorized income · taxable');
  });
});
