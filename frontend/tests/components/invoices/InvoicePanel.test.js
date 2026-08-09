import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor, within } from '@testing-library/svelte';
import { get } from 'svelte/store';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback || 'Error',
}));
vi.mock('svelte-spa-router', () => ({
  link: () => {},
  push: vi.fn(),
}));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import { getJobWs, rememberMode } from '@/stores/jobWorkspace.js';
import { overlayMessage } from '@/stores/messages.js';
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
    display_number: 'INV-5',
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

function mockApi(invoice, { invoices = null, categories = [] } = {}) {
  const invoiceList = invoices ?? (invoice ? [invoice] : []);
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (invoice && url === `/api/invoices/${invoice.invoice_id}/`) {
      return Promise.resolve({ ...invoice });
    }
    if (url.startsWith('/api/invoices/?job=')) {
      return Promise.resolve({ results: invoiceList });
    }
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: categories });
    if (url.includes('rate-schemes')) return Promise.resolve({ results: [ADJ_SERVICE] });
    if (url.includes('source-pool')) return Promise.resolve({ tasks: [] });
    if (url.includes('agreement-adjustments')) return Promise.resolve({ adjustments: [] });
    return Promise.resolve({});
  });
}

beforeEach(() => {
  api.post?.mockReset?.();
  api.patch?.mockReset?.();
  api.delete?.mockReset?.();
});

describe('InvoicePanel draft placeholder identity', () => {
  it('titles an unnumbered draft with the display placeholder', async () => {
    user.set({ permissions: [] });
    const draft = makeInvoice({
      invoice_number: null, display_number: 'Draft — JOB-9', status: 'draft',
    });
    mockApi(draft, { invoices: [draft] });
    const { findByText } = render(InvoicePanel, {
      props: { job: JOB, invoiceId: 5 },
    });
    await findByText('Invoice: Draft — JOB-9');
  });
});

