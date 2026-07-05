import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ push: vi.fn() }));

import { api } from '@/lib/api.js';
import { push } from 'svelte-spa-router';
import { user } from '@/stores/auth.js';
import InventoryListPage from '@/routes/inventory/InventoryListPage.svelte';

const ITEMS = [
  {
    inventory_item_id: 1, code: 'FELT', description: 'grey felt', units: 'sheet',
    qty_on_hand: '5.00', qty_earmarked: '2.00', qty_available: '3.00',
    is_active: true, purchase_price: '4.00', selling_price: '8.00',
  },
  {
    inventory_item_id: 2, code: 'LOT-1', description: 'leftover ply', units: 'sheet',
    qty_on_hand: '1.00', qty_earmarked: '0.00', qty_available: '1.00',
    is_active: false, purchase_price: '40.00', selling_price: '0.00',
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
  it('renders items with on-hand / earmarked / available and status', async () => {
    const { findByText, getByText } = render(InventoryListPage);
    expect(await findByText('FELT')).toBeInTheDocument();
    expect(getByText('grey felt')).toBeInTheDocument();
    expect(getByText('leftover ply')).toBeInTheDocument();
    // active vs inactive status labels
    expect(getByText('active')).toBeInTheDocument();
    expect(getByText('inactive')).toBeInTheDocument();
  });

  it('defaults to active-only', async () => {
    render(InventoryListPage);
    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    const url = api.get.mock.calls[0][0];
    expect(url).toContain('is_active=true');
    expect(url).not.toContain('include_finished');
  });

  it('walks all pages instead of truncating at the 100-item cap', async () => {
    const mk = (id, code) => ({
      inventory_item_id: id, code, description: '', units: 'ea',
      qty_on_hand: '0.00', qty_earmarked: '0.00', qty_available: '0.00',
      is_active: true, purchase_price: '0.00', selling_price: '0.00',
    });
    const page1 = Array.from({ length: 100 }, (_, i) => mk(i + 1, `I${i + 1}`));
    const page2 = [mk(101, 'LAST')];
    api.get.mockImplementation((url) =>
      url.includes('page=2')
        ? Promise.resolve({ results: page2, next: null })
        : Promise.resolve({ results: page1, next: 'http://x/api/inventory/?page=2' }));
    const { findByText } = render(InventoryListPage);
    // The 101st item (only on page 2) must appear → both pages were fetched.
    expect(await findByText('LAST')).toBeInTheDocument();
  });

  it('filters client-side by search text', async () => {
    const { findByText, getByPlaceholderText, queryByText } = render(InventoryListPage);
    await findByText('FELT');
    await fireEvent.input(getByPlaceholderText('code or description'), { target: { value: 'ply' } });
    expect(queryByText('FELT')).toBeNull();
    expect(queryByText('leftover ply')).toBeInTheDocument();
  });

  it('flags a row whose available count is negative', async () => {
    api.get.mockResolvedValue({ results: [{
      inventory_item_id: 9, code: 'OVER', description: 'oversubscribed', units: 'ea',
      qty_on_hand: '1.00', qty_earmarked: '3.00', qty_available: '-2.00',
      is_active: true, purchase_price: '0.00', selling_price: '0.00',
    }] });
    const { findByText } = render(InventoryListPage);
    const row = (await findByText('OVER')).closest('tr');
    expect(row.classList.contains('short')).toBe(true);
  });

  it('does not flag a row with non-negative available', async () => {
    const { findByText } = render(InventoryListPage);  // ITEMS: FELT available 3.00
    const row = (await findByText('FELT')).closest('tr');
    expect(row.classList.contains('short')).toBe(false);
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

  it('shows an order button on every row that navigates to a new PO', async () => {
    push.mockClear();
    const { findAllByRole } = render(InventoryListPage);
    const orderBtns = await findAllByRole('button', { name: 'order' });
    expect(orderBtns.length).toBe(2);  // one per ITEMS row
    await fireEvent.click(orderBtns[0]);  // FELT, inventory_item_id 1
    expect(push).toHaveBeenCalledWith('/purchase-orders/new?inventory_item=1');
  });

  it('hides the order button for a config-only user (PO creation is financials)', async () => {
    user.set({ username: 'cfg', permissions: ['can_manage_config'] });
    const { findAllByRole, queryByRole } = render(InventoryListPage);
    await findAllByRole('button', { name: 'edit' });  // config still manages items
    expect(queryByRole('button', { name: 'order' })).toBeNull();
  });

  it('writes off a partial quantity via the panel', async () => {
    const { findAllByRole, getByText, getByLabelText } = render(InventoryListPage);
    const writeOffBtns = await findAllByRole('button', { name: 'write off' });
    await fireEvent.click(writeOffBtns[0]);  // FELT (5 on hand)
    // Panel opens; qty defaults to the full balance — override to a partial.
    await getByText(/Write off — FELT/);
    await fireEvent.input(getByLabelText(/Quantity to write off/), { target: { value: '2' } });
    await fireEvent.click(getByText('Confirm write-off'));
    await vi.waitFor(() => {
      const call = api.post.mock.calls.find((c) => c[0].includes('/write-off/'));
      expect(call).toBeTruthy();
      expect(String(call[1].qty)).toBe('2');
    });
  });

  it('clicking write off opens a panel and does not post immediately', async () => {
    const { findAllByRole, getByText } = render(InventoryListPage);
    const writeOffBtns = await findAllByRole('button', { name: 'write off' });
    await fireEvent.click(writeOffBtns[0]);
    getByText(/Write off — FELT/);  // panel shown
    expect(api.post).not.toHaveBeenCalled();  // no POST until Confirm
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
