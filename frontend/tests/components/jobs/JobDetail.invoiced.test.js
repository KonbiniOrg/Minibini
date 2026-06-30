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
  // The Tasks & Materials pillar's read-only tables render an "Invoiced · NUM"
  // link (href to the invoice) on billed tasks/materials/expenses.
  it('renders an Invoiced link on an invoiced task', async () => {
    const job = baseJob({
      tasks: [{ task_id: 7, name: 'Cut', status: 'complete',
                invoice: { id: 3, number: 'INV-3' } }],
    });
    // A job with tasks opens the Tasks & Materials pillar by default.
    const { findByRole } = render(JobDetail, { props: { job, expenses: [] } });
    const link = await findByRole('link', { name: /Invoiced/ });
    expect(link.getAttribute('href')).toBe('#/invoices/3');
  });

  it('omits the link when task.invoice is null', async () => {
    const job = baseJob({
      tasks: [{ task_id: 7, name: 'Cut', status: 'complete', invoice: null }],
    });
    const { findByText, queryByRole } = render(JobDetail, { props: { job, expenses: [] } });
    await findByText('Cut'); // wait for the table to render
    expect(queryByRole('link', { name: /Invoiced/ })).toBeNull();
  });

  it('renders an Invoiced link on an invoiced material', async () => {
    const job = baseJob({
      materials: [{ material_id: 11, description: 'Steel', quantity: '1',
                    unit_cost: '10.00', units: 'kg',
                    consumption_state: 'pending',
                    invoice: { id: 5, number: 'INV-5' } }],
    });
    const { getByText, findByRole } = render(JobDetail, { props: { job, expenses: [] } });
    await fireEvent.click(getByText('Tasks & Materials')); // open the pillar (no tasks → collapsed by default)
    const link = await findByRole('link', { name: /Invoiced/ });
    expect(link.getAttribute('href')).toBe('#/invoices/5');
  });

  it('renders an Invoiced link on a loose expense', async () => {
    const expenses = [
      { id: 20, amount: '40.00', material: null, description: 'FedEx',
        accounting_category_name: 'Freight',
        invoice: { id: 7, number: 'INV-7' } },
    ];
    const job = baseJob({ materials: [] });
    const { getByText, findByRole } = render(JobDetail, { props: { job, expenses } });
    await fireEvent.click(getByText('Tasks & Materials')); // open the pillar
    const link = await findByRole('link', { name: /Invoiced/ });
    expect(link.getAttribute('href')).toBe('#/invoices/7');
  });
});
