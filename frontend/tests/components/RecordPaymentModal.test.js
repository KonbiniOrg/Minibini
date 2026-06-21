import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
vi.mock('@/lib/api.js', () => ({ api: { post: vi.fn() } }));
import { api } from '@/lib/api.js';
import RecordPaymentModal from '@/components/RecordPaymentModal.svelte';

beforeEach(() => api.post.mockReset());

describe('RecordPaymentModal', () => {
  it('posts payment with method/reference/amount and requires amount', async () => {
    api.post.mockResolvedValue({ payment_id: 1 });
    const onSaved = vi.fn();
    const { getByLabelText, getByText } = render(RecordPaymentModal, {
      props: { open: true, billId: 7, defaultAmount: '100.00', onSaved, onClose: () => {} },
    });
    await fireEvent.input(getByLabelText(/reference/i), { target: { value: '4471' } });
    await fireEvent.click(getByText(/save/i));
    expect(api.post).toHaveBeenCalledWith('/api/bills/7/payments/', expect.objectContaining({
      amount: '100.00', method: 'check', reference: '4471',
    }));
  });

  it('sends the typed amount as an exact string (no float coercion)', async () => {
    // A non-binary-representable value like 33.33 must reach the API as the
    // string "33.33", not a JS number — a number serializes to a float that
    // Django converts to 33.3299... and rejects as >2 decimal places.
    api.post.mockResolvedValue({ payment_id: 2 });
    const { getByLabelText, getByText } = render(RecordPaymentModal, {
      props: { open: true, billId: 7, defaultAmount: '', onSaved: () => {}, onClose: () => {} },
    });
    await fireEvent.input(getByLabelText(/amount/i), { target: { value: '33.33' } });
    await fireEvent.click(getByText(/save/i));
    const [, body] = api.post.mock.calls[0];
    expect(body.amount).toBe('33.33');
    expect(typeof body.amount).toBe('string');
  });

  it('blocks save and shows error when amount is empty or zero', async () => {
    const onSaved = vi.fn();
    const { getByText } = render(RecordPaymentModal, {
      props: { open: true, billId: 7, defaultAmount: '', onSaved, onClose: () => {} },
    });
    await fireEvent.click(getByText(/save/i));
    expect(api.post).not.toHaveBeenCalled();
    expect(getByText(/amount must be greater than zero/i)).toBeTruthy();
  });
});
