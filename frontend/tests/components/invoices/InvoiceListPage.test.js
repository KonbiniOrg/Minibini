import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, findByText } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => {} }));

import { api } from '@/lib/api.js';
import InvoiceListPage from '@/routes/invoices/InvoiceListPage.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('InvoiceListPage', () => {
  it('renders invoice rows from the API', async () => {
    api.get.mockResolvedValue({
      count: 1, next: null, previous: null,
      results: [{
        invoice_id: 42, invoice_number: 'INV-2026-0001', customer_name: 'Acme Corp',
        job: 10, job_number: 'JOB-2026-0001', status: 'open',
        sent_date: '2026-05-01T00:00:00Z', due_date: '2026-05-31',
        is_late: false, total: '500.00', amount_paid: '0.00', balance: '500.00',
      }],
    });
    const { container } = render(InvoiceListPage);
    expect(await findByText(container, 'INV-2026-0001')).toBeInTheDocument();
    expect(await findByText(container, 'Acme Corp')).toBeInTheDocument();
  });

  it('defaults to status=open and ordering=due_date on the first API call', async () => {
    api.get.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });
    render(InvoiceListPage);
    // wait for the effect to fire
    await new Promise((r) => setTimeout(r, 0));
    const url = api.get.mock.calls[0][0];
    expect(url).toContain('status=open');
    expect(url).toContain('ordering=due_date');
  });
});
