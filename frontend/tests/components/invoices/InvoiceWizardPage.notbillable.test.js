import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';

// Mock the API the page loads from. Static imports below share one Svelte
// runtime with testing-library (no vi.resetModules — that would give the
// component a second Svelte instance and trigger effect_orphan).
vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

import { api } from '@/lib/api.js';
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
          state: 'not_billable',
          not_billable_reason: 'task_incomplete',
          qty: '1',
          rate: '0.00',
          units: 'none',
          amount: '0.00',
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
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url === '/api/invoices/1/') {
      // job: null so the page skips the job/contact fetches entirely.
      return Promise.resolve({ invoice_id: 1, job: null, status: 'draft' });
    }
    if (url === '/api/invoices/1/line-items/') return Promise.resolve([]);
    if (url === '/api/invoices/1/source-pool/') return Promise.resolve(POOL);
    return Promise.resolve(null);
  });
});

describe('InvoiceWizardPage — not_billable atoms survive reconcile', () => {
  it('keeps an incomplete-task atom non-selectable after load (no checkbox)', async () => {
    render(InvoiceWizardPage, { props: { params: { id: '1' } } });

    // Wait for the async load + reconcile to settle: the atom's description renders.
    await screen.findByText(/Cut \(Hourly\)/);

    // The greyed reason must be shown…
    expect(screen.getByText(/task not complete/i)).toBeTruthy();
    // …and there must be NO selectable checkbox for it. Before the fix,
    // reconcileAtomStates() clobbered state 'not_billable' → 'available',
    // which renders an enabled checkbox.
    expect(screen.queryByRole('checkbox')).toBeNull();
  });
});
