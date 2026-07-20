import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock('svelte-spa-router', () => ({
  link: () => {},
  push: vi.fn(),
}));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import { getJobWs, rememberMode } from '@/stores/jobWorkspace.js';
import InvoicePanel from '@/components/invoices/InvoicePanel.svelte';

const JOB = {
  job_id: 9, job_number: 'JOB-9', name: 'Job', contact: null, can_manage: true,
  tasks: [], materials: [], fees: [],
};
const ADJ_SERVICE = { rate_scheme_id: 2, name: 'Late Fee', algorithm: 'percentage', rate: '5.00' };

function makeInvoice(overrides = {}) {
  return {
    invoice_id: 5,
    invoice_number: 'INV-5',
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

function mockApi(invoice, { invoices = null } = {}) {
  const invoiceList = invoices ?? (invoice ? [invoice] : []);
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (invoice && url === `/api/invoices/${invoice.invoice_id}/`) {
      return Promise.resolve({ ...invoice });
    }
    if (url.startsWith('/api/invoices/?job=')) {
      return Promise.resolve({ results: invoiceList });
    }
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [] });
    if (url.includes('rate-schemes')) return Promise.resolve({ results: [ADJ_SERVICE] });
    return Promise.resolve({});
  });
}

beforeEach(() => {
  api.post?.mockReset?.();
  api.patch?.mockReset?.();
  api.delete?.mockReset?.();
});

describe('InvoicePanel invoice subnav', () => {
  it('renders one job-scoped link per invoice, active on the shown doc', async () => {
    user.set({ permissions: [] });
    const i1 = makeInvoice({ invoice_id: 5, invoice_number: 'INV-5', status: 'open', created_date: '2026-01-01T00:00:00Z' });
    const i2 = makeInvoice({ invoice_id: 6, invoice_number: 'INV-6', status: 'draft', created_date: '2026-01-02T00:00:00Z' });
    mockApi(i2, { invoices: [i1, i2] });

    const { findByText, container } = render(InvoicePanel, {
      props: { job: JOB, invoiceId: 6 },
    });

    await findByText('Invoice: INV-6');
    const links = Array.from(container.querySelectorAll('.doc-subnav a'));
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute('href', '#/jobs/9/invoice/5');
    expect(links[0]).toHaveTextContent('INV-5');
    expect(links[1]).toHaveAttribute('href', '#/jobs/9/invoice/6');
    expect(links[1]).toHaveTextContent('INV-6');
    expect(links[1]).toHaveClass('active');
    expect(links[0]).not.toHaveClass('active');
  });
});

describe('InvoicePanel empty state', () => {
  it('shows a can_manage-gated Start Invoice button when a billable job has no invoices', async () => {
    user.set({ permissions: [] });
    mockApi(null, { invoices: [] });
    const { findByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'approved', can_manage: true }, invoiceId: null },
    });
    expect(await findByRole('button', { name: /start invoice/i })).toBeInTheDocument();
  });

  it('shows a plain message (no button) when the job has no invoices and no can_manage', async () => {
    user.set({ permissions: [] });
    mockApi(null, { invoices: [] });
    const { findByText, queryByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'approved', can_manage: false }, invoiceId: null },
    });
    expect(await findByText('No invoices yet.')).toBeInTheDocument();
    expect(queryByRole('button', { name: /start invoice/i })).not.toBeInTheDocument();
  });

  it('hides Start Invoice on a non-billable (draft) job and explains why', async () => {
    // Clicking it could only ever produce a backend error — gate it instead,
    // the way the estimate panel gates Create Change Order.
    user.set({ permissions: [] });
    mockApi(null, { invoices: [] });
    const { findByText, queryByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'draft', can_manage: true }, invoiceId: null },
    });
    expect(await findByText(/invoicing becomes available/i)).toBeInTheDocument();
    expect(queryByRole('button', { name: /start invoice/i })).not.toBeInTheDocument();
  });

  it('Start Invoice posts and navigates to the job-scoped invoice URL', async () => {
    user.set({ permissions: [] });
    mockApi(null, { invoices: [] });
    api.post.mockResolvedValue({ invoice_id: 42 });
    const { findByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'approved', can_manage: true }, invoiceId: null },
    });
    const btn = await findByRole('button', { name: /start invoice/i });
    await fireEvent.click(btn);
    expect(api.post).toHaveBeenCalledWith('/api/invoices/', { job: 9 });
  });
});

// ─── Seed buttons ────────────────────────────────────────────────────────────

