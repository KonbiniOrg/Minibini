import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import LineItemForm from '@/components/purchaseorders/LineItemForm.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue([]); // UnitsSelect units fetch (and others)
});

describe('LineItemForm', () => {
  it('submits a manual line with the quantity coerced to a number', async () => {
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole } = render(LineItemForm, { props: { onSubmit, onCancel: vi.fn() } });

    await fireEvent.input(getByLabelText(/Description/), { target: { value: 'Bolt' } });
    await fireEvent.input(getByLabelText(/Qty/), { target: { value: '3' } });
    await fireEvent.input(getByLabelText(/^Price/), { target: { value: '2.50' } }); // not "From Price List"
    await fireEvent.click(getByRole('button', { name: 'Add' }));

    // type="number" inputs bind as numbers, so price arrives as 2.5 (not '2.50').
    expect(onSubmit).toHaveBeenCalledWith({
      description: 'Bolt', qty: 3, units: 'none', price: 2.5,
    });
  });

  it('switches to From Price List mode', async () => {
    const { getByLabelText, queryByLabelText } = render(LineItemForm, { props: { onSubmit: vi.fn(), onCancel: vi.fn() } });
    // manual mode shows a Description field...
    expect(getByLabelText(/Description/)).toBeInTheDocument();
    await fireEvent.click(getByLabelText('From Price List'));
    // ...pli mode hides it
    expect(queryByLabelText(/Description/)).toBeNull();
  });

  it('cancels via onCancel', async () => {
    const onCancel = vi.fn();
    const { getByRole } = render(LineItemForm, { props: { onSubmit: vi.fn(), onCancel } });
    await fireEvent.click(getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalled();
  });

  it('prefills from an inventory item — fetches it and submits a PLI line', async () => {
    api.get.mockImplementation((url) =>
      url.startsWith('/api/inventory/')
        ? Promise.resolve({ inventory_item_id: 7, code: 'FELT', description: 'grey felt', units: 'sheet', purchase_price: '4.00' })
        : Promise.resolve([]));
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole, findByText } = render(LineItemForm, {
      props: { onSubmit, onCancel: vi.fn(), prefill: { inventory_item: 7 } },
    });
    await findByText(/FELT — grey felt/);  // switched to PLI mode + item selected
    await fireEvent.input(getByLabelText(/Qty/), { target: { value: '2' } });
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith({ inventory_item: 7, qty: 2 });
  });

  it('prefills manual fields from a neutral prefill (no inventory item)', async () => {
    const onSubmit = vi.fn();
    const { getByLabelText, getByRole } = render(LineItemForm, {
      props: { onSubmit, onCancel: vi.fn(), prefill: { qty: 5, description: 'misc', price: '3.00' } },
    });
    await vi.waitFor(() => expect(getByLabelText(/Description/).value).toBe('misc'));
    await fireEvent.click(getByRole('button', { name: 'Add' }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ description: 'misc', qty: 5 }));
  });
});
