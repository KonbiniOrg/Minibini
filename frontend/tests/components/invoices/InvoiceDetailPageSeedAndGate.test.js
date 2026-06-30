import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

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

function makeInvoice(overrides = {}) {
  return {
    invoice_id: 5,
    invoice_number: 'INV-5',
    job: 10,
    status: 'draft',
    created_date: '2026-01-01T00:00:00Z',
    sent_date: null,
    due_date: null,
    closed_date: null,
    is_late: false,
    qbo_id: null,
    qbo_payment_status: null,
    qbo_amount_paid: null,
    job_has_other_invoices: false,
    line_items: [],
    ...overrides,
  };
}

function makeLine(overrides = {}) {
  return {
    line_item_id: 1,
    line_number: 1,
    description: 'Some work',
    qty: 1,
    price: '100.00',
    units: 'each',
    accounting_category: { id: 1, name: 'Labor' },
    adjustment_service: null,
    target_categories: [],
    sources: [],
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
      return Promise.resolve({
        job_id: 10, job_number: 'JOB-10', name: 'Test Job',
        contact: null, tasks: [], materials: [],
      });
    }
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [] });
    return Promise.resolve({});
  });
  api.post.mockResolvedValue({ created: 2 });
}

beforeEach(() => {
  api.post?.mockReset?.();
  api.patch?.mockReset?.();
  api.delete?.mockReset?.();
});

// ─── Seed buttons ────────────────────────────────────────────────────────────

describe('InvoiceDetailPage — seed buttons', () => {
  it('shows both seed buttons on a draft invoice with no line items', async () => {
    mockApi(makeInvoice({ status: 'draft', line_items: [] }));
    const { findByText } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    expect(await findByText('Apply everything')).toBeInTheDocument();
    expect(await findByText('Copy from estimate')).toBeInTheDocument();
  });

  it('"Copy from estimate" is enabled when job_has_other_invoices is false', async () => {
    mockApi(makeInvoice({ status: 'draft', line_items: [], job_has_other_invoices: false }));
    const { findByText } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    const btn = await findByText('Copy from estimate');
    expect(btn).not.toBeDisabled();
  });

  it('"Copy from estimate" is disabled when job_has_other_invoices is true', async () => {
    mockApi(makeInvoice({ status: 'draft', line_items: [], job_has_other_invoices: true }));
    const { findByText } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    const btn = await findByText('Copy from estimate');
    expect(btn).toBeDisabled();
  });

  it('"Copy from estimate" has an explanatory title when disabled', async () => {
    mockApi(makeInvoice({ status: 'draft', line_items: [], job_has_other_invoices: true }));
    const { findByText } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    const btn = await findByText('Copy from estimate');
    expect(btn.title).toMatch(/another invoice exists/i);
  });

  it('does NOT show seed buttons on a draft invoice that already has line items', async () => {
    mockApi(makeInvoice({ status: 'draft', line_items: [makeLine()] }));
    const { findByText, queryByText } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    await findByText('Line Items'); // wait for render
    expect(queryByText('Apply everything')).not.toBeInTheDocument();
    expect(queryByText('Copy from estimate')).not.toBeInTheDocument();
  });

  it('does NOT show seed buttons on a non-draft invoice with no line items', async () => {
    mockApi(makeInvoice({ status: 'open', line_items: [] }));
    const { findByText, queryByText } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    await findByText('Line Items');
    expect(queryByText('Apply everything')).not.toBeInTheDocument();
    expect(queryByText('Copy from estimate')).not.toBeInTheDocument();
  });

  it('clicking "Apply everything" calls POST to apply-everything endpoint then reloads', async () => {
    const inv = makeInvoice({ status: 'draft', line_items: [] });
    mockApi(inv);
    const { findByText } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    const btn = await findByText('Apply everything');

    // Set up post to succeed; get returns the same invoice on reload
    api.post.mockResolvedValue({ created: 3 });
    await fireEvent.click(btn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        `/api/invoices/${inv.invoice_id}/apply-everything/`,
        {}
      );
    });
    // loadInvoice() re-fetches the invoice after posting
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(`/api/invoices/${inv.invoice_id}/`);
    });
  });

  it('clicking "Copy from estimate" calls POST to copy-from-estimate endpoint then reloads', async () => {
    const inv = makeInvoice({ status: 'draft', line_items: [], job_has_other_invoices: false });
    mockApi(inv);
    const { findByText } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    const btn = await findByText('Copy from estimate');

    api.post.mockResolvedValue({ created: 2 });
    await fireEvent.click(btn);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        `/api/invoices/${inv.invoice_id}/copy-from-estimate/`,
        {}
      );
    });
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(`/api/invoices/${inv.invoice_id}/`);
    });
  });
});

