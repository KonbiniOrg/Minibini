import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), patch: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
import JobDetail from '@/components/jobs/JobDetail.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue([]);
  user.set({ permissions: [] });
});

function baseJob(overrides = {}) {
  return {
    job_id: 1, job_number: 'JOB-1', name: 'J', status: 'in_progress',
    tasks: [], materials: [], ...overrides,
  };
}

describe('JobDetail invoiced indicator', () => {
  it('renders an Invoiced link on an invoiced task', () => {
    const job = baseJob({
      tasks: [{ task_id: 7, name: 'Cut', status: 'complete',
                invoice: { id: 3, number: 'INV-3' } }],
    });
    const { getByText } = render(JobDetail, { props: { job, expenses: [] } });
    const link = getByText(/INV-3/);
    expect(link.getAttribute('href')).toBe('#/invoices/3');
  });

  it('omits the link when task.invoice is null', () => {
    const job = baseJob({
      tasks: [{ task_id: 7, name: 'Cut', status: 'complete', invoice: null }],
    });
    const { queryByRole } = render(JobDetail, { props: { job, expenses: [] } });
    // No <a> element whose accessible name matches "Invoiced" should be present.
    expect(queryByRole('link', { name: /Invoiced/ })).toBeNull();
  });

  it('renders an Invoiced link on an invoiced material', async () => {
    const job = baseJob({
      materials: [{ material_id: 11, description: 'Steel', quantity: '1',
                    unit_cost: '10.00', units: 'kg',
                    consumption_state: 'pending',
                    invoice: { id: 5, number: 'INV-5' } }],
    });
    const { getByText, getByRole } = render(JobDetail, { props: { job, expenses: [] } });
    // Open the Materials & Expenses section
    await fireEvent.click(getByText('Materials'));
    const link = getByText(/INV-5/);
    expect(link.getAttribute('href')).toBe('#/invoices/5');
  });

  it('renders an Invoiced link on a loose expense', async () => {
    const expenses = [
      { id: 20, amount: '40.00', material: null, description: 'FedEx',
        accounting_category_name: 'Freight',
        invoice: { id: 7, number: 'INV-7' } },
    ];
    const job = baseJob({ materials: [] });
    const { getByText } = render(JobDetail, { props: { job, expenses } });
    // Open the Materials & Expenses section
    await fireEvent.click(getByText('Materials'));
    const link = getByText(/INV-7/);
    expect(link.getAttribute('href')).toBe('#/invoices/7');
  });
});
