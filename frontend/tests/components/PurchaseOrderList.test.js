import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import PurchaseOrderList from '@/components/purchaseorders/PurchaseOrderList.svelte';

describe('PurchaseOrderList bill links', () => {
  it('links to an associated bill', () => {
    const { getByText } = render(PurchaseOrderList, {
      props: {
        purchaseOrders: [
          { po_id: 1, po_number: 'PO-1', business_name: 'Acme', status: 'received_in_full',
            line_items: [], bills: [{ bill_id: 9, vendor_invoice_number: 'V-9', status: 'received' }] },
        ],
      },
    });
    expect(getByText('V-9').getAttribute('href')).toBe('#/bills/9');
  });

  it('shows a dash when a PO has no bills', () => {
    const { container } = render(PurchaseOrderList, {
      props: {
        purchaseOrders: [
          { po_id: 2, po_number: 'PO-2', business_name: 'Acme', status: 'issued',
            line_items: [], bills: [] },
        ],
      },
    });
    expect(container.textContent).toContain('—');
  });
});
