import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock('svelte-spa-router', () => ({
  link: () => {},
  push: vi.fn(),
}));
vi.mock('@/stores/permissions.js', () => {
  const { readable } = require('svelte/store');
  return { canManageFinancials: readable(true) };
});

import { api } from '@/lib/api.js';
import InvoiceDetailPage from '@/routes/invoices/InvoiceDetailPage.svelte';

const ADJ_SERVICE = { rate_scheme_id: 2, name: 'Late Fee', algorithm: 'percentage', rate: '5.00' };

function makeInvoice(overrides = {}) {
  return {
    invoice_id: 3,
    invoice_number: 'INV-3',
    job: 9,
    status: 'draft',
    created_date: '2026-01-01T00:00:00Z',
    sent_date: null,
    due_date: null,
    closed_date: null,
    is_late: false,
    qbo_id: null,
    qbo_payment_status: null,
    qbo_amount_paid: null,
    line_items: [],
    ...overrides,
  };
}

function mockApi(invoice) {
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === `/api/invoices/${invoice.invoice_id}/`) {
      return Promise.resolve({ ...invoice });
    }
    if (url.startsWith('/api/jobs/')) {
      return Promise.resolve({ job_id: 9, job_number: 'JOB-9', name: 'Job', contact: null, tasks: [], materials: [] });
    }
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [] });
    if (url.includes('rate-schemes')) return Promise.resolve({ results: [ADJ_SERVICE] });
    return Promise.resolve({});
  });
  api.post.mockResolvedValue({ line_item_id: 88 });
}

beforeEach(() => {
  api.post?.mockReset?.();
  api.patch?.mockReset?.();
  api.delete?.mockReset?.();
});

describe('InvoiceDetailPage adjustment affordances', () => {
  it('shows "Add Adjustment" on a draft invoice when canManageFinancials', async () => {
    mockApi(makeInvoice({ status: 'draft' }));
    const { findByText } = render(InvoiceDetailPage, {
      props: { params: { id: '3' } },
    });
    expect(await findByText('Add Adjustment')).toBeInTheDocument();
  });

  it('does NOT show "Add Adjustment" on a non-draft invoice', async () => {
    mockApi(makeInvoice({ status: 'open' }));
    const { findByText, queryByText } = render(InvoiceDetailPage, {
      props: { params: { id: '3' } },
    });
    await findByText('Line Items');
    expect(queryByText('Add Adjustment')).not.toBeInTheDocument();
  });

  it('opens AdjustmentModal when "Add Adjustment" is clicked', async () => {
    mockApi(makeInvoice({ status: 'draft' }));
    const { findByText, findByRole } = render(InvoiceDetailPage, {
      props: { params: { id: '3' } },
    });
    await fireEvent.click(await findByText('Add Adjustment'));
    expect(await findByRole('dialog')).toBeInTheDocument();
  });

  it('does NOT show a Recalculate button on a draft adjustment line (auto-recompute)', async () => {
    const adjLine = {
      line_item_id: 88, line_number: 1, description: 'Late Fee 5%',
      qty: 1, price: '5.00', units: 'none', accounting_category: null,
      adjustment_service: ADJ_SERVICE, target_categories: [],
      sources: [],
    };
    mockApi(makeInvoice({ status: 'draft', line_items: [adjLine] }));
    const { findByText, queryByRole } = render(InvoiceDetailPage, {
      props: { params: { id: '3' } },
    });
    await findByText('Line Items');
    expect(queryByRole('button', { name: /recalculate/i })).not.toBeInTheDocument();
  });
});
