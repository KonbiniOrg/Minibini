import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, findByText, queryByText } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => {} }));
// Mock LineItemModal to avoid its deep dependency chain (modalKeys, UnitsSelect, etc.)
vi.mock('@/components/LineItemModal.svelte', () => ({ default: vi.fn().mockReturnValue(null) }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import BillDetailPage from '@/routes/bills/BillDetailPage.svelte';

const DRAFT_BILL = {
  bill_id: 1,
  vendor_invoice_number: 'V-DRAFT',
  vendor_name: 'Acme Supply',
  po_number: null,
  purchase_order: null,
  status: 'draft',
  due_date: '2026-07-15T00:00:00Z',
  received_date: null,
  paid_date: null,
  balance: '75.00',
  line_items: [
    { line_item_id: 10, line_number: 1, description: 'Widget', qty: '3', units: 'ea', price: '25.00' },
  ],
};

const RECEIVED_BILL = {
  ...DRAFT_BILL,
  bill_id: 2,
  vendor_invoice_number: 'V-RECV',
  status: 'received',
  received_date: '2026-06-10T00:00:00Z',
};

const EMPTY_DRAFT_BILL = {
  ...DRAFT_BILL,
  bill_id: 3,
  vendor_invoice_number: 'V-EMPTY',
  line_items: [],
  balance: '0.00',
};

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  // Default categories response
  api.get.mockImplementation((url) => {
    if (url.includes('/api/accounting-categories/')) return Promise.resolve({ results: [] });
    return Promise.resolve(DRAFT_BILL);
  });
  user.set({ username: 'fin', permissions: ['can_manage_financials'] });
});

describe('BillDetailPage', () => {
  it('renders header fields for a draft bill', async () => {
    api.get.mockImplementation((url) => {
      if (url.includes('/api/accounting-categories/')) return Promise.resolve({ results: [] });
      return Promise.resolve(DRAFT_BILL);
    });
    const { container } = render(BillDetailPage, { props: { params: { id: '1' } } });
    expect(await findByText(container, 'V-DRAFT')).toBeInTheDocument();
    expect(await findByText(container, 'Acme Supply')).toBeInTheDocument();
    expect(await findByText(container, 'draft')).toBeInTheDocument();
  });

  it('shows Mark Received on a draft bill', async () => {
    api.get.mockImplementation((url) => {
      if (url.includes('/api/accounting-categories/')) return Promise.resolve({ results: [] });
      return Promise.resolve(DRAFT_BILL);
    });
    const { container } = render(BillDetailPage, { props: { params: { id: '1' } } });
    expect(await findByText(container, 'Mark Received')).toBeInTheDocument();
  });

  it('shows Mark Paid in Full on a received bill', async () => {
    api.get.mockImplementation((url) => {
      if (url.includes('/api/accounting-categories/')) return Promise.resolve({ results: [] });
      return Promise.resolve(RECEIVED_BILL);
    });
    const { container } = render(BillDetailPage, { props: { params: { id: '2' } } });
    expect(await findByText(container, 'Mark Paid in Full')).toBeInTheDocument();
  });

  it('Mark Received is disabled when no line items', async () => {
    api.get.mockImplementation((url) => {
      if (url.includes('/api/accounting-categories/')) return Promise.resolve({ results: [] });
      return Promise.resolve(EMPTY_DRAFT_BILL);
    });
    const { container } = render(BillDetailPage, { props: { params: { id: '3' } } });
    const btn = await findByText(container, 'Mark Received');
    expect(btn).toBeDisabled();
  });

  it('does not show status actions for non-financials users on a draft bill', async () => {
    user.set({ username: 'worker', permissions: [] });
    api.get.mockImplementation((url) => {
      if (url.includes('/api/accounting-categories/')) return Promise.resolve({ results: [] });
      return Promise.resolve(DRAFT_BILL);
    });
    const { container } = render(BillDetailPage, { props: { params: { id: '1' } } });
    await findByText(container, 'V-DRAFT'); // wait for load
    expect(queryByText(container, 'Mark Received')).toBeNull();
    expect(queryByText(container, 'Delete')).toBeNull();
  });
});
