import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));

import { api } from '@/lib/api.js';
import InventoryListPage from '@/routes/inventory/InventoryListPage.svelte';

const ITEMS = [
  {
    price_list_item_id: 1, code: 'FELT', description: 'grey felt', units: 'sheet',
    qty_on_hand: '5.00', qty_earmarked: '2.00', qty_available: '3.00',
    is_catalog: true, is_active: true, purchase_price: '4.00', selling_price: '8.00',
  },
  {
    price_list_item_id: 2, code: 'LOT-1', description: 'leftover ply', units: 'sheet',
    qty_on_hand: '1.00', qty_earmarked: '0.00', qty_available: '1.00',
    is_catalog: false, is_active: true, purchase_price: '40.00', selling_price: '0.00',
  },
];

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue({ results: ITEMS });
});

describe('InventoryListPage', () => {
  it('renders items with on-hand / earmarked / available and kind', async () => {
    const { findByText, getByText } = render(InventoryListPage);
    expect(await findByText('FELT')).toBeInTheDocument();
    expect(getByText('grey felt')).toBeInTheDocument();
    expect(getByText('leftover ply')).toBeInTheDocument();
    // catalog vs lot kind labels
    expect(getByText('catalog')).toBeInTheDocument();
    expect(getByText('lot')).toBeInTheDocument();
  });

  it('defaults to active-only and excludes finished lots', async () => {
    render(InventoryListPage);
    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    const url = api.get.mock.calls[0][0];
    expect(url).toContain('is_active=true');
    expect(url).not.toContain('include_finished');
  });

  it('requests finished lots when the toggle is checked', async () => {
    const { getByLabelText } = render(InventoryListPage);
    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    await fireEvent.click(getByLabelText('Show finished lots'));
    await vi.waitFor(() => {
      const urls = api.get.mock.calls.map((c) => c[0]);
      expect(urls.some((u) => u.includes('include_finished=true'))).toBe(true);
    });
  });

  it('filters client-side by search text', async () => {
    const { findByText, getByPlaceholderText, queryByText } = render(InventoryListPage);
    await findByText('FELT');
    await fireEvent.input(getByPlaceholderText('code or description'), { target: { value: 'ply' } });
    expect(queryByText('FELT')).toBeNull();
    expect(queryByText('leftover ply')).toBeInTheDocument();
  });
});