// ─── Send-gate ───────────────────────────────────────────────────────────────

describe('InvoiceDetailPage — send gate', () => {
  it('shows active Send link when all lines have an accounting_category', async () => {
    const inv = makeInvoice({
      status: 'draft',
      line_items: [
        makeLine({ accounting_category: { id: 1, name: 'Labor' } }),
        makeLine({ line_item_id: 2, line_number: 2, accounting_category: { id: 2, name: 'Material' } }),
      ],
    });
    mockApi(inv);
    const { findByRole } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    // The active Send control is an <a> link (role=link)
    const sendLink = await findByRole('link', { name: /send invoice/i });
    expect(sendLink).toBeInTheDocument();
    expect(sendLink.tagName).toBe('A');
  });

  it('shows active Send link when there are no line items (nothing missing a category)', async () => {
    mockApi(makeInvoice({ status: 'draft', line_items: [] }));
    const { findByRole } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    const sendLink = await findByRole('link', { name: /send invoice/i });
    expect(sendLink).toBeInTheDocument();
  });

  it('shows disabled Send button + note when a line item has no accounting_category', async () => {
    const inv = makeInvoice({
      status: 'draft',
      line_items: [
        makeLine({ accounting_category: { id: 1, name: 'Labor' } }),
        makeLine({ line_item_id: 2, line_number: 2, accounting_category: null }),
      ],
    });
    mockApi(inv);
    const { findByText, queryByRole } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });

    // Active <a> link should not be present
    // (We query by role=link with the send text — should be absent)
    await findByText('Line Items'); // wait for render

    const sendLinkEl = queryByRole('link', { name: /send invoice/i });
    expect(sendLinkEl).not.toBeInTheDocument();

    // Disabled button should be present
    const sendBtn = await findByText('Send Invoice');
    expect(sendBtn.tagName).toBe('BUTTON');
    expect(sendBtn).toBeDisabled();

    // Explanatory note should be present
    expect(await findByText(/assign an accounting category to every line before sending/i)).toBeInTheDocument();
  });

  it('the disabled Send button is a <button>, not an <a>', async () => {
    const inv = makeInvoice({
      status: 'draft',
      line_items: [makeLine({ accounting_category: null })],
    });
    mockApi(inv);
    const { findByText } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    const sendEl = await findByText('Send Invoice');
    expect(sendEl.tagName).toBe('BUTTON');
    expect(sendEl).toBeDisabled();
  });
});

// ─── hasBillables / Show Billables link ──────────────────────────────────────

describe('InvoiceDetailPage — Show Billables link', () => {
  function mockApiWithJob(invoice, jobOverrides = {}) {
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url === `/api/invoices/${invoice.invoice_id}/`) return Promise.resolve({ ...invoice });
      if (url.startsWith('/api/jobs/')) return Promise.resolve({
        job_id: 10, job_number: 'JOB-10', name: 'Test Job',
        contact: null, tasks: [], materials: [], fees: [],
        ...jobOverrides,
      });
      if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [] });
      return Promise.resolve({});
    });
  }

  it('shows "Show Billables" when job has fees (but no tasks or materials)', async () => {
    // hasBillables must include job.fees so the wizard link appears for fee-only jobs.
    mockApiWithJob(makeInvoice({ status: 'draft' }), { fees: [{ id: 1, description: 'Setup Fee' }] });
    const { findByText } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    expect(await findByText('Show Billables')).toBeInTheDocument();
  });

  it('shows "Show Billables" when job has tasks', async () => {
    mockApiWithJob(makeInvoice({ status: 'draft' }), { tasks: [{ id: 1, name: 'Cut' }] });
    const { findByText } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    expect(await findByText('Show Billables')).toBeInTheDocument();
  });

  it('shows "Show Billables" when job has materials', async () => {
    mockApiWithJob(makeInvoice({ status: 'draft' }), { materials: [{ id: 2, description: 'Steel' }] });
    const { findByText } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    expect(await findByText('Show Billables')).toBeInTheDocument();
  });

  it('does NOT show "Show Billables" when job has no tasks, materials, or fees', async () => {
    mockApiWithJob(makeInvoice({ status: 'draft' }), { tasks: [], materials: [], fees: [] });
    const { findByText, queryByText } = render(InvoiceDetailPage, { props: { params: { id: '5' } } });
    await findByText('Line Items');
    expect(queryByText('Show Billables')).not.toBeInTheDocument();
  });
});
