import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';

vi.mock('@/lib/api.js', () => ({ api: { get: vi.fn() } }));
vi.mock('svelte-spa-router', () => ({ push: vi.fn() }));
vi.mock('@/stores/permissions.js', () => ({
  canManageFinancials: { subscribe: (fn) => { fn(true); return () => {}; } },
}));

import { api } from '@/lib/api.js';
import PurchaseOrderListPage from '@/routes/purchaseorders/PurchaseOrderListPage.svelte';

beforeEach(() => {
  api.get.mockReset();
  api.get.mockResolvedValue({ count: 0, results: [], next: null, previous: null });
});

describe('PurchaseOrderListPage — awaiting-reconciliation filter', () => {
  it('wires the checkbox to the ?awaiting_reconciliation=true query param', async () => {
    const { getByLabelText } = render(PurchaseOrderListPage);
    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    api.get.mockClear();

    await fireEvent.click(getByLabelText('Awaiting reconciliation only'));

    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    const url = api.get.mock.calls[0][0];
    expect(url).toContain('awaiting_reconciliation=true');
  });

  it('omits the param when the checkbox is off', async () => {
    render(PurchaseOrderListPage);
    await vi.waitFor(() => expect(api.get).toHaveBeenCalled());
    const url = api.get.mock.calls[0][0];
    expect(url).not.toContain('awaiting_reconciliation');
  });
});
