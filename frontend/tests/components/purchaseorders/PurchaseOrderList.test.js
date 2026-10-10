import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import PurchaseOrderList from '@/components/purchaseorders/PurchaseOrderList.svelte';
import { viewMode } from '@/stores/viewMode.js';

function po(overrides = {}) {
  return {
    po_id: 1, po_number: 'PO-1', status: 'received_in_full', business_name: 'Acme',
    created_date: '2026-01-01', requested_date: null, line_items: [],
    ...overrides,
  };
}

describe('PurchaseOrderList — awaiting-reconciliation badge', () => {
  it('shows the badge for a PO awaiting reconciliation', () => {
    const { getByText } = render(PurchaseOrderList, {
      props: { purchaseOrders: [po({ awaiting_reconciliation: true })] },
    });
    expect(getByText('Awaiting Reconciliation')).toBeInTheDocument();
  });

  it('does not show the badge otherwise', () => {
    const { queryByText } = render(PurchaseOrderList, {
      props: { purchaseOrders: [po({ awaiting_reconciliation: false })] },
    });
    expect(queryByText('Awaiting Reconciliation')).toBeNull();
  });
});

describe('PurchaseOrderList — DataTable', () => {
  const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());
  const ALL = ['PO #', 'Vendor', 'Status', 'Created', 'Requested', 'Total', ''];

  it('renders the same columns in lite and full with data-col and a right-aligned total', () => {
    viewMode.set('lite');
    const rows = [po({ line_items: [{ qty: 2, price: '3.50' }] })];
    const { container } = render(PurchaseOrderList, { props: { purchaseOrders: rows } });
    const table = container.querySelector('table.data-table');
    expect(headersOf(table)).toEqual(ALL);
    expect(table.querySelector('td[data-col="total"]').textContent.trim()).toBe('$7.00');
    expect(table.querySelector('td[data-col="total"]').getAttribute('style')).toMatch(/text-align:\s*right/);
    viewMode.set('full');
    const { container: c2 } = render(PurchaseOrderList, { props: { purchaseOrders: rows } });
    expect(headersOf(c2.querySelector('table.data-table'))).toEqual(ALL);
  });

  it('renders the PO number as a button that calls onSelect when given', async () => {
    const calls = [];
    const { getByRole } = render(PurchaseOrderList, { props: { purchaseOrders: [po()], onSelect: (p) => calls.push(p) } });
    getByRole('button', { name: 'PO-1' }).click();
    expect(calls).toHaveLength(1);
    expect(calls[0].po_id).toBe(1);
  });

  it('shows "No purchase orders found." for an empty list', () => {
    const { getByText } = render(PurchaseOrderList, { props: { purchaseOrders: [] } });
    expect(getByText('No purchase orders found.')).toBeInTheDocument();
  });
});
