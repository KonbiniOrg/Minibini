import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { api } from '@/lib/api.js';
import { overlayMessage, clearMessage } from '@/stores/messages.js';
import InvoiceWizardPage from '@/routes/invoices/InvoiceWizardPage.svelte';

const POOL = {
  tasks: [
    {
      task_id: 5,
      name: 'Cut',
      has_billable_atoms: true,
      atoms: [
        {
          type: 'task',
          id: 5,
          description: 'Cut (Hourly)',
          state: 'available',
          qty: '1',
          rate: '10.00',
          units: 'none',
          amount: '10.00',
          claiming_line_item_id: null,
          claiming_line_number: null,
          claiming_invoice_id: null,
          claiming_invoice_number: null,
        },
      ],
    },
  ],
};

beforeEach(() => {
  clearMessage();
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/invoices/1/') {
      return Promise.resolve({ invoice_id: 1, job: null, status: 'draft' });
    }
    if (url === '/api/invoices/1/line-items/') return Promise.resolve([]);
    if (url === '/api/invoices/1/source-pool/') {
      return Promise.resolve(JSON.parse(JSON.stringify(POOL)));
    }
    return Promise.resolve(null);
  });
});

async function selectAtomAndAdd() {
  render(InvoiceWizardPage, { props: { params: { id: '1' } } });
  const checkbox = await screen.findByRole('checkbox');
  await fireEvent.click(checkbox);
  await fireEvent.click(screen.getByRole('button', { name: 'Add Here' }));
}

describe('InvoiceWizardPage add-atoms error handling', () => {
  it('renders the 409 atoms-claimed conflict as a form message with a Reload wizard affordance', async () => {
    api.post.mockRejectedValue(Object.assign(new Error('Conflict'), {
      status: 409,
      data: { detail: 'Some atoms were claimed by another invoice.', code: 'atoms_already_claimed' },
    }));

    await selectAtomAndAdd();

    const msg = await screen.findByRole('alert');
    expect(msg.textContent).toContain('Some atoms were claimed by another invoice.');
    // Conflict is a form-venue message, not the global overlay.
    expect(get(overlayMessage)).toBeNull();

    // The next-step affordance reloads the wizard (source pool included).
    const poolCallsBefore = api.get.mock.calls.filter(([u]) => u.includes('/source-pool/')).length;
    await fireEvent.click(screen.getByRole('button', { name: 'Reload wizard' }));
    expect(api.get.mock.calls.filter(([u]) => u.includes('/source-pool/')).length)
      .toBe(poolCallsBefore + 1);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('raises the global overlay for non-409 add failures', async () => {
    api.post.mockRejectedValue(Object.assign(new Error('Request failed'), {
      status: 400,
      data: { detail: 'Invoice is not editable.' },
    }));

    await selectAtomAndAdd();

    await vi.waitFor(() => {
      expect(get(overlayMessage)).toEqual({ kind: 'error', text: 'Invoice is not editable.' });
    });
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
