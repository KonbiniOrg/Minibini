import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
vi.mock('@/lib/paymentAccounts.js', () => ({ getPaymentAccounts: vi.fn() }));

import { api } from '@/lib/api.js';
import { getPaymentAccounts } from '@/lib/paymentAccounts.js';
import { user } from '@/stores/auth.js';
import ExpenseForm from '@/components/expenses/ExpenseForm.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  getPaymentAccounts.mockReset();
  user.set({ id: 2 });
  getPaymentAccounts.mockResolvedValue([{ qbo_account_id: 'acc1', display_name: 'Visa' }]);
  api.get.mockImplementation((url) => {
    if (url === '/api/accounting-categories/') {
      return Promise.resolve({ results: [{ id: 1, name: 'Meals', qbo_expense_account_id: 'a1' }] });
    }
    if (url === '/api/users/') return Promise.resolve({ results: [{ id: 2, first_name: 'Sam', last_name: 'X', username: 'sam' }] });
    return Promise.resolve({ results: [] });
  });
  api.post.mockResolvedValue({ id: 99 });
});

describe('ExpenseForm', () => {
  it('submits a personal expense', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, findByRole, getByRole } = render(ExpenseForm, { props: { onSaved, onCancel: vi.fn() } });

    // category select appears after the dropdowns load
    await findByRole('option', { name: 'Meals' });
    await fireEvent.input(getByLabelText(/Amount/), { target: { value: '20' } });
    await fireEvent.change(getByLabelText(/Category/), { target: { value: '1' } });
    await fireEvent.click(getByRole('button', { name: 'Submit expense' }));

    expect(api.post).toHaveBeenCalledWith('/api/expenses/', expect.objectContaining({
      amount: 20, accounting_category: 1, payment_method: 'personal',
    }));
    expect(onSaved).toHaveBeenCalledWith({ id: 99 });
  });

  it('reveals the reference field when paid by a company account', async () => {
    const { findByLabelText, findByRole, queryByLabelText } = render(ExpenseForm, { props: { onSaved: vi.fn(), onCancel: vi.fn() } });
    const paidBy = await findByLabelText(/Paid by/);
    await findByRole('option', { name: 'Visa' }); // wait for payment accounts to load
    expect(queryByLabelText(/Reference/)).toBeNull();
    await fireEvent.change(paidBy, { target: { value: 'company:acc1' } });
    expect(await findByLabelText(/Reference/)).toBeInTheDocument();
  });

  it('surfaces field errors from the server', async () => {
    api.post.mockRejectedValue({ data: { amount: ['Too high'] } });
    const { getByLabelText, findByRole, getByRole, findByText } = render(ExpenseForm, { props: { onSaved: vi.fn(), onCancel: vi.fn() } });
    await findByRole('option', { name: 'Meals' });
    await fireEvent.input(getByLabelText(/Amount/), { target: { value: '20' } });
    await fireEvent.change(getByLabelText(/Category/), { target: { value: '1' } });
    await fireEvent.click(getByRole('button', { name: 'Submit expense' }));
    expect(await findByText('Too high')).toBeInTheDocument();
  });
});
