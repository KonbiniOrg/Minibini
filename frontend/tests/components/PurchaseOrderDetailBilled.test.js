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
});
