import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import PurchaseOrderPicker from '@/components/PurchaseOrderPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('PurchaseOrderPicker', () => {
  it('searches all POs globally and emits the picked PO', async () => {
    api.get.mockResolvedValue({ results: [
      { po_id: 7, po_number: 'PO-7', business: { business_name: 'Acme' } },
    ] });
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(PurchaseOrderPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/purchase order/i), { target: { value: 'po-7' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/purchase-orders/?search=po-7&page_size=10');
    await fireEvent.mouseDown(await findByRole('button', { name: /PO-7/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ po_id: 7 }));
  });
});