describe('InvoicePanel invoice subnav', () => {
  it('renders one job-scoped link per invoice, active on the shown doc', async () => {
    user.set({ permissions: [] });
    const i1 = makeInvoice({ invoice_id: 5, invoice_number: 'INV-5', display_number: 'INV-5', status: 'open', created_date: '2026-01-01T00:00:00Z' });
    const i2 = makeInvoice({ invoice_id: 6, invoice_number: 'INV-6', display_number: 'INV-6', status: 'draft', created_date: '2026-01-02T00:00:00Z' });
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

// ─── Add-line flow (picker + InvoiceAddLineForm) ─────────────────────────────

describe('InvoicePanel add-line flow', () => {
  it('opens the picker (not the create-mode LineItemModal) when "Add Line Item" is clicked', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft', line_items: [] }));
    const { findByText, findByRole } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await fireEvent.click(await findByText('Add Line Item'));
    expect(await findByRole('dialog')).toBeInTheDocument();
    expect(await findByText('Add line')).toBeInTheDocument();
  });
});

// ─── Add Deposit Invoice (Task 21 — replaces the picker's Add Deposit) ───────

// Three states, derived from the job's own `invoices` list (InvoicePanel's
// GET /api/invoices/?job= call carries no ?summary= param, so each entry is
// the full InvoiceSerializer — nested line_items included, same shape as the
// single-invoice GET; no separate fetch needed):
//   1. no draft invoice on the job       → "Add Deposit Invoice"
//   2. a draft exists with ZERO lines    → "Make this a deposit invoice"
//   3. a draft exists WITH ≥1 lines      → suppressed entirely
const DEP_CAT = [{ id: 3, code: 'DEP', name: 'Deposits', is_active: true, is_deposit: true }];

describe('InvoicePanel Add Deposit Invoice — state 1 (no draft)', () => {
  it('shows "Add Deposit Invoice" next to Start Invoice in the empty state, when billable + can_manage', async () => {
    user.set({ permissions: [] });
    mockApi(null, { invoices: [] });
    const { findByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'approved', can_manage: true }, invoiceId: null },
    });
    expect(await findByRole('button', { name: /start invoice/i })).toBeInTheDocument();
    expect(await findByRole('button', { name: /^add deposit invoice$/i })).toBeInTheDocument();
  });

  it('hides Add Deposit Invoice in the empty state on a non-billable job', async () => {
    user.set({ permissions: [] });
    mockApi(null, { invoices: [] });
    const { findByText, queryByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'draft', can_manage: true }, invoiceId: null },
    });
    await findByText(/invoicing becomes available/i);
    expect(queryByRole('button', { name: /add deposit invoice/i })).not.toBeInTheDocument();
  });

  it('hides Add Deposit Invoice in the empty state without can_manage', async () => {
    user.set({ permissions: [] });
    mockApi(null, { invoices: [] });
    const { findByText, queryByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'approved', can_manage: false }, invoiceId: null },
    });
    await findByText('No invoices yet.');
    expect(queryByRole('button', { name: /add deposit invoice/i })).not.toBeInTheDocument();
  });

  it('disables Add Deposit Invoice with a hint when no active deposit category exists', async () => {
    user.set({ permissions: [] });
    mockApi(null, { invoices: [], categories: [] });
    const { findByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'approved', can_manage: true }, invoiceId: null },
    });
    const btn = await findByRole('button', { name: /^add deposit invoice$/i });
    expect(btn).toBeDisabled();
    expect(btn.title).toMatch(/set a deposit category/i);
  });

  it('enables Add Deposit Invoice once an active deposit category exists', async () => {
    user.set({ permissions: [] });
    mockApi(null, { invoices: [], categories: DEP_CAT });
    const { findByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'approved', can_manage: true }, invoiceId: null },
    });
    const btn = await findByRole('button', { name: /^add deposit invoice$/i });
    expect(btn).not.toBeDisabled();
  });

  it('clicking Add Deposit Invoice opens the modal', async () => {
    user.set({ permissions: [] });
    mockApi(null, { invoices: [], categories: DEP_CAT });
    const { findByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'approved', can_manage: true }, invoiceId: null },
    });
    await fireEvent.click(await findByRole('button', { name: /^add deposit invoice$/i }));
    expect(await findByRole('heading', { name: /add deposit invoice/i })).toBeInTheDocument();
  });

  it('relabels to "Add Progress Invoice" next to "+ New invoice" once a live invoice exists (spec §7.2)', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const sent = makeInvoice({ invoice_id: 5, invoice_number: 'INV-5', display_number: 'INV-5', status: 'sent' });
    mockApi(sent, { invoices: [sent], categories: DEP_CAT });
    const { findByRole, queryByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'in_progress', can_manage: true }, invoiceId: 5 },
    });
    expect(await findByRole('button', { name: /new invoice/i })).toBeInTheDocument();
    expect(await findByRole('button', { name: /^add progress invoice$/i })).toBeInTheDocument();
    expect(queryByRole('button', { name: /^add deposit invoice$/i })).not.toBeInTheDocument();
  });

  it('keeps "Add Deposit Invoice" when the job\'s only other invoice is cancelled (not live)', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const cancelled = makeInvoice({ invoice_id: 5, status: 'cancelled' });
    mockApi(cancelled, { invoices: [cancelled], categories: DEP_CAT });
    const { findByRole, queryByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'in_progress', can_manage: true }, invoiceId: 5 },
    });
    expect(await findByRole('button', { name: /^add deposit invoice$/i })).toBeInTheDocument();
    expect(queryByRole('button', { name: /^add progress invoice$/i })).not.toBeInTheDocument();
  });

  it('clicking Add Progress Invoice opens the modal with the progress heading', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const sent = makeInvoice({ invoice_id: 5, status: 'sent' });
    mockApi(sent, { invoices: [sent], categories: DEP_CAT });
    const { findByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'in_progress', can_manage: true }, invoiceId: 5 },
    });
    await fireEvent.click(await findByRole('button', { name: /^add progress invoice$/i }));
    expect(await findByRole('heading', { name: /add progress invoice/i })).toBeInTheDocument();
  });

  it('Create posts, navigates to the newly created draft, and refreshes the invoices list', async () => {
    user.set({ permissions: [] });
    mockApi(null, { invoices: [], categories: DEP_CAT });
    api.post.mockImplementation((url) => {
      if (url === '/api/invoices/') return Promise.resolve({ invoice_id: 77 });
      return Promise.resolve({ line_item_id: 1 });
    });
    const { findByRole, getByLabelText } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'approved', can_manage: true }, invoiceId: null },
    });
    const listCallsBefore = api.get.mock.calls.filter(([u]) => u.startsWith('/api/invoices/?job=')).length;

    await fireEvent.click(await findByRole('button', { name: /^add deposit invoice$/i }));
    await fireEvent.input(getByLabelText(/amount/i), { target: { value: '2500' } });
    await fireEvent.click(await findByRole('button', { name: /^create$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/invoices/77/line-items/', {
        deposit: true, description: 'Deposit on JOB-9', qty: '1', units: 'none', price: '2500',
      });
    });
    await waitFor(() => expect(window.location.hash).toBe('#/jobs/9/invoice/77'));
    // No doc was being viewed (empty state, invoiceId null) — navigation is
    // the only path, but the invoices list is still refreshed so gating
    // (state 1/2/3) is correct once the new draft renders.
    await waitFor(() => {
      const after = api.get.mock.calls.filter(([u]) => u.startsWith('/api/invoices/?job=')).length;
      expect(after).toBeGreaterThan(listCallsBefore);
    });
  });
});

