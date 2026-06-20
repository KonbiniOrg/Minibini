// frontend/tests/components/BillDetailPoBilling.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, findByText } from '@testing-library/svelte';
vi.mock('svelte-spa-router', () => ({ link: () => ({}), push: vi.fn() }));
vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
// Mock LineItemModal to avoid deep dependency chain
vi.mock('@/components/LineItemModal.svelte', () => ({ default: vi.fn().mockReturnValue(null) }));
import { api } from '@/lib/api.js';
import BillDetailPage from '@/routes/bills/BillDetailPage.svelte';

beforeEach(() => api.get.mockReset());

describe('Bill detail double-bill surfacing', () => {
  it('shows fully-billed warning and prior-bill notice', async () => {
    api.get.mockResolvedValue({
      bill_id: 2, status: 'received', vendor_name: 'Acme', balance: '0.00',
      payments: [], line_items: [], purchase_order: 5, po_number: 'PO-1',
      po_billing: { other_bills: [{ bill_id: 1, vendor_invoice_number: 'A', status: 'received', total: '100.00' }], po_fully_billed: true },
    });
    const { container } = render(BillDetailPage, { props: { params: { id: '2' } } });
    expect(await findByText(container, /fully billed/i)).toBeInTheDocument();
    expect(await findByText(container, /PO already has/i)).toBeInTheDocument();
  });
});
