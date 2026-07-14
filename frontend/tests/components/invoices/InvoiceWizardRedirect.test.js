import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('@/stores/jobWorkspace.js', () => ({ rememberMode: vi.fn() }));

import { api } from '@/lib/api.js';
import { rememberMode } from '@/stores/jobWorkspace.js';
import InvoiceWizardRedirect from '@/routes/invoices/InvoiceWizardRedirect.svelte';

beforeEach(() => {
  api.get.mockReset();
  rememberMode.mockReset();
  window.location.hash = '#/invoices/1/wizard';
});

describe('InvoiceWizardRedirect shim', () => {
  it('fetches the invoice, remembers reconcile mode, then replaces the hash with the job-scoped URL', async () => {
    api.get.mockResolvedValue({ invoice_id: 1, job: 9 });

    render(InvoiceWizardRedirect, { props: { params: { id: '1' } } });

    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/invoices/1/'));
    await waitFor(() => expect(rememberMode).toHaveBeenCalledWith(9, 'inv:1', 'reconcile'));
    await waitFor(() => expect(window.location.hash).toBe('#/jobs/9/invoice/1'));
  });

  it('redirects to the job list if the invoice fetch fails', async () => {
    api.get.mockRejectedValue(new Error('not found'));

    render(InvoiceWizardRedirect, { props: { params: { id: '1' } } });

    await waitFor(() => expect(window.location.hash).toBe('#/jobs'));
    expect(rememberMode).not.toHaveBeenCalled();
  });
});
