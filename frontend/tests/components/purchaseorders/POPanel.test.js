import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import POPanel from '@/components/purchaseorders/POPanel.svelte';

const job = { job_id: 7, job_number: 'JOB-7', name: 'Widget' };

beforeEach(() => {
  api.get.mockReset();
});

describe('POPanel', () => {
  it('lists purchase orders touching the job with a linked number, status pill, vendor, and total', async () => {
    api.get.mockResolvedValue({
      results: [
        { po_id: 11, po_number: 'PO-2026-0011', status: 'issued', business_name: 'Acme Supply', po_total: '150.00' },
      ],
    });
    const { findByRole, getByText } = render(POPanel, { props: { job } });
    const link = await findByRole('link', { name: 'PO-2026-0011' });
    expect(link).toHaveAttribute('href', '#/purchase-orders/11');
    expect(getByText('Acme Supply')).toBeInTheDocument();
    expect(getByText('issued')).toHaveClass('status-issued');
    expect(getByText('$150.00')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/purchase-orders/?job=7');
  });

  it('shows a plain empty state with no create affordance when the job has no purchase orders', async () => {
    api.get.mockResolvedValue({ results: [] });
    const { findByText, queryByRole } = render(POPanel, { props: { job } });
    expect(await findByText('No purchase orders touch this job yet.')).toBeInTheDocument();
    expect(queryByRole('button', { name: /new purchase order/i })).toBeNull();
    expect(queryByRole('link', { name: /new purchase order/i })).toBeNull();
  });

  it('shows an error message when the fetch fails', async () => {
    api.get.mockRejectedValue(new Error('boom'));
    const { findByText } = render(POPanel, { props: { job } });
    expect(await findByText('boom')).toBeInTheDocument();
  });
});
