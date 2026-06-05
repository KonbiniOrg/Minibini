import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('@/lib/paymentAccounts.js', () => ({ getPaymentAccounts: vi.fn() }));

import { api } from '@/lib/api.js';
import { getPaymentAccounts } from '@/lib/paymentAccounts.js';
import UserReimbursementPanel from '@/components/expenses/UserReimbursementPanel.svelte';

const OUTSTANDING = [
  { id: 1, purchased_on: '2026-03-01', description: 'Lunch', accounting_category: 'Meals', amount: '12.50' },
];

beforeEach(() => {
  api.get.mockReset();
  getPaymentAccounts.mockReset();
  getPaymentAccounts.mockResolvedValue([]);
  api.get.mockImplementation((url) => {
    if (url.includes('/api/expenses/') && url.includes('status=submitted')) return Promise.resolve({ results: OUTSTANDING });
    return Promise.resolve({ results: [] });
  });
});

describe('UserReimbursementPanel', () => {
  it('loads and lists outstanding reimbursements', async () => {
    const { findByText } = render(UserReimbursementPanel, { props: { user: { id: 7 } } });
    expect(await findByText('Lunch')).toBeInTheDocument();
  });

  it('reveals the batch action once a row is selected', async () => {
    const { findAllByRole, findByText } = render(UserReimbursementPanel, { props: { user: { id: 7 } } });
    const checkboxes = await findAllByRole('checkbox');
    // [0] is the header select-all; [1] is the first row.
    await fireEvent.click(checkboxes[1]);
    expect(await findByText(/Reimburse selected/)).toBeInTheDocument();
  });
});
