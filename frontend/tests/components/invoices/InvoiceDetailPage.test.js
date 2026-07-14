import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import InvoiceDetailPage from '@/routes/invoices/InvoiceDetailPage.svelte';

beforeEach(() => {
  api.get.mockReset();
  window.location.hash = '#/invoices/5';
});

describe('InvoiceDetailPage redirect shim', () => {
  it('fetches the invoice then replaces the hash with the job-scoped URL', async () => {
    api.get.mockResolvedValue({ invoice_id: 5, job: 9 });

    render(InvoiceDetailPage, { props: { params: { id: '5' } } });

    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/invoices/5/'));
    await waitFor(() => expect(window.location.hash).toBe('#/jobs/9/invoice/5'));
  });

  it('redirects to the job list if the invoice fetch fails', async () => {
    api.get.mockRejectedValue(new Error('not found'));

    render(InvoiceDetailPage, { props: { params: { id: '5' } } });

    await waitFor(() => expect(window.location.hash).toBe('#/jobs'));
  });
});
