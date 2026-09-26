import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import PurchaseOrderList from '@/components/purchaseorders/PurchaseOrderList.svelte';

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
