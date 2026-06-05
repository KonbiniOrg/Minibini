import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));

import { api } from '@/lib/api.js';
import MaterialModal from '@/components/MaterialModal.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.get.mockResolvedValue([]); // UnitsSelect / PLI picker
  api.post.mockResolvedValue({});
  api.patch.mockResolvedValue({});
});

describe('MaterialModal', () => {
  it('creates a freeform material on a task', async () => {
    const onSaved = vi.fn();
    const { getByLabelText, getByRole } = render(MaterialModal, {
      props: { open: true, mode: 'create', taskId: 10, onSaved },
    });
    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Steel' } });
    await fireEvent.input(getByLabelText(/Quantity/), { target: { value: '2' } });
    await fireEvent.input(getByLabelText(/Unit Cost/), { target: { value: '5' } });
    await fireEvent.input(getByLabelText(/Sell Price/), { target: { value: '8' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    expect(api.post).toHaveBeenCalledWith('/api/tasks/10/materials/', {
      description: 'Steel', quantity: 2, units: 'none', unit_cost: 5, sell_price: 8,
      price_list_item: null, accounting_category: null,
    });
    expect(onSaved).toHaveBeenCalled();
  });

  it('prompts to propagate a PLI price change, then patches with the flag', async () => {
    const { getByLabelText, getByRole, getByText } = render(MaterialModal, {
      props: {
        open: true, mode: 'edit',
        material: { material_id: 1, price_list_item: 99, unit_cost: 5, sell_price: 10, units: 'none', quantity: 2, description: 'X' },
      },
    });
    await fireEvent.input(getByLabelText(/Unit Cost/), { target: { value: '7' } });
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    // pricing differs from the PLI → propagate prompt appears (no API yet)
    expect(getByText('Update PLI with the new values?')).toBeInTheDocument();
    expect(api.patch).not.toHaveBeenCalled();

    await fireEvent.click(getByRole('button', { name: 'Yes, update PLI' }));
    expect(api.patch).toHaveBeenCalledWith('/api/materials/1/', {
      unit_cost: 7, sell_price: 10, propagate_to_pli: true,
    });
  });
});
