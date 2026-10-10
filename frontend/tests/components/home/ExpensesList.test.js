import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() }, errorMessage: (e, fallback) => e?.message || fallback }));
vi.mock('@/lib/paymentAccounts.js', () => ({ getPaymentAccounts: vi.fn() }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import { getPaymentAccounts } from '@/lib/paymentAccounts.js';
import { user } from '@/stores/auth.js';
import ExpensesList from '@/components/home/ExpensesList.svelte';
import { viewMode } from '@/stores/viewMode.js';

beforeEach(() => {
  api.get.mockReset();
  getPaymentAccounts.mockReset();
  getPaymentAccounts.mockResolvedValue([]);
  user.set({ id: 2 });
});

describe('ExpensesList', () => {
  it('shows the empty state', async () => {
    api.get.mockResolvedValue({ results: [] });
    const { findByText } = render(ExpensesList);
    expect(await findByText('No recent expenses.')).toBeInTheDocument();
  });

  it('lists expenses', async () => {
    api.get.mockResolvedValue({ results: [{ id: 1, purchased_on: '2026-03-01', description: 'Lunch', amount: '12.50', status: 'submitted' }] });
    const { findByText } = render(ExpensesList);
    expect(await findByText('Lunch')).toBeInTheDocument();
  });

  it('reveals the new-expense form', async () => {
    api.get.mockResolvedValue({ results: [] });
    const { findByText, getByRole } = render(ExpensesList);
    await findByText('No recent expenses.');
    await fireEvent.click(getByRole('button', { name: '+ New expense' }));
    expect(await findByText('Submit new expense')).toBeInTheDocument();
  });
});

describe('ExpensesList — DataTable', () => {
  const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());
  const ALL = ['Date', 'Description', 'Job', 'Task', 'Amount', 'Status', 'Reimbursed'];
  it('renders the same seven columns in both densities with data-col and a right-aligned amount', async () => {
    api.get.mockResolvedValue({ results: [{ id: 1, purchased_on: '2026-03-01', description: 'Lunch', amount: '12.50', status: 'submitted', job_id: 7, job_number: 'JOB-7' }] });
    viewMode.set('lite');
    const { findByText, container } = render(ExpensesList);
    await findByText('Lunch');
    const table = container.querySelector('table.data-table');
    expect(headersOf(table)).toEqual(ALL);
    expect(table.querySelector('td[data-col="amount"]').getAttribute('style')).toMatch(/text-align:\s*right/);
    expect(table.querySelector('td[data-col="job"] a')).toHaveAttribute('href', '/jobs/7');
    viewMode.set('full');
    const { findByText: f2, container: c2 } = render(ExpensesList);
    await f2('Lunch');
    expect(headersOf(c2.querySelector('table.data-table'))).toEqual(ALL);
  });
});
