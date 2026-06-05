import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import EstimateLineItemModal from '@/components/EstimateLineItemModal.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.get.mockResolvedValue([]); // UnitsSelect
  api.post.mockResolvedValue({});
});

describe('EstimateLineItemModal', () => {
  it('creates a line item', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(EstimateLineItemModal, {
      props: { open: true, mode: 'create', estimateId: 7, onSaved },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Widget' } });
    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '5' } });
    await fireEvent.input(getByLabelText(/Price/), { target: { value: '10' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/estimates/7/line-items/', {
      description: 'Widget', qty: 5, units: 'none', price: 10, accounting_category: null,
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('closes via onClose', async () => {
    const onClose = vi.fn();
    const { getByRole } = render(EstimateLineItemModal, {
      props: { open: true, mode: 'create', estimateId: 7, onClose },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
  });
});
