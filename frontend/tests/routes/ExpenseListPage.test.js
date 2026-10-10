import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, findByText } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) => e?.message || fallback,
}));
vi.mock('svelte-spa-router', () => ({ push: vi.fn(), link: () => {} }));

import { api } from '@/lib/api.js';
import { viewMode } from '@/stores/viewMode.js';
import ExpenseListPage from '@/routes/expenses/ExpenseListPage.svelte';

const expense = {
  id: 1, purchased_on: '2026-09-01', purchased_by: 4, purchased_by_name: 'Dana Doe',
  description: 'Paint', job_id: 7, job_number: 'JOB-7', job_name: 'Signage', task_name: 'Cut',
  accounting_category_name: 'Materials', amount: '12.50', payment_method: 'personal', status: 'submitted',
  qbo_sync_status: null, invoice: null,
};
const outstandingRow = { purchased_by: 4, full_name: 'Dana Doe', username: 'dana', count: 3, total: '40.00', oldest_purchased_on: '2026-08-01' };

const headersOf = (t) => Array.from(t.querySelectorAll('thead th')).map((th) => th.textContent.trim());
const MAIN = ['Date', 'Who (purchased by)', 'Description', 'Job', 'Task', 'Category', 'Amount', 'Paid', 'Status', 'Actions'];

function mock({ expenses = [expense], users = [outstandingRow] } = {}) {
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/expenses/')) return Promise.resolve({ results: expenses });
    if (url.startsWith('/api/reimbursements/outstanding-summary/')) return Promise.resolve({ users });
    return Promise.resolve({});
  });
}

beforeEach(() => {
  api.get.mockReset();
  viewMode.set('lite');
  mock();
});

describe('ExpenseListPage — DataTable', () => {
  it('renders the expenses table with the same ten columns in lite and full, data-col stamped', async () => {
    const { container } = render(ExpenseListPage);
    await findByText(container, 'Paint');
    const tables = container.querySelectorAll('table.data-table');
    const main = tables[tables.length - 1];
    expect(headersOf(main)).toEqual(MAIN);
    expect(main.querySelector('td[data-col="amount"]').textContent.trim()).toBe('$12.50');
    expect(main.querySelector('td[data-col="job"] a')).toHaveAttribute('href', '/jobs/7');
    expect(main.querySelector('td[data-col="actions"]').textContent).toContain('reject');
    viewMode.set('full');
    const { container: c2 } = render(ExpenseListPage);
    await findByText(c2, 'Paint');
    const t2 = c2.querySelectorAll('table.data-table');
    expect(headersOf(t2[t2.length - 1])).toEqual(MAIN);
  });

  it('renders the outstanding-reimbursements summary as a headed table', async () => {
    const { container } = render(ExpenseListPage);
    await findByText(container, 'Outstanding reimbursements');
    const summary = container.querySelectorAll('table.data-table')[0];
    expect(headersOf(summary)).toEqual(['Who', 'Items', 'Total', 'Oldest purchase']);
    expect(summary.querySelector('td[data-col="who"] a')).toHaveAttribute('href', '/reimbursements/4');
    expect(summary.querySelector('td[data-col="items"]').textContent.trim()).toBe('3 items');
    expect(summary.querySelector('td[data-col="oldest"]').textContent.trim()).toBe('2026-08-01');
  });

  it('shows "No expenses match." when the list is empty', async () => {
    mock({ expenses: [], users: [] });
    const { container } = render(ExpenseListPage);
    expect(await findByText(container, 'No expenses match.')).toBeInTheDocument();
  });
});
