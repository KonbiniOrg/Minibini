import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

import { api } from '@/lib/api.js';
import InventoryItemForm from '@/components/inventory/InventoryItemForm.svelte';

const CATS = [{ id: 7, code: 'MAT', name: 'Materials' }];

beforeEach(() => {
  api.get.mockReset();
  api.post.mockReset();
  api.patch.mockReset();
  api.get.mockImplementation((url) => {
    if (url.startsWith('/api/settings/units/')) return Promise.resolve(['none', 'ea', 'sheet']);
    if (url.startsWith('/api/accounting-categories/')) return Promise.resolve({ results: CATS });
    return Promise.resolve({ results: [] });
  });
  api.post.mockResolvedValue({ price_list_item_id: 99 });
  api.patch.mockResolvedValue({ price_list_item_id: 1 });
});

describe('InventoryItemForm', () => {
  it('creates an item with catalog default true and omits blank selling price', async () => {
    const onSaved = vi.fn();
    const { getByRole, findByRole } = render(InventoryItemForm, { props: { onSaved } });
    await findByRole('option', { name: /Materials/ });

    await fireEvent.input(document.querySelector('input[type=text]'), { target: { value: 'NEW-1' } });
    // accounting_category is the only <select required>; pick it.
    const catSelect = document.querySelector('select[required]') || document.querySelectorAll('select')[document.querySelectorAll('select').length - 1];
    await fireEvent.change(catSelect, { target: { value: '7' } });
    await fireEvent.click(getByRole('button', { name: 'Create' }));

    await vi.waitFor(() => expect(api.post).toHaveBeenCalled());
    const [url, payload] = api.post.mock.calls[0];
    expect(url).toBe('/api/inventory/');
    expect(payload.code).toBe('NEW-1');
    expect(payload.is_catalog).toBe(true);
    expect('selling_price' in payload).toBe(false);
    expect(onSaved).toHaveBeenCalled();
  });

  it('edits via PATCH and can demote to a lot (uncheck catalog)', async () => {
    const item = {
      price_list_item_id: 5, code: 'OLD', description: 'd', units: 'ea',
      purchase_price: '4.00', selling_price: '8.00', is_catalog: true, is_active: true,
      accounting_category: 7,
    };
    const { getByRole, findByRole, getByLabelText } = render(InventoryItemForm, { props: { item } });
    await findByRole('option', { name: /Materials/ });

    await fireEvent.click(getByLabelText(/Catalog item/));
    await fireEvent.click(getByRole('button', { name: 'Save' }));

    await vi.waitFor(() => expect(api.patch).toHaveBeenCalled());
    const [url, payload] = api.patch.mock.calls[0];
    expect(url).toBe('/api/inventory/5/');
    expect(payload.is_catalog).toBe(false);
  });
});
