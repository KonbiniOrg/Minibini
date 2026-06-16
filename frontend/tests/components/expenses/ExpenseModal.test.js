import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
vi.mock('@/lib/paymentAccounts.js', () => ({ getPaymentAccounts: vi.fn() }));

import { api } from '@/lib/api.js';
import { getPaymentAccounts } from '@/lib/paymentAccounts.js';
import { user } from '@/stores/auth.js';
import ExpenseModal from '@/components/expenses/ExpenseModal.svelte';

beforeEach(() => {
  api.get.mockReset();
  getPaymentAccounts.mockReset();
  user.set({ id: 2 });
  getPaymentAccounts.mockResolvedValue([]);
  api.get.mockResolvedValue({ results: [] });
});

describe('ExpenseModal', () => {
  it('renders nothing when closed', () => {
    const { queryByText } = render(ExpenseModal, { props: { open: false } });
    expect(queryByText('Add Expense')).toBeNull();
  });

  it('renders the expense form when open', () => {
    const { getByText, getByLabelText } = render(ExpenseModal, { props: { open: true } });
    expect(getByText('Add Expense')).toBeInTheDocument();
    expect(getByLabelText(/Amount/)).toBeInTheDocument();
  });

  it('pre-anchors the job from initialJob', () => {
    const { getByText } = render(ExpenseModal, {
      props: { open: true, initialJob: { job_id: 7, job_number: 'JOB-7' } },
    });
    // JobPicker renders the chosen job number with a Clear control when set.
    expect(getByText('JOB-7')).toBeInTheDocument();
  });
});
