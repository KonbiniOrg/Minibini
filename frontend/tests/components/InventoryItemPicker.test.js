import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import InventoryItemPicker from '@/components/InventoryItemPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('InventoryItemPicker', () => {
  it('server-searches with params and emits the full row', async () => {
    api.get.mockResolvedValue({ results: [
      { inventory_item_id: 2, code: 'BOLT-14', description: 'Hex bolt', units: 'each', selling_price: '0.10' },
    ] });
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(InventoryItemPicker, {
      props: { onSelect, params: { is_active: true } },
    });
    await fireEvent.input(getByPlaceholderText(/price list|inventory/i), { target: { value: 'bolt' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/api/inventory/?search=bolt'));
    expect(api.get).toHaveBeenCalledWith(expect.stringContaining('is_active=true'));
    await fireEvent.click(await findByRole('button', { name: /BOLT-14/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ inventory_item_id: 2, units: 'each' }));
  });

  it('offers a freeform option that emits null', async () => {
    api.get.mockResolvedValue({ results: [] }); // dropdown opens even with no matches
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(InventoryItemPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/price list|inventory/i), { target: { value: 'x' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole('button', { name: /freeform/i }));
    expect(onSelect).toHaveBeenCalledWith(null);
  });
});
