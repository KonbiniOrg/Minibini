import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));

import { api } from '@/lib/api.js';
import { user } from '@/stores/auth.js';
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
  api.post.mockReset();
  api.get.mockResolvedValue({ results: ITEMS });
  api.post.mockResolvedValue({});
  user.set({ username: 'u', permissions: [] });  // no manage by default
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

  it('hides manage actions without an atom', async () => {
    const { findByText, queryByRole } = render(InventoryListPage);
    await findByText('FELT');
    expect(queryByRole('button', { name: '+ New item' })).toBeNull();
    expect(queryByRole('button', { name: 'edit' })).toBeNull();
  });
});

describe('InventoryListPage — manage actions (financials/config)', () => {
  beforeEach(() => {
    user.set({ username: 'fin', permissions: ['can_manage_financials'] });
    vi.stubGlobal('confirm', vi.fn(() => true));
  });

  it('writes off an item with stock', async () => {
    const { findAllByRole } = render(InventoryListPage);
    const writeOffBtns = await findAllByRole('button', { name: 'write off' });
    await fireEvent.click(writeOffBtns[0]);
    await vi.waitFor(() => {
      const urls = api.post.mock.calls.map((c) => c[0]);
      expect(urls.some((u) => u.includes('/write-off/'))).toBe(true);
    });
  });

  it('merges a discard lot into a keep item', async () => {
    const { findByText, getByRole, getByText } = render(InventoryListPage);
    await findByText('FELT');
    await fireEvent.click(getByRole('button', { name: 'Merge items' }));
    const selects = document.querySelectorAll('select');
    // last two selects in the merge panel are keep + discard
    const keepSel = selects[selects.length - 2];
    const discardSel = selects[selects.length - 1];
    await fireEvent.change(keepSel, { target: { value: '1' } });   // FELT (keep)
    await fireEvent.change(discardSel, { target: { value: '2' } }); // LOT-1 (lot)
    await fireEvent.click(getByText('Merge'));
    await vi.waitFor(() => {
      const call = api.post.mock.calls.find((c) => c[0] === '/api/inventory/merge/');
      expect(call).toBeTruthy();
      expect(String(call[1].keep_id)).toBe('1');
      expect(String(call[1].discard_id)).toBe('2');
    });
  });
});
