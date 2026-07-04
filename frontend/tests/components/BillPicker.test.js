import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import BillPicker from '@/components/BillPicker.svelte';

beforeEach(() => { api.get.mockReset(); });

describe('BillPicker', () => {
  it('searches and emits the picked bill', async () => {
    api.get.mockResolvedValue({ results: [
      { bill_id: 4, vendor_invoice_number: 'INV-7788', business: { business_name: 'Acme' } },
    ] });
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByRole } = render(BillPicker, { props: { onSelect } });
    await fireEvent.input(getByPlaceholderText(/bill/i), { target: { value: '7788' } });
    await new Promise((r) => setTimeout(r, 300));
    expect(api.get).toHaveBeenCalledWith('/api/bills/?search=7788&page_size=25');
    await fireEvent.mouseDown(await findByRole('button', { name: /INV-7788/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ bill_id: 4 }));
  });
});