describe('InvoicePanel seed buttons', () => {
  it('shows both seed buttons on a draft invoice with no line items', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft', line_items: [] }));
    const { findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    expect(await findByText('Apply everything')).toBeInTheDocument();
    expect(await findByText('Copy from estimate')).toBeInTheDocument();
  });

  it('"Copy from estimate" is enabled when job_has_other_invoices is false', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft', line_items: [], job_has_other_invoices: false }));
    const { findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    const btn = await findByText('Copy from estimate');
    expect(btn).not.toBeDisabled();
  });

  it('"Copy from estimate" is disabled when job_has_other_invoices is true', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft', line_items: [], job_has_other_invoices: true }));
    const { findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    const btn = await findByText('Copy from estimate');
    expect(btn).toBeDisabled();
  });

  it('"Copy from estimate" has an explanatory title when disabled', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft', line_items: [], job_has_other_invoices: true }));
    const { findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    const btn = await findByText('Copy from estimate');
    expect(btn.title).toMatch(/another invoice exists/i);
  });

  it('does NOT show seed buttons on a draft invoice that already has line items', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft', line_items: [makeLine()] }));
    const { findByText, queryByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Line Items');
    expect(queryByText('Apply everything')).not.toBeInTheDocument();
    expect(queryByText('Copy from estimate')).not.toBeInTheDocument();
  });

  it('does NOT show seed buttons on a non-draft invoice with no line items', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'open', line_items: [] }));
    const { findByText, queryByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Line Items');
    expect(queryByText('Apply everything')).not.toBeInTheDocument();
    expect(queryByText('Copy from estimate')).not.toBeInTheDocument();
  });

  it('clicking "Apply everything" calls POST to apply-everything endpoint then reloads', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const inv = makeInvoice({ status: 'draft', line_items: [] });
    mockApi(inv);
    api.post.mockResolvedValue({ created: 3 });
    const { findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    const btn = await findByText('Apply everything');

    // Track api.get calls before the click to verify reload happens
    const getCallCountBefore = api.get.mock.calls.length;

    await fireEvent.click(btn);

    // Wait for the reload (api.get call) to happen
    await waitFor(() => {
      expect(api.get.mock.calls.length).toBeGreaterThan(getCallCountBefore);
    });

    expect(api.post).toHaveBeenCalledWith(`/api/invoices/${inv.invoice_id}/apply-everything/`, {});
    expect(api.get).toHaveBeenCalledWith(`/api/invoices/${inv.invoice_id}/`);
  });

  it('clicking "Copy from estimate" calls POST to copy-from-estimate endpoint then reloads', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const inv = makeInvoice({ status: 'draft', line_items: [], job_has_other_invoices: false });
    mockApi(inv);
    api.post.mockResolvedValue({ created: 2 });
    const { findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    const btn = await findByText('Copy from estimate');

    // Track api.get calls before the click to verify reload happens
    const getCallCountBefore = api.get.mock.calls.length;

    await fireEvent.click(btn);

    // Wait for the reload (api.get call) to happen
    await waitFor(() => {
      expect(api.get.mock.calls.length).toBeGreaterThan(getCallCountBefore);
    });

    expect(api.post).toHaveBeenCalledWith(`/api/invoices/${inv.invoice_id}/copy-from-estimate/`, {});
    expect(api.get).toHaveBeenCalledWith(`/api/invoices/${inv.invoice_id}/`);
  });
});

// ─── Send-gate ───────────────────────────────────────────────────────────────

describe('InvoicePanel send gate', () => {
  it('shows active Send link when all lines have an accounting_category', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const inv = makeInvoice({
      status: 'draft',
      line_items: [
        makeLine({ accounting_category: { id: 1, name: 'Labor' } }),
        makeLine({ line_item_id: 2, line_number: 2, accounting_category: { id: 2, name: 'Material' } }),
      ],
    });
    mockApi(inv);
    const { findByRole } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    const sendLink = await findByRole('link', { name: /send invoice/i });
    expect(sendLink).toBeInTheDocument();
    expect(sendLink.tagName).toBe('A');
  });

  it('shows active Send link when there are no line items (nothing missing a category)', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft', line_items: [] }));
    const { findByRole } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    const sendLink = await findByRole('link', { name: /send invoice/i });
    expect(sendLink).toBeInTheDocument();
  });

  it('shows disabled Send button + note when a line item has no accounting_category', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const inv = makeInvoice({
      status: 'draft',
      line_items: [
        makeLine({ accounting_category: { id: 1, name: 'Labor' } }),
        makeLine({ line_item_id: 2, line_number: 2, accounting_category: null }),
      ],
    });
    mockApi(inv);
    const { findByText, queryByRole } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });

    await findByText('Line Items');

    expect(queryByRole('link', { name: /send invoice/i })).not.toBeInTheDocument();

    const sendBtn = await findByText('Send Invoice');
    expect(sendBtn.tagName).toBe('BUTTON');
    expect(sendBtn).toBeDisabled();

    expect(await findByText(/assign an accounting category to every line before sending/i)).toBeInTheDocument();
  });

  it('the disabled Send button is a <button>, not an <a>', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const inv = makeInvoice({
      status: 'draft',
      line_items: [makeLine({ accounting_category: null })],
    });
    mockApi(inv);
    const { findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    const sendEl = await findByText('Send Invoice');
    expect(sendEl.tagName).toBe('BUTTON');
    expect(sendEl).toBeDisabled();
  });
});

