import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('@/lib/paymentAccounts.js', () => ({ getPaymentAccounts: vi.fn() }));
vi.mock('svelte-spa-router', () => ({ link: () => ({}) }));

import { api } from '@/lib/api.js';
import { getPaymentAccounts } from '@/lib/paymentAccounts.js';
import { user } from '@/stores/auth.js';
import ExpensesList from '@/components/home/ExpensesList.svelte';

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
