import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';

// Reconcile mode is the parameterized merge of the two retired wizard pages
// (EstimateWizardPage / InvoiceWizardPage). These tests port their behavioral
// assertions across both configs.
vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));
vi.mock('svelte-spa-router', () => ({ link: () => {}, push: vi.fn() }));

import { api } from '@/lib/api.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import ReconcileMode from '@/components/wizards/ReconcileMode.svelte';

beforeEach(() => {
  clearMessage();
  api.get.mockReset();
  api.post.mockReset();
});

// ─── Estimate config ─────────────────────────────────────────────────────────

const EST_ATOM = {
  type: 'task', id: 3, description: 'Cut parts', state: 'available',
  qty: '1', rate: '10.00', units: 'none', amount: '10.00',
};

function mockEstimate({ atoms = [], lineItems = [] } = {}) {
  api.get.mockImplementation((url) => {
    if (url === '/api/estimates/11/') return Promise.resolve({ estimate_id: 11, estimate_number: 'EST-11', job: 9, status: 'draft' });
    if (url === '/api/estimates/11/line-items/') return Promise.resolve({ results: lineItems });
    if (url === '/api/estimates/11/source-pool/') return Promise.resolve({ atoms: atoms.map((a) => ({ ...a })) });
    return Promise.resolve({});
  });
}

async function selectAtomAndAdd(props) {
  render(ReconcileMode, { props });
  const checkbox = await screen.findByRole('checkbox');
  await fireEvent.click(checkbox);
  await fireEvent.click(screen.getByRole('button', { name: 'Add Here' }));
}