describe('InvoicePanel Add Deposit Invoice — state 2 (draft, zero lines)', () => {
  it('relabels to "Make this a deposit invoice" on the version bar when a draft with zero lines exists', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft', line_items: [] });
    mockApi(draft, { invoices: [draft], categories: DEP_CAT });
    const { findByText, findByRole, queryByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'in_progress', can_manage: true }, invoiceId: 5 },
    });
    await findByText(`Invoice: ${draft.display_number}`);
    // "+ New invoice" is hidden (a draft is already open)...
    expect(queryByRole('button', { name: /new invoice/i })).not.toBeInTheDocument();
    // ...but the deposit action stays offered, relabeled — its POST is
    // idempotent server-side and would add the deposit line to this draft.
    expect(queryByRole('button', { name: /^add deposit invoice$/i })).not.toBeInTheDocument();
    expect(await findByRole('button', { name: /make this a deposit invoice/i })).toBeInTheDocument();
  });

  it('Create while VIEWING that draft reloads it in place — no navigation', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft', line_items: [] });
    mockApi(draft, { invoices: [draft], categories: DEP_CAT });
    api.post.mockImplementation((url) => {
      if (url === '/api/invoices/') return Promise.resolve({ invoice_id: 5 });
      return Promise.resolve({ line_item_id: 1 });
    });
    window.location.hash = '#/jobs/9/invoice/5';
    const { findByRole, getByLabelText } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'in_progress', can_manage: true }, invoiceId: 5 },
    });
    const detailCallsBefore = api.get.mock.calls.filter(([u]) => u === '/api/invoices/5/').length;

    await fireEvent.click(await findByRole('button', { name: /make this a deposit invoice/i }));
    await fireEvent.input(getByLabelText(/amount/i), { target: { value: '2500' } });
    await fireEvent.click(await findByRole('button', { name: /^create$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/invoices/5/line-items/', {
        deposit: true, description: 'Deposit on JOB-9', qty: '1', units: 'none', price: '2500',
      });
    });
    // The established loadInvoice()/handleLineAdded reload convention: the
    // invoice GET refires so the new line appears, and the URL is untouched.
    await waitFor(() => {
      const after = api.get.mock.calls.filter(([u]) => u === '/api/invoices/5/').length;
      expect(after).toBeGreaterThan(detailCallsBefore);
    });
    expect(window.location.hash).toBe('#/jobs/9/invoice/5');
  });

  it('relabels to "Make this a progress invoice" when a live invoice exists besides the empty draft', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const sent = makeInvoice({ invoice_id: 9001, invoice_number: 'INV-9001', display_number: 'INV-9001', status: 'sent' });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft', line_items: [] });
    mockApi(draft, { invoices: [sent, draft], categories: DEP_CAT });
    const { findByRole, queryByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'in_progress', can_manage: true }, invoiceId: 5 },
    });
    expect(await findByRole('button', { name: /make this a progress invoice/i })).toBeInTheDocument();
    expect(queryByRole('button', { name: /make this a deposit invoice/i })).not.toBeInTheDocument();
  });

  it('Create while viewing a DIFFERENT doc navigates to the draft (as before; progress variant here)', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const sent = makeInvoice({ invoice_id: 9001, invoice_number: 'INV-9001', display_number: 'INV-9001', status: 'sent' });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft', line_items: [] });
    mockApi(sent, { invoices: [sent, draft], categories: DEP_CAT });
    api.post.mockImplementation((url) => {
      if (url === '/api/invoices/') return Promise.resolve({ invoice_id: 5 });
      return Promise.resolve({ line_item_id: 1 });
    });
    window.location.hash = '#/jobs/9/invoice/9001';
    const { findByRole, getByLabelText } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'in_progress', can_manage: true }, invoiceId: 9001 },
    });

    await fireEvent.click(await findByRole('button', { name: /make this a progress invoice/i }));
    await fireEvent.input(getByLabelText(/amount/i), { target: { value: '2500' } });
    await fireEvent.click(await findByRole('button', { name: /^create$/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/invoices/5/line-items/', {
        deposit: true, description: 'Progress billing on JOB-9', qty: '1', units: 'none', price: '2500',
      });
    });
    await waitFor(() => expect(window.location.hash).toBe('#/jobs/9/invoice/5'));
  });
});

