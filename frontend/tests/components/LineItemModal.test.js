import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import LineItemModal from '@/components/LineItemModal.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.get.mockResolvedValue([]); // UnitsSelect (/api/settings/units/) + InventoryItemPicker
  api.post.mockResolvedValue({});
  api.patch.mockResolvedValue({});
});

describe('LineItemModal', () => {
  it('creates a manual line item against the given apiBase', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(LineItemModal, {
      props: { open: true, mode: 'create', apiBase: '/api/estimates/7', onSaved },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Widget' } });
    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '5' } });
    await fireEvent.input(getByLabelText('Price'), { target: { value: '10' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/estimates/7/line-items/', {
      description: 'Widget', qty: 5, units: 'none', price: 10, accounting_category: null,
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('patches an existing line item in edit mode', async () => {
    const onSaved = vi.fn();
    const item = { line_item_id: 3, description: 'Old', qty: 2, units: 'none', price: 4, accounting_category: null };
    const { getByLabelText, getByRole } = render(LineItemModal, {
      props: { open: true, mode: 'edit', apiBase: '/api/estimates/7', item, onSaved },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'New' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.patch).toHaveBeenCalledWith('/api/estimates/7/line-items/3/', {
      description: 'New', qty: 2, units: 'none', price: 4, accounting_category: null,
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('requires an inventory item before saving in catalog mode', async () => {
    const { getByLabelText, getByRole, findByText } = render(LineItemModal, {
      props: { open: true, mode: 'create', apiBase: '/api/estimates/7' },
    });
    await fireEvent.click(getByLabelText(/From Inventory/));
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(await findByText('Select an inventory item.')).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('closes via onClose', async () => {
    const onClose = vi.fn();
    const { getByRole } = render(LineItemModal, {
      props: { open: true, mode: 'create', apiBase: '/api/estimates/7', onClose },
    });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
  });
});
