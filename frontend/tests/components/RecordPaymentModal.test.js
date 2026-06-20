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
});
