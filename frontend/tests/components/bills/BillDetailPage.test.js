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

  it('hides Edit header for non-financials user and shows it for financials user on a draft bill', async () => {
    // Non-financials user: Edit header absent
    user.set({ username: 'worker', permissions: [] });
    api.get.mockImplementation((url) => {
      if (url.includes('/api/accounting-categories/')) return Promise.resolve({ results: [] });
      return Promise.resolve(DRAFT_BILL);
    });
    const { container: containerNonFin, unmount } = render(BillDetailPage, {
      props: { params: { id: '1' } },
    });
    await findByText(containerNonFin, 'V-DRAFT'); // wait for load to settle
    expect(queryByText(containerNonFin, 'Edit header')).toBeNull();
    unmount();

    // Financials user: Edit header present
    user.set({ username: 'fin', permissions: ['can_manage_financials'] });
    const { container: containerFin } = render(BillDetailPage, {
      props: { params: { id: '1' } },
    });
    expect(await findByText(containerFin, 'Edit header')).toBeInTheDocument();
  });

  it('Cancel Bill button is disabled without a reason and enabled after typing one', async () => {
    api.get.mockImplementation((url) => {
      if (url.includes('/api/accounting-categories/')) return Promise.resolve({ results: [] });
      return Promise.resolve(RECEIVED_BILL);
    });
    user.set({ username: 'fin', permissions: ['can_manage_financials'] });
    const { container } = render(BillDetailPage, { props: { params: { id: '2' } } });
    const cancelBtn = await findByText(container, 'Cancel Bill');
    expect(cancelBtn).toBeDisabled();

    // Type a reason into the textbox
    const reasonInput = container.querySelector('input[type="text"][placeholder="Enter reason…"]');
    reasonInput.value = 'Duplicate invoice';
    reasonInput.dispatchEvent(new Event('input'));
    await new Promise((r) => setTimeout(r, 0)); // flush Svelte reactivity

    expect(cancelBtn).not.toBeDisabled();
  });

  it('renders a PO link when po_number is set and no link when absent', async () => {
    const billWithPO = {
      ...DRAFT_BILL,
      bill_id: 4,
      po_number: 'PO-2026-0001',
      purchase_order: 42,
    };
    api.get.mockImplementation((url) => {
      if (url.includes('/api/accounting-categories/')) return Promise.resolve({ results: [] });
      return Promise.resolve(billWithPO);
    });
    const { container: containerWithPO } = render(BillDetailPage, {
      props: { params: { id: '4' } },
    });
    const poLink = await findByText(containerWithPO, 'PO-2026-0001');
    expect(poLink.tagName).toBe('A');
    expect(poLink.getAttribute('href')).toBe('#/purchase-orders/42');

    // Bill without a PO: link absent
    api.get.mockImplementation((url) => {
      if (url.includes('/api/accounting-categories/')) return Promise.resolve({ results: [] });
      return Promise.resolve(DRAFT_BILL); // po_number: null
    });
    const { container: containerNoPO } = render(BillDetailPage, {
      props: { params: { id: '1' } },
    });
    await findByText(containerNoPO, 'V-DRAFT'); // wait for load
    expect(queryByText(containerNoPO, 'PO-2026-0001')).toBeNull();
  });
});
