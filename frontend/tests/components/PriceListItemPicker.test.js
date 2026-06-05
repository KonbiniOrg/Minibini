import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import PriceListItemPicker from '@/components/PriceListItemPicker.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue({ results: [{ price_list_item_id: 1, code: 'PLI-1', description: 'Steel bar' }] });
});

describe('PriceListItemPicker', () => {
  it('loads the catalog on focus and shows items', async () => {
    const { getByPlaceholderText, findByText } = render(PriceListItemPicker);
    await fireEvent.focus(getByPlaceholderText('Search price list items...'));
    expect(await findByText(/Steel bar/)).toBeInTheDocument();
  });

  it('calls onSelect with the chosen item', async () => {
    const onSelect = vi.fn();
    const { getByPlaceholderText, findByText } = render(PriceListItemPicker, { props: { onSelect } });
    await fireEvent.focus(getByPlaceholderText('Search price list items...'));
    await fireEvent.mouseDown(await findByText(/Steel bar/));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ price_list_item_id: 1 }));
  });

  it('shows the prefilled label from selectedItem', () => {
    const { getByText } = render(PriceListItemPicker, {
      props: { selectedItem: { code: 'PLI-9', description: 'Bolt' } },
    });
    expect(getByText('PLI-9 — Bolt')).toBeInTheDocument();
  });
});
