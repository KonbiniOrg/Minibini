import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), patch: vi.fn(), post: vi.fn(), delete: vi.fn() },
  errorMessage: (e, fallback) =>
    e?.data?.detail || e?.message || fallback || 'Something went wrong.',
}));

import { api } from '@/lib/api.js';
import WizardLineItemCard from '@/components/wizards/WizardLineItemCard.svelte';

function lineItem(overrides) {
  return { line_item_id: 7, line_number: 1, description: 'Line', qty: '2', units: 'none', price: '10', sources: [], ...overrides };
}

beforeEach(() => {
  api.get.mockReset();
  api.patch.mockReset();
  api.post.mockReset();
  api.delete.mockReset();
  api.get.mockResolvedValue([]); // UnitsSelect
  api.patch.mockResolvedValue({ description: 'Line2', qty: '2', units: 'none', price: '10' });
  api.delete.mockResolvedValue({});
  api.post.mockResolvedValue({});
});

describe('WizardLineItemCard', () => {
  it('saves an edited line item', async () => {
    const { getByPlaceholderText, getByRole } = render(WizardLineItemCard, {
      props: { lineItem: lineItem(), apiBase: '/api/estimates/3' },
    });
    await fireEvent.input(getByPlaceholderText('Name this line item…'), { target: { value: 'Line2' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(api.patch).toHaveBeenCalledWith('/api/estimates/3/line-items/7/', {
      description: 'Line2', qty: '2', units: 'none', price: '10',
    });
  });

  it('deletes the line item', async () => {
    const { getByRole } = render(WizardLineItemCard, {
      props: { lineItem: lineItem(), apiBase: '/api/estimates/3' },
    });
    await fireEvent.click(getByRole('button', { name: '×' }));
    expect(api.delete).toHaveBeenCalledWith('/api/estimates/3/line-items/7/');
  });

  it('registers a flush; flushing saves a dirty card and no-ops a clean one', async () => {
    let flush;
    const registerFlush = vi.fn((id, fn) => { if (fn) flush = fn; });
    const { getByPlaceholderText } = render(WizardLineItemCard, {
      props: { lineItem: lineItem(), apiBase: '/api/estimates/3', registerFlush },
    });
    await waitFor(() => expect(registerFlush).toHaveBeenCalledWith(7, expect.any(Function)));
    // clean → no patch
    await flush();
    expect(api.patch).not.toHaveBeenCalled();
    // dirty → patches
    await fireEvent.input(getByPlaceholderText('Name this line item…'), { target: { value: 'Edited' } });
    await flush();
    expect(api.patch).toHaveBeenCalledWith('/api/estimates/3/line-items/7/',
      expect.objectContaining({ description: 'Edited' }));
  });

  it('flush rejects when the save fails (so Done can block navigation)', async () => {
    api.patch.mockRejectedValueOnce(new Error('boom'));
    let flush;
    const registerFlush = vi.fn((id, fn) => { if (fn) flush = fn; });
    const { getByPlaceholderText } = render(WizardLineItemCard, {
      props: { lineItem: lineItem(), apiBase: '/api/estimates/3', registerFlush },
    });
    await waitFor(() => expect(registerFlush).toHaveBeenCalled());
    await fireEvent.input(getByPlaceholderText('Name this line item…'), { target: { value: 'Edited' } });
    await expect(flush()).rejects.toThrow('boom');
  });

  it('shows an operation error under the buttons when a manual save fails', async () => {
    const err = Object.assign(new Error('Request failed'), {
      status: 400, data: { detail: 'Invoice is not editable.' },
    });
    api.patch.mockRejectedValueOnce(err);
    const { getByPlaceholderText, getByRole, findByRole } = render(WizardLineItemCard, {
      props: { lineItem: lineItem(), apiBase: '/api/estimates/3' },
    });
    await fireEvent.input(getByPlaceholderText('Name this line item…'), { target: { value: 'Line2' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(await findByRole('alert')).toHaveTextContent('Invoice is not editable.');
  });

  it('shows a field error under the inputs when a manual save fails validation', async () => {
    const err = Object.assign(new Error('Request failed'), {
      status: 400, data: { qty: ['A valid number is required.'] },
    });
    api.patch.mockRejectedValueOnce(err);
    const { getByPlaceholderText, getByRole, findByText } = render(WizardLineItemCard, {
      props: { lineItem: lineItem(), apiBase: '/api/estimates/3' },
    });
    await fireEvent.input(getByPlaceholderText('Name this line item…'), { target: { value: 'Line2' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));
    expect(await findByText('A valid number is required.')).toBeInTheDocument();
  });

  it('flags a bundled price that is out of sync with its atoms', () => {
    // sources sum 10 over qty 2 → expected $5/unit, but saved price is $10 → out of sync
    const { getByText } = render(WizardLineItemCard, {
      props: {
        lineItem: lineItem({ price: '10', sources: [{ source_id: 9, description: 'atom', computed_amount: '10' }] }),
        apiBase: '/api/estimates/3',
      },
    });
    expect(getByText(/out of sync with atoms/)).toBeInTheDocument();
  });
});
