import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, findByText } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() }, errorMessage: (e, fallback) => e?.message || fallback }));
vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => {} }));

import { api } from '@/lib/api.js';
import InvoiceListPage from '@/routes/invoices/InvoiceListPage.svelte';
import { viewMode } from '@/stores/viewMode.js';

beforeEach(() => { api.get.mockReset(); });

describe('InvoiceListPage', () => {
  it('renders invoice rows from the API', async () => {
    api.get.mockResolvedValue({
      count: 1, next: null, previous: null,
      results: [{
        invoice_id: 42, invoice_number: 'INV-2026-0001', display_number: 'INV-2026-0001', customer_name: 'Acme Corp',
        job: 10, job_number: 'JOB-2026-0001', status: 'open',
        sent_date: '2026-05-01T00:00:00Z', due_date: '2026-05-31',
        is_late: false, total: '500.00', amount_paid: '0.00', balance: '500.00',
      }],
    });
    const { container } = render(InvoiceListPage);
    expect(await findByText(container, 'INV-2026-0001')).toBeInTheDocument();
    expect(await findByText(container, 'Acme Corp')).toBeInTheDocument();
  });

  it('renders the draft placeholder for an unnumbered draft', async () => {
    api.get.mockResolvedValue({
      count: 1, next: null, previous: null,
      results: [{
        invoice_id: 43, invoice_number: null, display_number: 'Draft — JOB-2026-0002',
        customer_name: 'Acme Corp', job: 11, job_number: 'JOB-2026-0002',
        status: 'draft', sent_date: null, due_date: null,
        is_late: false, total: '0.00', amount_paid: '0.00', balance: '0.00',
      }],
    });
    const { container } = render(InvoiceListPage);
    expect(await findByText(container, 'Draft — JOB-2026-0002')).toBeInTheDocument();
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

  it('shows a DEPOSIT pill next to the status', async () => {
    api.get.mockResolvedValue({
      count: 1, next: null, previous: null,
      results: [{
        invoice_id: 44, invoice_number: 'INV-2026-0003', display_number: 'INV-2026-0003', customer_name: 'Acme Corp',
        job: 12, job_number: 'JOB-2026-0003', status: 'open',
        sent_date: '2026-05-01T00:00:00Z', due_date: '2026-05-31',
        is_late: false, total: '500.00', amount_paid: '0.00', balance: '500.00',
        is_deposit: true,
      }],
    });
    const { container } = render(InvoiceListPage);
    expect(await findByText(container, 'DEPOSIT')).toBeInTheDocument();
  });

  it('omits the DEPOSIT pill for a non-deposit invoice', async () => {
    api.get.mockResolvedValue({
      count: 1, next: null, previous: null,
      results: [{
        invoice_id: 45, invoice_number: 'INV-2026-0004', display_number: 'INV-2026-0004', customer_name: 'Acme Corp',
        job: 13, job_number: 'JOB-2026-0004', status: 'open',
        sent_date: '2026-05-01T00:00:00Z', due_date: '2026-05-31',
        is_late: false, total: '500.00', amount_paid: '0.00', balance: '500.00',
        is_deposit: false,
      }],
    });
    const { container, queryByText } = render(InvoiceListPage);
    await findByText(container, 'INV-2026-0004');
    expect(queryByText('DEPOSIT')).toBeNull();
  });
});

describe('InvoiceListPage — DataTable', () => {
  const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());
  const payload = {
    count: 1, next: null, previous: null,
    results: [{
      invoice_id: 42, invoice_number: 'INV-1', display_number: 'INV-1', customer_name: 'Acme Corp',
      job: 10, job_number: 'JOB-10', status: 'open', is_deposit: true,
      sent_date: '2026-05-01T00:00:00Z', due_date: '2026-05-31', is_late: true,
      total: '500.00', amount_paid: '100.00', balance: '400.00',
    }],
  };
  const ALL = ['Invoice #', 'Job', 'Customer', 'Status', 'Sent', 'Due', 'Amount', 'Paid', 'Balance'];

  it('renders the same nine columns in lite and full, with money right-aligned and data-col stamped', async () => {
    api.get.mockResolvedValue(payload);
    viewMode.set('lite');
    const { container } = render(InvoiceListPage);
    await findByText(container, 'INV-1');
    const table = container.querySelector('table.data-table');
    expect(headersOf(table)).toEqual(ALL);
    expect(table.querySelector('td[data-col="balance"]').getAttribute('style')).toMatch(/text-align:\s*right/);
    expect(table.querySelector('td[data-col="status"]').textContent).toContain('DEPOSIT');
    expect(table.querySelector('td[data-col="due"]').textContent).toContain('⚠️');
    expect(table.querySelector('td[data-col="job"] a')).toHaveAttribute('href', '#/jobs/10');
    viewMode.set('full');
    const { container: c2 } = render(InvoiceListPage);
    await findByText(c2, 'INV-1');
    expect(headersOf(c2.querySelector('table.data-table'))).toEqual(ALL);
  });
});
