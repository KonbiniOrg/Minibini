import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import SendPODialog from '@/components/purchaseorders/SendPODialog.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
});

describe('SendPODialog', () => {
  it('loads and pre-fills the send defaults', async () => {
    api.get.mockResolvedValue({ to: 'vendor@x.com', subject: 'PO PO-1', body: 'Please fulfil.' });
    const { findByDisplayValue } = render(SendPODialog, { props: { poId: 5, onSuccess: vi.fn(), onCancel: vi.fn() } });
    expect(await findByDisplayValue('vendor@x.com')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/api/purchase-orders/5/send-defaults/');
  });

  it('sends and reports success', async () => {
    api.get.mockResolvedValue({ to: 'vendor@x.com', subject: 'PO PO-1', body: 'Body' });
    api.post.mockResolvedValue({ ok: true });
    const onSuccess = vi.fn();
    const { findByRole } = render(SendPODialog, { props: { poId: 5, onSuccess, onCancel: vi.fn() } });

    await fireEvent.click(await findByRole('button', { name: 'Send' }));

    expect(api.post).toHaveBeenCalledWith('/api/purchase-orders/5/send/', {
      to: 'vendor@x.com', subject: 'PO PO-1', body: 'Body',
    });
    expect(onSuccess).toHaveBeenCalledWith({ ok: true });
  });

  it('shows an error when loading defaults fails', async () => {
    api.get.mockRejectedValue(new Error('boom'));
    const { findByText } = render(SendPODialog, { props: { poId: 5, onSuccess: vi.fn(), onCancel: vi.fn() } });
    expect(await findByText(/boom/)).toBeInTheDocument();
  });

  it('cancels via onCancel', async () => {
    api.get.mockResolvedValue({ to: 'a@b.com', subject: 's', body: 'b' });
    const onCancel = vi.fn();
    const { findByRole } = render(SendPODialog, { props: { poId: 5, onSuccess: vi.fn(), onCancel } });
    await fireEvent.click(await findByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
  });
});