describe('ReconcileMode — estimate config', () => {
  it('loads the doc, line items, and source pool from the estimate endpoints', async () => {
    mockEstimate({ atoms: [EST_ATOM] });
    render(ReconcileMode, { props: { docType: 'estimate', docId: 11 } });
    await screen.findByText(/Cut parts/);
    expect(api.get).toHaveBeenCalledWith('/api/estimates/11/');
    expect(api.get).toHaveBeenCalledWith('/api/estimates/11/line-items/');
    expect(api.get).toHaveBeenCalledWith('/api/estimates/11/source-pool/');
  });

  it('creates a new line item from selected atoms via line-items-from-atoms', async () => {
    mockEstimate({ atoms: [EST_ATOM] });
    api.post.mockResolvedValue({});
    await selectAtomAndAdd({ docType: 'estimate', docId: 11 });
    expect(api.post).toHaveBeenCalledWith('/api/estimates/11/line-items-from-atoms/', { atoms: [{ type: 'task', id: 3 }] });
  });

  it('renders the 409 atoms-claimed conflict as a form message with a Reload wizard affordance', async () => {
    mockEstimate({ atoms: [EST_ATOM] });
    api.post.mockRejectedValue(Object.assign(new Error('Conflict'), {
      status: 409,
      data: { detail: 'Some atoms were claimed by another estimate.', code: 'atoms_already_claimed' },
    }));

    await selectAtomAndAdd({ docType: 'estimate', docId: 11 });

    const msg = await screen.findByRole('alert');
    expect(msg.textContent).toContain('Some atoms were claimed by another estimate.');
    expect(get(overlayMessage)).toBeNull();

    const poolCallsBefore = api.get.mock.calls.filter(([u]) => u.includes('/source-pool/')).length;
    await fireEvent.click(screen.getByRole('button', { name: 'Reload wizard' }));
    expect(api.get.mock.calls.filter(([u]) => u.includes('/source-pool/')).length)
      .toBe(poolCallsBefore + 1);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('raises the global overlay for non-409 add failures', async () => {
    mockEstimate({ atoms: [EST_ATOM] });
    api.post.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400,
      data: { detail: 'Estimate is not editable.' },
    }));

    await selectAtomAndAdd({ docType: 'estimate', docId: 11 });

    await vi.waitFor(() => {
      expect(get(overlayMessage)).toEqual({ kind: 'error', text: 'Estimate is not editable.' });
    });
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('does not render the invoice-only Agreement Adjustments panel or Manual button', async () => {
    mockEstimate({ atoms: [EST_ATOM] });
    render(ReconcileMode, { props: { docType: 'estimate', docId: 11 } });
    await screen.findByText(/Cut parts/);
    expect(screen.queryByText('Agreement Adjustments')).toBeNull();
    expect(screen.queryByRole('button', { name: '+ Manual' })).toBeNull();
  });
});

// ─── Invoice config ──────────────────────────────────────────────────────────

const INV_POOL = {
  tasks: [
    {
      task_id: 5, name: 'Cut', has_billable_atoms: true,
      atoms: [
        {
          type: 'task', id: 5, description: 'Cut (Hourly)', state: 'available',
          qty: '1', rate: '10.00', units: 'none', amount: '10.00',
          claiming_line_item_id: null, claiming_line_number: null,
        },
      ],
    },
  ],
};

function mockInvoice({ pool = INV_POOL, lineItems = [], adjustments = [] } = {}) {
  api.get.mockImplementation((url) => {
    if (url === '/api/invoices/1/') return Promise.resolve({ invoice_id: 1, invoice_number: 'INV-1', job: 9, status: 'draft' });
    if (url === '/api/invoices/1/line-items/') return Promise.resolve(lineItems);
    if (url === '/api/invoices/1/source-pool/') return Promise.resolve(JSON.parse(JSON.stringify(pool)));
    if (url === '/api/invoices/1/agreement-adjustments/') return Promise.resolve({ adjustments });
    return Promise.resolve(null);
  });
}

describe('ReconcileMode — invoice config', () => {
  it('loads the doc, line items, and source pool from the invoice endpoints', async () => {
    mockInvoice();
    render(ReconcileMode, { props: { docType: 'invoice', docId: 1 } });
    await screen.findByText(/Cut \(Hourly\)/);
    expect(api.get).toHaveBeenCalledWith('/api/invoices/1/');
    expect(api.get).toHaveBeenCalledWith('/api/invoices/1/line-items/');
    expect(api.get).toHaveBeenCalledWith('/api/invoices/1/source-pool/');
  });

  it('creates a new line item from selected atoms via line-items-from-atoms', async () => {
    mockInvoice();
    api.post.mockResolvedValue({});
    const render_ = render(ReconcileMode, { props: { docType: 'invoice', docId: 1 } });
    const checkbox = await screen.findByRole('checkbox');
    await fireEvent.click(checkbox);
    await fireEvent.click(screen.getByRole('button', { name: 'Add Here' }));
    expect(api.post).toHaveBeenCalledWith('/api/invoices/1/line-items-from-atoms/', { atoms: [{ type: 'task', id: 5 }] });
    void render_;
  });

  it('adds a manual line item via the line-items endpoint', async () => {
    mockInvoice();
    api.post.mockResolvedValue({});
    render(ReconcileMode, { props: { docType: 'invoice', docId: 1 } });
    const manual = await screen.findByRole('button', { name: '+ Manual' });
    await fireEvent.click(manual);
    expect(api.post).toHaveBeenCalledWith('/api/invoices/1/line-items/', {
      description: '', qty: '1', units: 'each', price: '0.00',
    });
  });

  it('renders the Agreement Adjustments panel when adjustments exist', async () => {
    mockInvoice({ adjustments: [{ adjustment_service_id: 7, description: 'Rush', percent: 10, already_added: false }] });
    render(ReconcileMode, { props: { docType: 'invoice', docId: 1 } });
    expect(await screen.findByText('Agreement Adjustments')).toBeInTheDocument();
  });

  it('renders the 409 atoms-claimed conflict as a form message with a Reload wizard affordance', async () => {
    mockInvoice();
    api.post.mockRejectedValue(Object.assign(new Error('Conflict'), {
      status: 409,
      data: { detail: 'Some atoms were claimed by another invoice.', code: 'atoms_already_claimed' },
    }));

    render(ReconcileMode, { props: { docType: 'invoice', docId: 1 } });
    const checkbox = await screen.findByRole('checkbox');
    await fireEvent.click(checkbox);
    await fireEvent.click(screen.getByRole('button', { name: 'Add Here' }));

    const msg = await screen.findByRole('alert');
    expect(msg.textContent).toContain('Some atoms were claimed by another invoice.');
    expect(get(overlayMessage)).toBeNull();

    const poolCallsBefore = api.get.mock.calls.filter(([u]) => u.includes('/source-pool/')).length;
    await fireEvent.click(screen.getByRole('button', { name: 'Reload wizard' }));
    expect(api.get.mock.calls.filter(([u]) => u.includes('/source-pool/')).length)
      .toBe(poolCallsBefore + 1);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('keeps a not_billable atom non-selectable after reconcile (no checkbox)', async () => {
    const pool = {
      tasks: [
        {
          task_id: 5, name: 'Cut', has_billable_atoms: true,
          atoms: [
            {
              type: 'task', id: 5, description: 'Cut (Hourly)', state: 'not_billable',
              not_billable_reason: 'task_incomplete', qty: '1', rate: '0.00', units: 'none', amount: '0.00',
              claiming_line_item_id: null, claiming_line_number: null,
            },
          ],
        },
      ],
    };
    mockInvoice({ pool });
    render(ReconcileMode, { props: { docType: 'invoice', docId: 1 } });
    await screen.findByText(/Cut \(Hourly\)/);
    expect(screen.getByText(/task not complete/i)).toBeTruthy();
    expect(screen.queryByRole('checkbox')).toBeNull();
  });
});