// ─── hasBillables / Show Billables link ──────────────────────────────────────

describe('InvoicePanel Show Billables link', () => {
  it('shows "Show Billables" when job has fees (but no tasks or materials)', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft' }));
    const job = { ...JOB, tasks: [], materials: [], fees: [{ id: 1, description: 'Setup Fee' }] };
    const { findByText } = render(InvoicePanel, { props: { job, invoiceId: 5 } });
    expect(await findByText('Show Billables')).toBeInTheDocument();
  });

  it('shows "Show Billables" when job has tasks', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft' }));
    const job = { ...JOB, tasks: [{ id: 1, name: 'Cut' }], materials: [], fees: [] };
    const { findByText } = render(InvoicePanel, { props: { job, invoiceId: 5 } });
    expect(await findByText('Show Billables')).toBeInTheDocument();
  });

  it('shows "Show Billables" when job has materials', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft' }));
    const job = { ...JOB, tasks: [], materials: [{ id: 2, description: 'Steel' }], fees: [] };
    const { findByText } = render(InvoicePanel, { props: { job, invoiceId: 5 } });
    expect(await findByText('Show Billables')).toBeInTheDocument();
  });

  it('does NOT show "Show Billables" when job has no tasks, materials, or fees', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft' }));
    const job = { ...JOB, tasks: [], materials: [], fees: [] };
    const { findByText, queryByText } = render(InvoicePanel, { props: { job, invoiceId: 5 } });
    await findByText('Line Items');
    expect(queryByText('Show Billables')).not.toBeInTheDocument();
  });
});

// ─── Adjustment affordances ──────────────────────────────────────────────────

describe('InvoicePanel adjustment affordances', () => {
  it('shows "Add Adjustment" on a draft invoice when canManageFinancials', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft' }));
    const { findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    expect(await findByText('Add Adjustment')).toBeInTheDocument();
  });

  it('does NOT show "Add Adjustment" on a non-draft invoice', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'open' }));
    const { findByText, queryByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Line Items');
    expect(queryByText('Add Adjustment')).not.toBeInTheDocument();
  });

  it('does NOT show "Add Adjustment" when canManageFinancials is false', async () => {
    user.set({ permissions: [] });
    mockApi(makeInvoice({ status: 'draft' }));
    const { findByText, queryByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Line Items');
    expect(queryByText('Add Adjustment')).not.toBeInTheDocument();
  });

  it('opens AdjustmentModal when "Add Adjustment" is clicked', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft' }));
    const { findByText, findByRole } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await fireEvent.click(await findByText('Add Adjustment'));
    expect(await findByRole('dialog')).toBeInTheDocument();
  });

  it('does NOT show a Recalculate button on a draft adjustment line (auto-recompute)', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const adjLine = {
      line_item_id: 88, line_number: 1, description: 'Late Fee 5%',
      qty: 1, price: '5.00', units: 'none', accounting_category: null,
      adjustment_service: ADJ_SERVICE, target_categories: [],
      sources: [],
    };
    mockApi(makeInvoice({ status: 'draft', line_items: [adjLine] }));
    const { findByText, queryByRole } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Line Items');
    expect(queryByRole('button', { name: /recalculate/i })).not.toBeInTheDocument();
  });
});

// ─── Line-item actions ────────────────────────────────────────────────────────

