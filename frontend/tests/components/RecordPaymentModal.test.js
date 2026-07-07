import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
vi.mock('@/lib/api.js', () => ({
  api: { post: vi.fn() },
  errorMessage: (e, fallback) => e?.data?.detail || e?.message || fallback,
}));
vi.mock('@/lib/paymentAccounts.js', () => ({ getPaymentAccounts: vi.fn() }));
import { api } from '@/lib/api.js';
import { getPaymentAccounts } from '@/lib/paymentAccounts.js';
import RecordPaymentModal from '@/components/RecordPaymentModal.svelte';

beforeEach(() => {
  api.post.mockReset();
  getPaymentAccounts.mockReset();
  getPaymentAccounts.mockResolvedValue([
    { qbo_account_id: '35', display_name: 'Checking', account_type: 'Bank' },
  ]);
});

describe('RecordPaymentModal', () => {
  it('posts with the auto-selected account, reference, amount', async () => {
    api.post.mockResolvedValue({ payment_id: 1 });
    const onSaved = vi.fn();
    const { getByLabelText, getByText, findByText } = render(RecordPaymentModal, {
      props: { open: true, billId: 7, defaultAmount: '100.00', onSaved, onClose: () => {} },
    });
    await findByText('Checking'); // wait for accounts to load + the first to auto-select
    await fireEvent.input(getByLabelText(/reference/i), { target: { value: '4471' } });
    await fireEvent.click(getByText(/save/i));
    expect(api.post).toHaveBeenCalledWith('/api/bills/7/payments/', expect.objectContaining({
      amount: '100.00', payment_account_id: '35', reference: '4471',
    }));
  });

  it('sends the typed amount as an exact string (no float coercion)', async () => {
    api.post.mockResolvedValue({ payment_id: 2 });
    const { getByLabelText, getByText, findByText } = render(RecordPaymentModal, {
      props: { open: true, billId: 7, defaultAmount: '', onSaved: () => {}, onClose: () => {} },
    });
    await findByText('Checking');
    await fireEvent.input(getByLabelText(/amount/i), { target: { value: '33.33' } });
    await fireEvent.click(getByText(/save/i));
    const [, body] = api.post.mock.calls[0];
    expect(body.amount).toBe('33.33');
    expect(typeof body.amount).toBe('string');
  });

  it('blocks save and shows error when amount is empty or zero', async () => {
    const { getByText, findByText } = render(RecordPaymentModal, {
      props: { open: true, billId: 7, defaultAmount: '', onSaved: () => {}, onClose: () => {} },
    });
    await findByText('Checking');
    await fireEvent.click(getByText(/save/i));
    expect(api.post).not.toHaveBeenCalled();
    expect(getByText(/amount must be greater than zero/i)).toBeTruthy();
  });

  it('blocks save with an error when no payment account is chosen', async () => {
    const { getByLabelText, getByText, findByText, container } = render(RecordPaymentModal, {
      props: { open: true, billId: 7, defaultAmount: '', onSaved: () => {}, onClose: () => {} },
    });
    await findByText('Checking');
    // clear the auto-selected account via the placeholder option
    await fireEvent.change(container.querySelector('select'), { target: { value: '' } });
    await fireEvent.input(getByLabelText(/amount/i), { target: { value: '50' } });
    await fireEvent.click(getByText(/save/i));
    expect(api.post).not.toHaveBeenCalled();
    // Native form validation is the blocker now: the required account select
    // is invalid, so the submit never fires (the JS message stays as the
    // backstop for browsers/paths that skip constraint validation).
    expect(container.querySelector('select:invalid')).toBeTruthy();
  });

  it('shows a configure-accounts message and no form when none are configured', async () => {
    getPaymentAccounts.mockResolvedValue([]);
    const { findByText, queryByText } = render(RecordPaymentModal, {
      props: { open: true, billId: 7, defaultAmount: '100.00', onSaved: () => {}, onClose: () => {} },
    });
    await findByText(/no payment accounts are configured/i);
    expect(queryByText('Save')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });
});
