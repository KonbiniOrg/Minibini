// frontend/tests/components/purchaseorders/VendorPicker.test.js
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
import { api } from '@/lib/api.js';
import VendorPicker from '@/components/purchaseorders/VendorPicker.svelte';

const rows = [
  { business_id: 17, business_name: 'Rugby Architectural', contact_id: 88, last_ordered: '2026-08-02',
    last_price: '62.40', vendor_sku: 'BB34P-48', po_number: 'PO0120', times: 6 },
  { business_id: 59, business_name: 'Royal Plywood', contact_id: null, last_ordered: '2026-07-09',
    last_price: '73.33', vendor_sku: '', po_number: 'PO0012', times: 1 },
];

beforeEach(() => { api.get.mockReset(); api.get.mockResolvedValue({ results: [] }); });

describe('VendorPicker', () => {
  it('opens in recent mode, preselects the first vendor and reports it', () => {
    const onSelect = vi.fn();
    const { getByRole } = render(VendorPicker, { props: { vendors: rows, onSelect } });
    const select = getByRole('combobox');
    expect(select.value).toBe('17');
    expect(onSelect).toHaveBeenCalledWith(rows[0]);
    const labels = Array.from(select.options).map((o) => o.textContent);
    expect(labels[0]).toMatch(/Rugby Architectural/);
    expect(labels[0]).toMatch(/\$62\.40/);
    expect(labels[0]).toMatch(/SKU BB34P-48/);
    expect(labels[1]).not.toMatch(/SKU/);            // empty SKU segment omitted
    expect(labels.at(-1)).toMatch(/Search all businesses/);
  });

  it('choosing another recent vendor reports that row', async () => {
    const onSelect = vi.fn();
    const { getByRole } = render(VendorPicker, { props: { vendors: rows, onSelect } });
    await fireEvent.change(getByRole('combobox'), { target: { value: '59' } });
    expect(onSelect).toHaveBeenLastCalledWith(rows[1]);
  });

  it('"Search all businesses…" switches to the type-ahead with a back link; back restores recent', async () => {
    const onSelect = vi.fn();
    const { getByRole, getByPlaceholderText, queryByRole, getByText } = render(VendorPicker, { props: { vendors: rows, onSelect } });
    await fireEvent.change(getByRole('combobox'), { target: { value: '__search' } });
    expect(onSelect).toHaveBeenLastCalledWith(null);
    expect(getByPlaceholderText('Search business…')).toBeInTheDocument();
    expect(queryByRole('combobox')).toBeNull();
    await fireEvent.click(getByText('back to recent vendors'));
    expect(getByRole('combobox').value).toBe('17');
    expect(onSelect).toHaveBeenLastCalledWith(rows[0]);
  });

  it('a search pick reports the business; Clear returns to recent mode', async () => {
    api.get.mockResolvedValue({ results: [{ business_id: 5, business_name: 'Acme Steel', default_contact: 9 }] });
    const onSelect = vi.fn();
    const { getByRole, getByPlaceholderText, findByRole, queryByText } = render(VendorPicker, { props: { vendors: rows, onSelect } });
    await fireEvent.change(getByRole('combobox'), { target: { value: '__search' } });
    await fireEvent.input(getByPlaceholderText('Search business…'), { target: { value: 'ac' } });
    await new Promise((r) => setTimeout(r, 300));
    await fireEvent.mouseDown(await findByRole('button', { name: /Acme Steel/ }));
    expect(onSelect).toHaveBeenLastCalledWith(expect.objectContaining({ business_id: 5 }));
    expect(queryByText('back to recent vendors')).toBeNull();   // hidden once something is chosen
    await fireEvent.click(await findByRole('button', { name: 'Clear' }));
    expect(getByRole('combobox').value).toBe('17');
    expect(onSelect).toHaveBeenLastCalledWith(rows[0]);
  });

  it('with no history it opens in search mode with no back link', () => {
    const onSelect = vi.fn();
    const { getByPlaceholderText, queryByRole, queryByText } = render(VendorPicker, { props: { vendors: [], onSelect } });
    expect(getByPlaceholderText('Search business…')).toBeInTheDocument();
    expect(queryByRole('combobox')).toBeNull();
    expect(queryByText('back to recent vendors')).toBeNull();
    expect(onSelect).not.toHaveBeenCalled();
  });
});
