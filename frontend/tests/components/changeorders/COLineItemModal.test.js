import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import COLineItemModal from '@/components/changeorders/COLineItemModal.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.get.mockResolvedValue([]); // UnitsSelect
  api.post.mockResolvedValue({});
});

describe('COLineItemModal', () => {
  it('creates an "add" line', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(COLineItemModal, {
      props: { open: true, mode: 'create', coId: 3, onSaved },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'New line' } });
    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/Price/), { target: { value: '50' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/change-orders/3/line-items/', {
      action: 'add', target_line_item: null, description: 'New line', qty: 2, units: 'none', price: 50,
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('hides the line fields for a plain remove', async () => {
    const { getByLabelText, queryByLabelText } = render(COLineItemModal, {
      props: {
        open: true, mode: 'create', coId: 3,
        estimateLines: [{ line_item_id: 7, line_number: 1, description: 'Old', price: 10, qty: 1, units: 'ea' }],
      },
    });
    await fireEvent.change(getByLabelText(/Action/), { target: { value: 'remove' } });
    expect(queryByLabelText(/Description/)).toBeNull();
    expect(getByLabelText(/Target estimate line/)).toBeInTheDocument();
  });
});
