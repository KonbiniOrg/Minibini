import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import QBOConnectionCard from '@/components/QBOConnectionCard.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
});

describe('QBOConnectionCard', () => {
  it('renders the connected state', async () => {
    api.get.mockResolvedValue({ status: 'connected', realm_id: '123', connected_at: '2026-01-01' });
    const { findByText, getByRole } = render(QBOConnectionCard);
    expect(await findByText('Connected')).toBeInTheDocument();
    expect(getByRole('button', { name: 'Disconnect' })).toBeInTheDocument();
  });

  it('renders the not-connected state', async () => {
    api.get.mockResolvedValue({ status: 'not_connected' });
    const { findByText, getByRole } = render(QBOConnectionCard);
    expect(await findByText('Not connected')).toBeInTheDocument();
    expect(getByRole('link', { name: 'Connect to QuickBooks' })).toBeInTheDocument();
  });

  it('hides the card entirely on a 403 (no permission)', async () => {
    api.get.mockRejectedValue({ status: 403 });
    const { queryByText } = render(QBOConnectionCard);
    await waitFor(() => expect(queryByText('Loading QuickBooks status...')).toBeNull());
    expect(queryByText('QuickBooks Online')).toBeNull();
  });

  it('disconnects after confirmation, then reloads status', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    api.get
      .mockResolvedValueOnce({ status: 'connected', realm_id: '1', connected_at: '2026-01-01' })
      .mockResolvedValue({ status: 'not_connected' });
    api.post.mockResolvedValue({});

    const { findByText, getByRole } = render(QBOConnectionCard);
    await findByText('Connected');
    await fireEvent.click(getByRole('button', { name: 'Disconnect' }));

    expect(api.post).toHaveBeenCalledWith('/api/qbo/disconnect/');
    expect(await findByText('Not connected')).toBeInTheDocument();
    confirmSpy.mockRestore();
  });

  it('does not disconnect if the confirm is cancelled', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    api.get.mockResolvedValue({ status: 'connected', realm_id: '1', connected_at: '2026-01-01' });

    const { findByText, getByRole } = render(QBOConnectionCard);
    await findByText('Connected');
    await fireEvent.click(getByRole('button', { name: 'Disconnect' }));

    expect(api.post).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });
});
