import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('svelte-spa-router', () => ({ link: () => ({}), push: vi.fn() }));
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import PurchaseOrderDetail from '@/components/purchaseorders/PurchaseOrderDetail.svelte';

beforeEach(() => api.get.mockReset());

describe('PO detail billed status', () => {
  it('shows billed total vs po total', () => {
    const { container } = render(PurchaseOrderDetail, {
      props: {
        po: {
          po_id: 5, po_number: 'PO-1', status: 'received_in_full', line_items: [],
          billed_total: '120.00', po_total: '200.00', is_fully_billed: false,
        },
      },
    });
    expect(container.textContent).toMatch(/120\.00 \/ \$200\.00/);
  });

  it('shows fully billed marker when is_fully_billed is true', () => {
    const { container } = render(PurchaseOrderDetail, {
      props: {
        po: {
          po_id: 5, po_number: 'PO-1', status: 'received_in_full', line_items: [],
          billed_total: '200.00', po_total: '200.00', is_fully_billed: true,
        },
      },
    });
    expect(container.textContent).toMatch(/200\.00 \/ \$200\.00/);
    expect(container.textContent).toMatch(/fully billed/);
  });

  it('shows a Create Bill link for a billable PO when user can manage financials', () => {
    const { getByText } = render(PurchaseOrderDetail, {
      props: {
        po: { po_id: 5, po_number: 'PO-1', status: 'issued', line_items: [],
              billed_total: '0.00', po_total: '200.00', is_fully_billed: false, bills: [] },
        canManageFinancials: true,
      },
    });
    const link = getByText('Create Bill');
    expect(link.getAttribute('href')).toBe('#/bills/new?po=5');
  });

  it('hides Create Bill without financials permission', () => {
    const { queryByText } = render(PurchaseOrderDetail, {
      props: {
        po: { po_id: 5, po_number: 'PO-1', status: 'issued', line_items: [],
              billed_total: '0.00', po_total: '200.00', is_fully_billed: false, bills: [] },
        canManageFinancials: false,
      },
    });
    expect(queryByText('Create Bill')).toBeNull();
  });

  it('hides Create Bill on a draft PO (can not bill a draft)', () => {
    const { queryByText } = render(PurchaseOrderDetail, {
      props: {
        po: { po_id: 5, po_number: 'PO-1', status: 'draft', line_items: [],
              billed_total: '0.00', po_total: '200.00', is_fully_billed: false, bills: [] },
        canManageFinancials: true,
      },
    });
    expect(queryByText('Create Bill')).toBeNull();
  });

  it('links to associated bills', () => {
    const { getByText } = render(PurchaseOrderDetail, {
      props: {
        po: { po_id: 5, po_number: 'PO-1', status: 'received_in_full', line_items: [],
              billed_total: '50.00', po_total: '200.00', is_fully_billed: false,
              bills: [{ bill_id: 9, vendor_invoice_number: 'V-9', status: 'received' }] },
        canManageFinancials: true,
      },
    });
    expect(getByText('V-9').getAttribute('href')).toBe('#/bills/9');
  });
});