describe('InvoicePanel reconcile mode', () => {
  beforeEach(() => { localStorage.clear(); });

  function mockReconcile(invoice) {
    api.get.mockReset();
    api.get.mockImplementation((url) => {
      if (url === `/api/invoices/${invoice.invoice_id}/`) return Promise.resolve({ ...invoice });
      if (url === `/api/invoices/${invoice.invoice_id}/line-items/`) return Promise.resolve([]);
      if (url === `/api/invoices/${invoice.invoice_id}/source-pool/`) return Promise.resolve({ tasks: [] });
      if (url === `/api/invoices/${invoice.invoice_id}/agreement-adjustments/`) return Promise.resolve({ adjustments: [] });
      if (url.startsWith('/api/invoices/?job=')) return Promise.resolve({ results: [invoice] });
      if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: [] });
      return Promise.resolve({});
    });
  }

  it('flips to reconcile mode and persists the choice per docId', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockReconcile(makeInvoice({ invoice_id: 5, status: 'draft' }));
    const { findByRole, findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await fireEvent.click(await findByRole('button', { name: 'Reconcile' }));
    expect(await findByText('Send all to Invoice')).toBeInTheDocument();
    expect(getJobWs(9).modes['inv:5']).toBe('reconcile');
    expect(await findByRole('button', { name: 'Back to lines' })).toBeInTheDocument();
  });

  it('restores reconcile mode on mount for a draft doc when remembered', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    rememberMode(9, 'inv:5', 'reconcile');
    mockReconcile(makeInvoice({ invoice_id: 5, status: 'draft' }));
    const { findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    expect(await findByText('Send all to Invoice')).toBeInTheDocument();
  });

  it('restores lines (not reconcile) for a SENT doc even when reconcile was remembered', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    rememberMode(9, 'inv:5', 'reconcile');
    mockReconcile(makeInvoice({ invoice_id: 5, status: 'open' }));
    const { findByText, queryByText, queryByRole } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Line Items');
    expect(queryByText('Send all to Invoice')).toBeNull();
    expect(queryByRole('button', { name: 'Reconcile' })).toBeNull();
    expect(queryByRole('button', { name: 'Back to lines' })).toBeNull();
  });

  it('reloads the invoice when flipping back to lines', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockReconcile(makeInvoice({ invoice_id: 5, status: 'draft' }));
    const { findByRole } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await fireEvent.click(await findByRole('button', { name: 'Reconcile' }));
    await findByRole('button', { name: 'Back to lines' });
    const before = api.get.mock.calls.filter(([u]) => u === '/api/invoices/5/').length;
    await fireEvent.click(await findByRole('button', { name: 'Back to lines' }));
    expect(api.get.mock.calls.filter(([u]) => u === '/api/invoices/5/').length).toBeGreaterThan(before);
    expect(getJobWs(9).modes['inv:5']).toBe('lines');
  });
});

describe('InvoicePanel line-item actions', () => {
  it('Delete on a line calls the line-item delete endpoint', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft', line_items: [
      { line_item_id: 42, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [] },
    ] }));
    api.delete.mockResolvedValue({ message: 'deleted' });
    const { findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    const deleteBtn = await findByText('Delete');
    await fireEvent.click(deleteBtn);
    expect(api.delete).toHaveBeenCalledWith('/api/invoices/5/line-items/42/');
  });

  it('hides Edit/Delete when canEditLineItems is false (not draft)', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'open', line_items: [
      { line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [] },
    ] }));
    const { findByText, queryByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Cut');
    expect(queryByText('Edit')).toBeNull();
    expect(queryByText('Delete')).toBeNull();
  });
});

describe('InvoicePanel "+ New invoice" (create a sibling invoice)', () => {
  const billableJob = { ...JOB, status: 'in_progress' };

  it('offers "+ New invoice" on the version bar when billable, no open draft, and financials', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const sent = makeInvoice({ invoice_id: 5, invoice_number: 'INV-5', status: 'sent' });
    mockApi(sent, { invoices: [sent] });
    const { findByRole } = render(InvoicePanel, { props: { job: billableJob, invoiceId: 5 } });
    expect(await findByRole('button', { name: /New invoice/ })).toBeInTheDocument();
  });

  it('posts a new invoice for the job and navigates when clicked', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const sent = makeInvoice({ invoice_id: 5, status: 'sent' });
    mockApi(sent, { invoices: [sent] });
    api.post.mockResolvedValue({ invoice_id: 8 });
    const { findByRole } = render(InvoicePanel, { props: { job: billableJob, invoiceId: 5 } });
    await fireEvent.click(await findByRole('button', { name: /New invoice/ }));
    expect(api.post).toHaveBeenCalledWith('/api/invoices/', { job: 9 });
  });

  it('hides "+ New invoice" while an open draft already exists', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft' });
    mockApi(draft, { invoices: [draft] });
    const { findByText, queryByRole } = render(InvoicePanel, { props: { job: billableJob, invoiceId: 5 } });
    await findByText('Invoice: INV-5');
    expect(queryByRole('button', { name: /New invoice/ })).toBeNull();
  });

  it('hides "+ New invoice" when the job is not in a billable status', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const sent = makeInvoice({ invoice_id: 5, status: 'sent' });
    mockApi(sent, { invoices: [sent] });
    const { findByText, queryByRole } = render(InvoicePanel, { props: { job: { ...JOB, status: 'draft' }, invoiceId: 5 } });
    await findByText('Invoice: INV-5');
    expect(queryByRole('button', { name: /New invoice/ })).toBeNull();
  });

  it('hides "+ New invoice" without the financials permission', async () => {
    user.set({ permissions: [] });
    const sent = makeInvoice({ invoice_id: 5, status: 'sent' });
    mockApi(sent, { invoices: [sent] });
    const { findByText, queryByRole } = render(InvoicePanel, { props: { job: billableJob, invoiceId: 5 } });
    await findByText('Invoice: INV-5');
    expect(queryByRole('button', { name: /New invoice/ })).toBeNull();
  });
});
