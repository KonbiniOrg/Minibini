import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import { getJobWs, rememberSection } from '@/stores/jobWorkspace.js';
import JobInvoicePage from '@/routes/jobs/JobInvoicePage.svelte';

const job = { job_id: 3, job_number: 'JOB-3', name: 'Widget', status: 'in_progress', contact: null, can_manage: true, tasks: [], materials: [] };

function inv(id, created, status = 'draft') {
  return {
    invoice_id: id, invoice_number: `INV-${id}`, display_number: `INV-${id}`, job: 3, status,
    created_date: created, sent_date: null, due_date: null, closed_date: null,
    is_late: false, qbo_id: null, qbo_payment_status: null, qbo_amount_paid: null,
    job_has_other_invoices: false, line_items: [],
  };
}

function mockApi({ invoices = [], byId = {} } = {}) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.includes('/emails/')) return Promise.resolve({ results: [] });
    if (url.includes('/deliverables/')) return Promise.resolve([]);
    if (url.startsWith('/api/invoices/?job=')) return Promise.resolve({ results: invoices });
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [] });
    const m = url.match(/^\/api\/invoices\/(\d+)\/$/);
    if (m && byId[m[1]]) return Promise.resolve(byId[m[1]]);
    if (url === '/api/jobs/3/') return Promise.resolve(job);
    return Promise.resolve(null);
  });
}

beforeEach(() => {
  localStorage.clear();
  window.location.hash = '';
});

describe('JobInvoicePage document resolution', () => {
  it('uses the URL docId when present', async () => {
    const i1 = inv(7, '2026-01-01T00:00:00Z');
    const i2 = inv(8, '2026-01-02T00:00:00Z');
    mockApi({ invoices: [i1, i2], byId: { 7: i1, 8: i2 } });

    const { findByText } = render(JobInvoicePage, {
      props: { params: { jobId: '3', docId: '7' } },
    });

    expect(await findByText('Invoice: INV-7')).toBeInTheDocument();
  });

  it('falls back to the remembered doc on a bare route', async () => {
    const i1 = inv(7, '2026-01-01T00:00:00Z');
    const i2 = inv(8, '2026-01-02T00:00:00Z');
    mockApi({ invoices: [i1, i2], byId: { 7: i1, 8: i2 } });
    rememberSection('3', 'invoice', '7');

    const { findByText } = render(JobInvoicePage, {
      props: { params: { jobId: '3' } },
    });

    expect(await findByText('Invoice: INV-7')).toBeInTheDocument();
  });

  it('falls back to the latest invoice when nothing is remembered', async () => {
    const i1 = inv(7, '2026-01-01T00:00:00Z');
    const i2 = inv(8, '2026-01-02T00:00:00Z');
    mockApi({ invoices: [i1, i2], byId: { 7: i1, 8: i2 } });

    const { findByText } = render(JobInvoicePage, {
      props: { params: { jobId: '3' } },
    });

    expect(await findByText('Invoice: INV-8')).toBeInTheDocument();
  });

  it('ignores a remembered doc id that is no longer in the job\'s invoice list', async () => {
    const i1 = inv(7, '2026-01-01T00:00:00Z');
    const i2 = inv(8, '2026-01-02T00:00:00Z');
    mockApi({ invoices: [i1, i2], byId: { 7: i1, 8: i2 } });
    rememberSection('3', 'invoice', '999');

    const { findByText } = render(JobInvoicePage, {
      props: { params: { jobId: '3' } },
    });

    expect(await findByText('Invoice: INV-8')).toBeInTheDocument();
  });

  it('normalizes the URL to the resolved doc via replaceState on a bare route', async () => {
    const i1 = inv(7, '2026-01-01T00:00:00Z');
    mockApi({ invoices: [i1], byId: { 7: i1 } });

    render(JobInvoicePage, { props: { params: { jobId: '3' } } });

    await waitFor(() => expect(window.location.hash).toBe('#/jobs/3/invoice/7'));
    expect(getJobWs('3').sections.invoice).toBe('7');
  });

  it('shows the gated empty state when the job has no invoices', async () => {
    mockApi({ invoices: [] });
    const { findByRole } = render(JobInvoicePage, { props: { params: { jobId: '3' } } });
    expect(await findByRole('button', { name: /start invoice/i })).toBeInTheDocument();
  });
});

describe('JobInvoicePage doc-subnav navigation (no job-context refetch)', () => {
  it('does not refetch the job or invoice list when only docId changes', async () => {
    const i1 = inv(7, '2026-01-01T00:00:00Z');
    const i2 = inv(8, '2026-01-02T00:00:00Z');
    mockApi({ invoices: [i1, i2], byId: { 7: i1, 8: i2 } });

    const { findByText, rerender } = render(JobInvoicePage, {
      props: { params: { jobId: 3, docId: '7' } },
    });
    expect(await findByText('Invoice: INV-7')).toBeInTheDocument();

    // Fresh params object, same jobId — this is what svelte-spa-router hands
    // the still-mounted component on every doc-subnav navigation.
    await rerender({ params: { jobId: 3, docId: '8' } });
    expect(await findByText('Invoice: INV-8')).toBeInTheDocument();

    const jobFetches = api.get.mock.calls.filter(([url]) => url === '/api/jobs/3/');
    const invoiceListFetches = api.get.mock.calls.filter(([url]) => url.startsWith('/api/invoices/?job='));

    expect(jobFetches).toHaveLength(1);
    expect(invoiceListFetches).toHaveLength(2);
  });
});
