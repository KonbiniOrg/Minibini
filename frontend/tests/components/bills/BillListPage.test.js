import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, findByText } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => {} }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import BillListPage from '@/routes/bills/BillListPage.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('BillListPage balance', () => {
  it('renders the API balance verbatim', async () => {
    api.get.mockResolvedValue({ results: [
      { bill_id: 1, status: 'partly_paid', vendor_name: 'Acme', balance: '70.00', total: '100.00' },
    ], count: 1 });
    const { container } = render(BillListPage);
    expect(await findByText(container, /70\.00/)).toBeInTheDocument();
  });
});

describe('BillListPage', () => {
  it('renders bill rows from the API', async () => {
    user.set({ username: 'fin', permissions: ['can_manage_financials'] });
    api.get.mockResolvedValue({
      count: 1, next: null, previous: null,
      results: [{
        bill_id: 7, vendor_invoice_number: 'V-7', vendor_name: 'Acme',
        po_number: null, status: 'received', received_date: null,
        due_date: '2026-07-01T00:00:00Z', total: '50.00', balance: '50.00',
      }],
    });
    const { container } = render(BillListPage);
    expect(await findByText(container, 'V-7')).toBeInTheDocument();
    expect(await findByText(container, 'Acme')).toBeInTheDocument();
    expect(api.get.mock.calls[0][0]).toContain('status=open');
  });

  it('shows New Bill for financials users', async () => {
    user.set({ username: 'fin', permissions: ['can_manage_financials'] });
    api.get.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    const { findByText: fbt } = render(BillListPage);
    expect(await fbt('New Bill')).toBeInTheDocument();
  });

  it('hides New Bill for non-financials users', async () => {
    user.set({ username: 'worker', permissions: [] });
    api.get.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    const { queryByText } = render(BillListPage);
    // allow the initial load to settle
    await new Promise((r) => setTimeout(r, 0));
    expect(queryByText('New Bill')).not.toBeInTheDocument();
  });
});