describe('InvoicePanel Add Deposit Invoice — state 3 (draft, has lines)', () => {
  it('suppresses the deposit action entirely when the open draft already has line items', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft', line_items: [makeLine()] });
    mockApi(draft, { invoices: [draft], categories: DEP_CAT });
    const { findByText, queryByRole } = render(InvoicePanel, {
      props: { job: { ...JOB, status: 'in_progress', can_manage: true }, invoiceId: 5 },
    });
    await findByText('Invoice: INV-5');
    expect(queryByRole('button', { name: /add deposit invoice/i })).not.toBeInTheDocument();
    expect(queryByRole('button', { name: /make this a deposit invoice/i })).not.toBeInTheDocument();
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

// ─── Mode bar ─────────────────────────────────────────────────────────────────

describe('InvoicePanel mode bar', () => {
  beforeEach(() => { localStorage.clear(); });

  const LINE = {
    line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
    price: '5', accounting_category: null, sources: [], backing: null,
  };

  it('offers Edit / Customer / Reorder — no wizard-era wording', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ invoice_id: 5, status: 'draft', line_items: [LINE] }));
    const { findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Line Items');
    expect(await findByText('Edit')).toBeInTheDocument();
    expect(await findByText('Customer')).toBeInTheDocument();
    expect(await findByText('Reorder')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Show Billables|Reconcile|Send all to Invoice/);
  });

  it('does not offer Reorder when the invoice is not editable (sent)', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ invoice_id: 5, status: 'open', line_items: [LINE] }));
    const { findByText, queryByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Invoice: INV-5');
    expect(await findByText('Customer')).toBeInTheDocument();
    expect(queryByText('Reorder')).toBeNull();
  });

  it('switches between Edit / Customer / Reorder views in place and persists the choice per docId', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ invoice_id: 5, status: 'draft', line_items: [LINE], total: '10.00' }));
    const { container, findByText, queryByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Cut');

    const modeBar = () => container.querySelector('.doc-mode-bar');
    await fireEvent.click(within(modeBar()).getByRole('button', { name: 'Customer' }));
    expect(await findByText('Invoice INV-5')).toBeInTheDocument();
    expect(queryByText('Add Line Item')).toBeNull();
    expect(getJobWs(9).modes['inv:5']).toBe('customer');

    await fireEvent.click(within(modeBar()).getByRole('button', { name: 'Reorder' }));
    expect(container.querySelectorAll('.doc-reorder-arrows').length).toBeGreaterThan(0);
    expect(getJobWs(9).modes['inv:5']).toBe('reorder');

    await fireEvent.click(within(modeBar()).getByRole('button', { name: 'Edit' }));
    expect(await findByText('Add Line Item')).toBeInTheDocument();
    expect(getJobWs(9).modes['inv:5']).toBe('edit');
  });

  it('normalizes a remembered "reconcile" (old wizard toggle) to Edit mode', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    rememberMode(9, 'inv:5', 'reconcile');
    mockApi(makeInvoice({ invoice_id: 5, status: 'draft', line_items: [LINE] }));
    const { container, findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Add Line Item');
    const modeBar = container.querySelector('.doc-mode-bar');
    expect(within(modeBar).getByRole('button', { name: 'Edit' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('normalizes a remembered "lines" (old two-mode panel) to Edit mode', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    rememberMode(9, 'inv:5', 'lines');
    mockApi(makeInvoice({ invoice_id: 5, status: 'draft', line_items: [LINE] }));
    const { container, findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Add Line Item');
    const modeBar = container.querySelector('.doc-mode-bar');
    expect(within(modeBar).getByRole('button', { name: 'Edit' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('does NOT restore from an ESTIMATE with the same numeric id (namespaced keys)', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    rememberMode(9, 'est:5', 'reorder');
    mockApi(makeInvoice({ invoice_id: 5, status: 'draft', line_items: [LINE] }));
    const { container, findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Add Line Item');
    const modeBar = container.querySelector('.doc-mode-bar');
    expect(within(modeBar).getByRole('button', { name: 'Edit' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('falls back to Edit when "reorder" was remembered but the invoice is no longer editable', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    rememberMode(9, 'inv:5', 'reorder');
    mockApi(makeInvoice({ invoice_id: 5, status: 'open', line_items: [LINE] }));
    const { container, findByText, queryByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Cut');
    expect(queryByText('Add Line Item')).toBeNull(); // not editable, but still Edit mode
    const modeBar = container.querySelector('.doc-mode-bar');
    expect(within(modeBar).getByRole('button', { name: 'Edit' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(modeBar).queryByRole('button', { name: 'Reorder' })).toBeNull();
  });
});

describe('InvoicePanel line-item actions', () => {
  it('"Remove from invoice" on a line calls the line-item delete endpoint', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft', line_items: [
      { line_item_id: 42, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [], backing: null },
    ] }));
    api.delete.mockResolvedValue({ message: 'Line item deleted.' });
    const { findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    const removeBtn = await findByText('Remove from invoice');
    await fireEvent.click(removeBtn);
    expect(api.delete).toHaveBeenCalledWith('/api/invoices/5/line-items/42/');
  });

  it('hides Edit…/Remove when canEditLineItems is false (not draft)', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'open', line_items: [
      { line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [], backing: null },
    ] }));
    const { findByText, queryByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Cut');
    expect(queryByText('Edit…')).toBeNull();
    expect(queryByText('Remove from invoice')).toBeNull();
  });

  it('never renders the word "delete" anywhere in the edit view', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    mockApi(makeInvoice({ status: 'draft', line_items: [
      { line_item_id: 1, line_number: 1, description: 'Cut', qty: '2', units: 'hr',
        price: '5', accounting_category: null, sources: [], backing: null },
    ] }));
    const { findByText, queryByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Cut');
    expect(queryByText(/delete/i)).toBeNull();
  });
});

describe('InvoicePanel "+ New invoice" (create a sibling invoice)', () => {
  const billableJob = { ...JOB, status: 'in_progress' };

  it('offers "+ New invoice" on the version bar when billable, no open draft, and financials', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const sent = makeInvoice({ invoice_id: 5, invoice_number: 'INV-5', display_number: 'INV-5', status: 'sent' });
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

// ─── Unapplied deposit credit notice + Apply (Task 22) ───────────────────────

function makeDepositLine(overrides = {}) {
  return makeLine({
    line_item_id: 501, line_number: 1, description: 'Deposit on JOB-9',
    qty: '1', price: '5000.00', units: 'none',
    accounting_category: { id: 3, name: 'Customer Deposits' },
    is_deposit: true, sources: [],
    ...overrides,
  });
}

function makeDeductionLine(overrides = {}) {
  return makeLine({
    line_item_id: 601, line_number: 1, description: 'Less deposit (INV-1042)',
    qty: '1', price: '-5000.00', units: 'none',
    is_deposit: false,
    sources: [{ source_id: 1, source_type: 'deposit', source_pk: 501 }],
    ...overrides,
  });
}

describe('InvoicePanel unapplied deposit credit notice', () => {
  it('renders the notice (amount + source invoice number) on a draft when a paid deposit line is unapplied', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft', line_items: [] });
    const paidDeposit = makeInvoice({
      invoice_id: 100, invoice_number: 'INV-1042', display_number: 'INV-1042',
      status: 'paid', line_items: [makeDepositLine()],
    });
    mockApi(draft, { invoices: [draft, paidDeposit] });
    const { findByText, findByRole } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    expect(await findByText('Unapplied deposit credit — $5000.00 from INV-1042')).toBeInTheDocument();
    expect(await findByRole('button', { name: /apply deposit credit/i })).toBeInTheDocument();
  });

  it('handles multiple unapplied credits as a list', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft', line_items: [] });
    const paidA = makeInvoice({
      invoice_id: 100, invoice_number: 'INV-1042', display_number: 'INV-1042',
      status: 'paid', line_items: [makeDepositLine({ line_item_id: 501, price: '5000.00' })],
    });
    const paidB = makeInvoice({
      invoice_id: 101, invoice_number: 'INV-1043', display_number: 'INV-1043',
      status: 'paid', line_items: [makeDepositLine({ line_item_id: 502, price: '750.00' })],
    });
    mockApi(draft, { invoices: [draft, paidA, paidB] });
    const { findByText, findAllByRole } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    expect(await findByText('Unapplied deposit credit — $5000.00 from INV-1042')).toBeInTheDocument();
    expect(await findByText('Unapplied deposit credit — $750.00 from INV-1043')).toBeInTheDocument();
    expect(await findAllByRole('button', { name: /apply deposit credit/i })).toHaveLength(2);
  });

  it('is absent when the deposit line is claimed by a live (non-cancelled) invoice', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft', line_items: [] });
    const paidDeposit = makeInvoice({
      invoice_id: 100, invoice_number: 'INV-1042', display_number: 'INV-1042',
      status: 'paid', line_items: [makeDepositLine()],
    });
    const claiming = makeInvoice({
      invoice_id: 200, invoice_number: 'INV-2000', display_number: 'INV-2000',
      status: 'open', line_items: [makeDeductionLine()],
    });
    mockApi(draft, { invoices: [draft, paidDeposit, claiming] });
    const { findByText, queryByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Invoice: INV-5');
    expect(queryByText(/unapplied deposit credit/i)).not.toBeInTheDocument();
  });

  it('is PRESENT again when the claiming invoice is cancelled (parity with the backend claims rule)', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft', line_items: [] });
    const paidDeposit = makeInvoice({
      invoice_id: 100, invoice_number: 'INV-1042', display_number: 'INV-1042',
      status: 'paid', line_items: [makeDepositLine()],
    });
    const cancelledClaim = makeInvoice({
      invoice_id: 200, invoice_number: 'INV-2000', display_number: 'INV-2000',
      status: 'cancelled', line_items: [makeDeductionLine()],
    });
    mockApi(draft, { invoices: [draft, paidDeposit, cancelledClaim] });
    const { findByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    expect(await findByText('Unapplied deposit credit — $5000.00 from INV-1042')).toBeInTheDocument();
  });

  it('is absent on a non-draft invoice view even though an unapplied credit exists on the job', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const sent = makeInvoice({ invoice_id: 5, status: 'sent', line_items: [] });
    const paidDeposit = makeInvoice({
      invoice_id: 100, invoice_number: 'INV-1042', display_number: 'INV-1042',
      status: 'paid', line_items: [makeDepositLine()],
    });
    mockApi(sent, { invoices: [sent, paidDeposit] });
    const { findByText, queryByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Invoice: INV-5');
    expect(queryByText(/unapplied deposit credit/i)).not.toBeInTheDocument();
  });

  it('is absent when no deposit credits exist on the job at all', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft', line_items: [] });
    mockApi(draft, { invoices: [draft] });
    const { findByText, queryByText } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await findByText('Invoice: INV-5');
    expect(queryByText(/unapplied deposit credit/i)).not.toBeInTheDocument();
  });

  it('the notice text shows even without canManageFinancials, but the Apply button is gated on it', async () => {
    user.set({ permissions: [] });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft', line_items: [] });
    const paidDeposit = makeInvoice({
      invoice_id: 100, invoice_number: 'INV-1042', display_number: 'INV-1042',
      status: 'paid', line_items: [makeDepositLine()],
    });
    mockApi(draft, { invoices: [draft, paidDeposit] });
    const { findByText, queryByRole } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    expect(await findByText('Unapplied deposit credit — $5000.00 from INV-1042')).toBeInTheDocument();
    expect(queryByRole('button', { name: /apply deposit credit/i })).not.toBeInTheDocument();
  });

  it('Apply posts the exact atoms payload and reloads the invoice + invoices list', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft', line_items: [] });
    const paidDeposit = makeInvoice({
      invoice_id: 100, invoice_number: 'INV-1042', display_number: 'INV-1042',
      status: 'paid', line_items: [makeDepositLine()],
    });
    mockApi(draft, { invoices: [draft, paidDeposit] });
    api.post.mockResolvedValue({ line_item_id: 999 });
    const { findByRole } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    const detailCallsBefore = api.get.mock.calls.filter(([u]) => u === '/api/invoices/5/').length;
    const listCallsBefore = api.get.mock.calls.filter(([u]) => u.startsWith('/api/invoices/?job=')).length;

    await fireEvent.click(await findByRole('button', { name: /apply deposit credit/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/api/invoices/5/line-items-from-atoms/', {
        atoms: [{ type: 'deposit', id: 501 }],
      });
    });
    await waitFor(() => {
      const after = api.get.mock.calls.filter(([u]) => u === '/api/invoices/5/').length;
      expect(after).toBeGreaterThan(detailCallsBefore);
    });
    await waitFor(() => {
      const after = api.get.mock.calls.filter(([u]) => u.startsWith('/api/invoices/?job=')).length;
      expect(after).toBeGreaterThan(listCallsBefore);
    });
  });

  it('a 409 atoms_already_claimed error surfaces via the overlay (triageError) without crashing', async () => {
    user.set({ permissions: ['can_manage_financials'] });
    const draft = makeInvoice({ invoice_id: 5, status: 'draft', line_items: [] });
    const paidDeposit = makeInvoice({
      invoice_id: 100, invoice_number: 'INV-1042', display_number: 'INV-1042',
      status: 'paid', line_items: [makeDepositLine()],
    });
    mockApi(draft, { invoices: [draft, paidDeposit] });
    api.post.mockRejectedValue({
      status: 409,
      message: 'Some of these atoms are already claimed by another invoice.',
      data: {
        detail: 'Some of these atoms are already claimed by another invoice.',
        code: 'atoms_already_claimed', atom_ids: [501],
      },
    });
    overlayMessage.set(null);
    const { findByRole } = render(InvoicePanel, { props: { job: JOB, invoiceId: 5 } });
    await fireEvent.click(await findByRole('button', { name: /apply deposit credit/i }));
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    await waitFor(() => {
      expect(get(overlayMessage)?.text).toMatch(/already claimed/i);
    });
  });
});
